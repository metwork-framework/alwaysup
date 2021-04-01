from typing import Optional
import asyncio
from asyncio.subprocess import Process
import subprocess
import enum
import os
import mflog
from mfutil import get_unique_hexa_identifier, kill_process_and_children
from alwaysup.state import (
    StateMixin,
    OnlyStates,
    OnlyStatesOrRaise,
    NotTheseStatesOrRaise,
)
from alwaysup.utils import (
    log_exceptions,
    AsyncMutuallyExclusive,
)
from alwaysup.cmd import Cmd
from alwaysup.options import Options


class ManagedProcessState(enum.Enum):
    """Enum for describing ManagedProcess possible states."""

    READY = 0  # the object is initialized but not started
    STARTING = 1  # we are starting the process
    RUNNING = 2  # the process is running
    STOPPING = 3  # we are stopping (non-smart) the process
    SMART_STOPPING = 4  # we are smart-stopping the process
    STOPPED = 5  # the process was self-stopped with a 0 return code
    DEAD = 6  # the process was self-stopped with a !=0 return code or by signal


class ManagedProcess(StateMixin):
    """Short lived object which monitor a process.

    After the process stop, we can't reuse this object.

    Attributes:
        id: unique id of the process (for logging only)
        name: (generated) name of the process
        pid: pid of the process (or None)
        returncode: return code of the process (or None)
        logger: logger to use for structured logging
        cmd: FIXME
    """

    def __init__(
        self,
        name_prefix: str,
        cmd: Cmd,
        options: Options = Options(),
    ):
        self.cmd: Cmd = cmd
        self.options = options
        self.id: str = get_unique_hexa_identifier()[0:10]
        self.name: str = f"{name_prefix}.managed_process.{self.id}"
        self.logger = mflog.get_logger("alwaysup.managed_process").bind(id=self.name)
        StateMixin.__init__(self, logger=self.logger)
        self.process: Optional[Process] = None
        self.pid: Optional[int] = None
        self.returncode: Optional[int] = None
        self.set_state(ManagedProcessState.READY)
        self._wait_for_process_end_task: Optional[asyncio.Task] = None
        self.cmd_line: Optional[str] = None

    def is_alive(self) -> bool:
        """Return True if the process still has a pid."""
        return self.state in (
            ManagedProcessState.RUNNING,
            ManagedProcessState.STOPPING,
            ManagedProcessState.SMART_STOPPING,
        )

    async def wait(self) -> None:
        """Wait for the end of the process."""
        while self.state == ManagedProcessState.STARTING:
            await self.wait_for_state_change(0.1)
        if self._wait_for_process_end_task is None:
            return
        await self._wait_for_process_end_task

    async def _wait_for_process_end(self, wait_event: asyncio.Event) -> None:
        """Wait for the process end and set return code.

        If the process self-ended, we change the state dependening on the return code.
        WARNING: this coroutine is not protected by @AsyncMutuallyExclusive

        Args:
            wait_event: asyncio Event to notify when this coroutine is really started.
        """
        self.logger.info("Waiting for process to end...")
        assert self.process is not None  # in RUNNING state, this shouldn't be possible
        wait_event.set()
        self.returncode = await self.process.wait()
        self.logger.info(f"Process ended with returncode: {self.returncode}")
        if self.returncode == 0:
            self.set_state(ManagedProcessState.STOPPED)
        else:
            self.set_state(ManagedProcessState.DEAD)
        self.logger = self.logger.unbind("_pid")
        self.pid = None
        self.process = None

    @AsyncMutuallyExclusive()
    @OnlyStatesOrRaise([ManagedProcessState.READY])
    async def start(self):
        self.logger.info(f"Creating subprocess (shell) with cmd: {self.cmd}")
        self.set_state(ManagedProcessState.STARTING)
        try:
            self.cmd_line = str(self.cmd)
            self.process = await asyncio.create_subprocess_exec(
                self.cmd.program,
                *self.cmd.args,
                stdin=subprocess.DEVNULL,
                stdout=self.cmd.stdoutsubprocess,
                stderr=self.cmd.stderrsubprocess,
            )
        except Exception:
            self.logger.warning(
                "can't launch subprocess because of exception", exc_info=True
            )
            self.set_state(ManagedProcessState.DEAD)
            return
        self.pid = self.process.pid
        self.logger = self.logger.bind(_pid=self.pid)
        self.set_state(ManagedProcessState.RUNNING)
        event = asyncio.Event()
        self._wait_for_process_end_task: asyncio.Task = asyncio.create_task(
            log_exceptions(self._wait_for_process_end(event))
        )
        # let's wait the _wait_for_process_end coroutine to be started
        await event.wait()

    @AsyncMutuallyExclusive()
    @NotTheseStatesOrRaise([ManagedProcessState.READY])
    @OnlyStates([ManagedProcessState.RUNNING])
    async def stop(self):
        smart = self.options.smart_stop
        if not smart:
            return await self._non_smart_stop()
        self.logger.info("Smart stopping process...")
        self.set_state(ManagedProcessState.SMART_STOPPING)
        self._kill(self.options.smart_stop_signal)
        done, _ = await asyncio.wait(
            [self.wait()], timeout=self.options.smart_stop_timeout
        )
        if len(done) != 1:
            self.logger.warning("Timeout of smart stopping => let's kill")
            return await self._non_smart_stop()

    async def _non_smart_stop(self):
        self.set_state(ManagedProcessState.STOPPING)
        self._kill(9)
        await self.wait()

    def _kill(self, signal: int):
        if self.process is None:
            return
        if self.options.recursive_sigkill and signal == 9:
            self.logger.info(
                "Sending signal %i to %i (and children)" % (signal, self.process.pid)
            )
            try:
                kill_process_and_children(self.process.pid)
            except Exception:
                self.logger.warning("can't recursively kill %i", exc_info=True)
        else:
            self.logger.info("Sending signal %i to %i" % (signal, self.process.pid))
            try:
                os.kill(self.process.pid, signal)
            except ProcessLookupError:
                pass
            except Exception:
                self.logger.warning("can't kill %i", exc_info=True)

    @OnlyStates([ManagedProcessState.RUNNING, ManagedProcessState.SMART_STOPPING])
    def kill(self, signal: int):
        self._kill(signal)

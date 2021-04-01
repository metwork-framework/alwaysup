from typing import Optional
import asyncio
import enum
import mflog
from alwaysup.utils import log_exceptions, AsyncMutuallyExclusive
from alwaysup.state import StateMixin, OnlyStates
from alwaysup.cmd import Cmd
from alwaysup.process import ManagedProcess
from alwaysup.options import Options
from alwaysup.status import Status


class ProcessSlotState(enum.Enum):
    STOPPED = 1
    RUNNING = 2
    STOPPING = 3
    STARTING = 4
    SHUTDOWN = 5
    WAITING_FOR_RESTART = 6


class ProcessSlot(StateMixin):
    def __init__(
        self, name_prefix, slot_number, cmd: Cmd, options: Options = Options()
    ):
        self.name_prefix = name_prefix
        self.slot_number: int = slot_number
        self.name = self.name_prefix + "." + str(self.slot_number)
        self.options = options
        self.cmd: Cmd = Cmd.copy_and_add_to_context(cmd, {"SLOT": self.slot_number})
        self.logger = mflog.get_logger("alwaysup.process_slot").bind(id=self.name)
        StateMixin.__init__(self, logger=self.logger)
        self.managed_process: Optional[ManagedProcess] = None
        self.set_state(ProcessSlotState.STOPPED)
        self._manage_task = asyncio.create_task(log_exceptions(self._manage()))
        self._waiting_for_restart_task = None

    def as_dict(self):
        return {
            "cmd_line": self.cmd_line,
            "state": self.state.name,
            "status": self.status.name,
            "state_since": self.seconds_since_latest_state_change(),
            "state_hsince": self.humanized_time_since_latest_state_change(),
            "slot_number": self.slot_number,
            "pid": self.pid,
        }

    @property
    def cmd_line(self) -> Optional[str]:
        if self.managed_process is None:
            return None
        return self.managed_process.cmd_line

    @property
    def status(self) -> Status:
        seconds = self.seconds_since_latest_state_change()
        if seconds is None:
            return Status.NOK
        if self.state == ProcessSlotState.RUNNING and seconds >= 10:
            return Status.OK
        if self.state in [ProcessSlotState.STOPPED, ProcessSlotState.SHUTDOWN]:
            return Status.STOPPED
        if self.state in [ProcessSlotState.WAITING_FOR_RESTART]:
            return Status.NOK
        if (
            self.state in [ProcessSlotState.STARTING, ProcessSlotState.RUNNING]
            and seconds <= 5
        ):
            return Status.NOK
        return Status.WARNING

    @property
    def pid(self) -> Optional[int]:
        if self.managed_process is None:
            return None
        return self.managed_process.pid

    def is_running(self):
        return self.state == ProcessSlotState.RUNNING

    def is_shutdown(self):
        return self.state == ProcessSlotState.SHUTDOWN

    async def _manage(self):
        while self.state != ProcessSlotState.SHUTDOWN:
            if self.state != ProcessSlotState.RUNNING:
                await self.wait_for_state_change(timeout=1.0)
                continue
            await self.managed_process.wait()
            self.managed_process = None
            if self.state == ProcessSlotState.RUNNING:
                # self-stop
                if self.options.autorespawn:
                    self.set_state(ProcessSlotState.WAITING_FOR_RESTART)
                    self._waiting_for_restart_task = asyncio.create_task(
                        self._waiting_for_restart()
                    )
                    await self._waiting_for_restart_task
                    self._waiting_for_restart_task = None
                    await self._autorestart()
                else:
                    self.set_state(ProcessSlotState.STOPPED)

    async def _waiting_for_restart(self):
        await asyncio.sleep(self.options.waiting_for_restart_delay)

    @AsyncMutuallyExclusive()
    @OnlyStates([ProcessSlotState.STOPPED, ProcessSlotState.WAITING_FOR_RESTART])
    async def start(self):
        if (
            self.state == ProcessSlotState.WAITING_FOR_RESTART
            and self._waiting_for_restart_task is not None
        ):
            self._waiting_for_restart_task.cancel()
        return await self._start()

    @AsyncMutuallyExclusive(wait=False)
    @OnlyStates([ProcessSlotState.WAITING_FOR_RESTART])
    async def _autorestart(self):
        return await self._start()

    async def _start(self):
        self.logger.info("Process slot is starting")
        self.set_state(ProcessSlotState.STARTING)
        self.managed_process = ManagedProcess(self.name, self.cmd)
        await self.managed_process.start()
        self.set_state(ProcessSlotState.RUNNING)
        self.logger.info("Process slot started")

    @AsyncMutuallyExclusive()
    @OnlyStates(
        [
            ProcessSlotState.STOPPED,
            ProcessSlotState.RUNNING,
            ProcessSlotState.WAITING_FOR_RESTART,
        ]
    )
    async def shutdown(self):
        await self._stop()
        self.set_state(ProcessSlotState.SHUTDOWN)
        await self.wait()
        self.logger.info("Process slot is shutdown")

    @AsyncMutuallyExclusive()
    @OnlyStates([ProcessSlotState.RUNNING, ProcessSlotState.WAITING_FOR_RESTART])
    async def stop(self):
        return await self._stop()

    async def _stop(self):
        if self.state == ProcessSlotState.WAITING_FOR_RESTART:
            if self._waiting_for_restart_task is not None:
                self._waiting_for_restart_task.cancel()
            self.set_state(ProcessSlotState.STOPPED)
            return
        self.logger.info("Stopping process slot")
        self.set_state(ProcessSlotState.STOPPING)
        if self.managed_process is not None:
            await self.managed_process.stop()
        self.set_state(ProcessSlotState.STOPPED)
        self.logger.info("Process slot stopped")

    async def wait(self):
        await self._manage_task

    @OnlyStates([ProcessSlotState.RUNNING, ProcessSlotState.STOPPING])
    def kill(self, signal: int):
        if self.managed_process is not None:
            return self.managed_process.kill(signal)

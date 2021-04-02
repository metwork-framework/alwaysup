from typing import List, Dict, Any, cast
import shlex
import copy
import json
import enum
import os
import subprocess
import jinja2
from pydantic.dataclasses import dataclass
from dataclasses import field


DEFAULT_STDXXX_ROTATION_SIZE = 104857600
DEFAULT_STDXXX_ROTATION_TIME = 86400
DEFAULT_STDOUT = "NULL"
DEFAULT_STDERR = "STDOUT"


class Templating(enum.Enum):

    NO = 0
    JINJA2 = 1


class StdxxxHandler(enum.Enum):

    NULL = 0
    LOG_PROXY_WRAPPER = 1
    AUTO = 2


@dataclass(frozen=True)
class CmdConfiguration:
    """Dataclass which holds execution options for Cmd.

    Following attributes can contain some templating placeholders:
    program, args, stdout, stderr

    Attributes:
        program: the program to execute (fullpath).
        args: prog arguments.
        smart_stop: if True, try to (smart) stop a process.
        smart_stop_signal: signal used to (smart) stop a process.
        smart_stop_timeout: the timeout (seconds) after smart_stop_signal, after that
            send SIGKILL.
        waiting_for_restart_delay: wait this delay (in seconds) before an automatic
            restart.
        autorespawn: if True, autorestart a crashed process.
        autostart: if True, start the process during service startup.
        recursive_sigkill: if True, send SIGKILL recursively (to the orignal process
            and its children processes).
        templating: templating system to use for args and options.
        clean_env: if True, launch process with a clean env (and do not inherit from
            the parent process).
        extra_envs: extra environment variables to add before the process launch.
        stdout: full path to redirect stdout (special values: NULL => ignore stdout)
        stderr: full path to redirect stderr (special values: NULL => ignore stderr,
            STDOUT => redirect to the same destination than stdout).
        stdxxx_handler: method to use for stdxxx capture.
        stdxxx_rotation_size: maximum size (in bytes) of a stdxxx file before rotation
            (for LOG_PROXY_WRAPPER stdxxx_handler only).
        stdxxx_rotation_time: maximum size (in seconds) of a stdxxx file before rotation
            (for LOG_PROXY_WRAPPER stdxxx_handler only).

    """

    program: str
    args: List[str] = field(default_factory=lambda: [])
    smart_stop: bool = True
    smart_stop_signal: int = 15
    smart_stop_timeout: float = 5.0
    waiting_for_restart_delay: float = 1.0
    autorespawn: bool = True
    autostart: bool = True
    stdxxx_handler: StdxxxHandler = StdxxxHandler.AUTO
    stdxxx_rotation_size: int = DEFAULT_STDXXX_ROTATION_SIZE
    stdxxx_rotation_time: int = DEFAULT_STDXXX_ROTATION_TIME
    stdout: str = DEFAULT_STDOUT
    stderr: str = DEFAULT_STDERR
    recursive_sigkill: bool = True
    jinja2: bool = True
    clean_env: bool = False
    extra_envs: Dict[str, str] = field(default_factory=lambda: {})
    templating: Templating = Templating.JINJA2

    @classmethod
    def from_json(cls, path: str) -> "CmdConfiguration":
        with open(path, "r") as f:
            c = f.read()
        kwargs: Dict[str, Any] = json.loads(c)
        if "templating" in kwargs:
            kwargs["templating"] = Templating[kwargs["templating"].upper()]
        if "stdxxx_handler" in kwargs:
            kwargs["stdxxx_handler"] = StdxxxHandler[kwargs["stdxxx_handler"].upper()]
        return cls(**kwargs)  # type: ignore

    @classmethod
    def from_shell(cls, shell_cmd: str) -> "CmdConfiguration":
        tmp = shlex.split(shell_cmd)
        return cls(program=tmp[0], args=tmp[1:])  # type: ignore


class Cmd:
    """CmdConfiguration wrapper to expose resolved values (depending on context).

    The context is mainly environment variables. But you can add some extra context
    in the constructor.

    Attributes:
        config: the configuration
        context: the context to use for templating evaluation

    """

    def __init__(
        self,
        config: CmdConfiguration,
        extra_context: Dict[str, str] = {},
    ):
        self.context = dict(os.environ)
        self.context.update(extra_context)
        self.config = config

    @property
    def stdxxx_handler(self) -> StdxxxHandler:
        """Get the handler to use for stdxxx management.

        AUTO value is resolved here, so it can't be returned by this method.

        """
        if self.config.stdxxx_handler != StdxxxHandler.AUTO:
            return self.config.stdxxx_handler
        if self.config.stdout.lower() in (
            "null",
            "pipe",
        ) and self.config.stderr.lower() in (
            "null",
            "stdout",
            "pipe",
        ):
            return StdxxxHandler.NULL
        return StdxxxHandler.LOG_PROXY_WRAPPER

    @property
    def stdoutsubprocess(self) -> int:
        return self._stdxxxsubprocesss(self.config.stdout)

    @property
    def stderrsubprocess(self) -> int:
        return self._stdxxxsubprocesss(self.config.stderr)

    @property
    def program(self) -> str:
        if self.stdxxx_handler == StdxxxHandler.LOG_PROXY_WRAPPER:
            return "log_proxy_wrapper"
        else:
            return self._jinja2(self.config.program)

    @property
    def autostart(self) -> bool:
        return self.config.autostart

    @property
    def autorespawn(self) -> bool:
        return self.config.autorespawn

    @property
    def waiting_for_restart_delay(self) -> float:
        return self.config.waiting_for_restart_delay

    @property
    def recursive_sigkill(self) -> bool:
        return self.config.recursive_sigkill

    @property
    def smart_stop_signal(self) -> int:
        return self.config.smart_stop_signal

    @property
    def smart_stop_timeout(self) -> float:
        return self.config.smart_stop_timeout

    @property
    def smart_stop(self) -> bool:
        return self.config.smart_stop

    @property
    def args(self) -> List[str]:
        tmp_args: List[str] = list(self.config.args)
        if self.stdxxx_handler == StdxxxHandler.LOG_PROXY_WRAPPER:
            extra_args: List[str] = []
            if self.config.stdxxx_rotation_size != DEFAULT_STDXXX_ROTATION_SIZE:
                extra_args.append(
                    "--rotation-size=%i" % self.config.stdxxx_rotation_size
                )
            if self.config.stdxxx_rotation_time != DEFAULT_STDXXX_ROTATION_TIME:
                extra_args.append(
                    "--rotation-time=%i" % self.config.stdxxx_rotation_time
                )
            if self.config.stdout != DEFAULT_STDOUT:
                extra_args.append("--stdout=%s" % self._jinja2(self.config.stdout))
            if self.config.stdout != DEFAULT_STDERR:
                extra_args.append("--stderr=%s" % self._jinja2(self.config.stderr))
            tmp_args = (
                extra_args + ["--use-locks", "--", self.config.program] + tmp_args
            )
        return [self._jinja2(x) for x in tmp_args]

    def _jinja2(self, value: str) -> str:
        if self.config.templating == Templating.JINJA2:
            t = jinja2.Template(value)
            return t.render(self.context)
        return value

    def _stdxxxsubprocesss(self, stdxxx: str) -> int:
        if self.stdxxx_handler == StdxxxHandler.LOG_PROXY_WRAPPER:
            return subprocess.DEVNULL
        elif stdxxx.lower() == "pipe":
            return subprocess.PIPE
        return subprocess.DEVNULL

    @classmethod
    def make_from_shell_cmd(cls, shell_cmd: str, **extra_configuration) -> "Cmd":
        tmp = shlex.split(shell_cmd)
        kwargs: Dict[str, Any] = {"program": tmp[0], "args": tmp[1:]}
        kwargs.update(extra_configuration)
        return cls(CmdConfiguration(**kwargs))  # type: ignore

    def copy_and_add_to_context(self, to_add: Dict[str, Any]) -> "Cmd":
        new = cast("Cmd", copy.deepcopy(self))
        for key, value in to_add.items():
            new.context[key] = str(value)
        return new

    def __str__(self):
        return " ".join([self.program] + self.args)

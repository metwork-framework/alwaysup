from typing import List, Dict, Any, cast
import shlex
import copy
import os
import subprocess
import enum
import jinja2
from alwaysup.options import (
    Options,
    DEFAULT_STDXXX_ROTATION_SIZE,
    DEFAULT_STDXXX_ROTATION_TIME,
    DEFAULT_STDOUT,
    DEFAULT_STDERR,
)


class StdXxxMethod(enum.Enum):

    NULL = 0
    LOG_PROXY_WRAPPER = 1


class Cmd:
    def __init__(
        self,
        program: str,
        args: List[str],
        options: Options = Options(),
        context: Dict[str, str] = {},
    ):
        self.options: Options = options
        self.context = os.environ
        self.context.update(context)
        self._program = program
        self._args = args
        if self._stdxxx_method() == StdXxxMethod.LOG_PROXY_WRAPPER:
            self._program = "log_proxy_wrapper"
            self._args = []
            if self.options.stdxxx_use_locks:
                self._args.append("--use-locks")
            if self.options.stdxxx_rotation_size != DEFAULT_STDXXX_ROTATION_SIZE:
                self._args.append(
                    "--rotation-size=%i" % self.options.stdxxx_rotation_size
                )
            if self.options.stdxxx_rotation_time != DEFAULT_STDXXX_ROTATION_TIME:
                self._args.append(
                    "--rotation-time=%i" % self.options.stdxxx_rotation_time
                )
            if self.options.stdout != DEFAULT_STDOUT:
                self._args.append("--stdout=%s" % self._jinja2(self.options.stdout))
            if self.options.stdout != DEFAULT_STDERR:
                self._args.append("--stderr=%s" % self._jinja2(self.options.stderr))
            self._args.append("--")
            self._args.append(program)
            self._args = self._args + args

    def _jinja2(self, value: str) -> str:
        if not self.options.jinja2:
            return value
        t = jinja2.Template(value)
        return t.render(self.context)

    @property
    def program(self) -> str:
        return self._jinja2(self._program)

    @property
    def args(self) -> List[str]:
        return [self._jinja2(x) for x in self._args]

    def _stdxxxsubprocesss(self, stdxxx: str) -> int:
        if self._stdxxx_method() == StdXxxMethod.LOG_PROXY_WRAPPER:
            return subprocess.DEVNULL
        elif stdxxx.lower() == "pipe":
            return subprocess.PIPE
        return subprocess.DEVNULL

    def _stdxxx_method(self) -> StdXxxMethod:
        if self.options.stdxxx_method.lower() == "auto":
            if self.options.stdout.lower() in (
                "null",
                "pipe",
            ) and self.options.stderr.lower() in ("null", "stdout", "pipe",):
                return StdXxxMethod.NULL
        return StdXxxMethod.LOG_PROXY_WRAPPER

    @property
    def stdoutsubprocess(self) -> int:
        return self._stdxxxsubprocesss(self.options.stdout)

    @property
    def stderrsubprocess(self) -> int:
        return self._stdxxxsubprocesss(self.options.stderr)

    @classmethod
    def make_from_shell_cmd(cls, shell_cmd: str) -> "Cmd":
        tmp = shlex.split(shell_cmd)
        return Cmd(tmp[0], tmp[1:])

    @classmethod
    def copy_and_add_to_context(self, **to_add: Dict[str, Any]) -> "Cmd":
        new = cast("Cmd", copy.deepcopy(self))
        for key, value in to_add.items():
            new.context[key] = str(value)
        return new

    def __str__(self):
        return " ".join([self.program] + self.args)

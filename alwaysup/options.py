from typing import Dict
from pydantic.dataclasses import dataclass


DEFAULT_STDXXX_ROTATION_SIZE = 104857600
DEFAULT_STDXXX_ROTATION_TIME = 86400
DEFAULT_STDOUT = "NULL"
DEFAULT_STDERR = "STDOUT"
DEFAULT_STDXXX_METHOD = "AUTO"


@dataclass(frozen=True)
class Options:
    smart_stop: bool = True
    smart_stop_signal: int = 15
    smart_stop_timeout: float = 5.0
    waiting_for_restart_delay: float = 1.0
    autorespawn: bool = True
    autostart: bool = True
    stdxxx_method: str = DEFAULT_STDXXX_METHOD
    stdxxx_rotation_size: int = DEFAULT_STDXXX_ROTATION_SIZE
    stdxxx_rotation_time: int = DEFAULT_STDXXX_ROTATION_TIME
    stdxxx_use_locks: bool = True
    stdout: str = DEFAULT_STDOUT
    stderr: str = DEFAULT_STDERR
    recursive_sigkill: bool = True
    jinja2: bool = True
    clean_env: bool = False
    extra_envs: Dict[str, str] = {}

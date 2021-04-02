from typing import Deque, Optional, List
import asyncio
import inspect
import enum
import humanize
import datetime
from collections import deque
from contextlib import suppress
from functools import wraps


class UnknownState(enum.Enum):
    """Unknown state."""

    UNKNOWN = 0


class StateMixin:
    def __init__(self, *args, **kwargs):
        self.__logger = kwargs.get("logger", None)
        self.__state: enum.Enum = None
        self.__listened_events: Deque[asyncio.Event] = deque()
        self.__latest_state_change: datetime.datetime = None

    @property
    def state(self) -> enum.Enum:
        return self.get_state()

    def seconds_since_latest_state_change(self) -> Optional[float]:
        if self.__latest_state_change is None:
            return None
        now = datetime.datetime.utcnow()
        return (now - self.__latest_state_change).total_seconds()

    def humanized_time_since_latest_state_change(self) -> Optional[str]:
        s = self.seconds_since_latest_state_change()
        if s is None:
            return None
        return humanize.naturaltime(s)

    def set_state(self, new_state: enum.Enum) -> None:
        if self.__state != new_state:
            if self.__logger is not None and self.__state is not None:
                self.__logger.debug(
                    f"State changed {self.__state.name} => {new_state.name}"
                )
            self.__state = new_state
            self.__latest_state_change = datetime.datetime.utcnow()
            while True:
                try:
                    event = self.__listened_events.popleft()
                except IndexError:
                    break
                if not event.is_set():
                    event.set()

    def get_state(self) -> enum.Enum:
        if self.__state is None:
            return UnknownState.UNKNOWN
        return self.__state

    async def wait_for_state_change(self, timeout: float = None) -> bool:
        with suppress(asyncio.CancelledError):
            aioevent = asyncio.Event()
            self.__listened_events.append(aioevent)
            try:
                tk = asyncio.create_task(aioevent.wait())
                await asyncio.wait_for(tk, timeout=timeout)
            except asyncio.TimeoutError:
                aioevent.set()
                return False
        return True


class OnlyStates:
    def __init__(self, states: List):
        self.states = states

    def __call__(self, f):
        @wraps(f)
        def wrapper(obj, *args, **kwargs):
            if not isinstance(obj, StateMixin):
                raise Exception("the class must inherit from StateMixin")
            state = obj.state
            if state not in self.states:
                if inspect.iscoroutinefunction(f):
                    fut = asyncio.Future()
                    fut.set_result(None)
                    return fut
                return None
            return f(obj, *args, **kwargs)

        return wrapper


class OnlyStatesOrRaise:
    def __init__(self, states: List):
        self.states = states

    def __call__(self, f):
        @wraps(f)
        def wrapper(obj, *args, **kwargs):
            if not isinstance(obj, StateMixin):
                raise Exception("the class must inherit from StateMixin")
            state = obj.state
            if state not in self.states:
                raise Exception(
                    "invalid state: %s (must be %s)"
                    % (
                        state.name,
                        " or ".join([x.name for x in self.states]),
                    )
                )
            return f(obj, *args, **kwargs)

        return wrapper


class NotTheseStatesOrRaise:
    def __init__(self, states: List):
        self.states = states

    def __call__(self, f):
        @wraps(f)
        def wrapper(obj, *args, **kwargs):
            if not isinstance(obj, StateMixin):
                raise Exception("the class must inherit from StateMixin")
            state = obj.state
            if state in self.states:
                raise Exception("invalid state: %s" % (state.name,))
            return f(obj, *args, **kwargs)

        return wrapper

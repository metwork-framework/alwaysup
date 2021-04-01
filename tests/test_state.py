import enum
import asyncio
import pytest
from alwaysup.state import StateMixin, OnlyStates, OnlyStatesOrRaise


class S(enum.Enum):
    S1 = 0
    S2 = 1


class OnlyStatesTest(StateMixin):

    def __init__(self):
        StateMixin.__init__(self)
        self.func_called = False

    @OnlyStates([S.S1])
    def func(self, *args, **kwargs):
        self.func_called = True
        return True

    @OnlyStates([S.S1])
    async def async_func(self, *args, **kwargs):
        self.func_called = True
        return True

    @OnlyStatesOrRaise([S.S1])
    def func2(self, *args, **kwargs):
        self.func_called = True
        return True


def test_just_created_state():
    a = StateMixin()
    assert a.seconds_since_latest_state_change() is None
    assert a.get_state().name == "UNKNOWN"


def test_basic_state():
    a = StateMixin()
    a.set_state(S.S1)
    assert a.state == S.S1
    assert a.seconds_since_latest_state_change() > 0.0


@pytest.mark.asyncio
async def test_publish():
    a = StateMixin()
    a.set_state(S.S1)
    task = asyncio.create_task(a.wait_for_state_change())
    await asyncio.sleep(1)
    a.set_state(S.S2)
    done, pending = await asyncio.wait([task])
    assert len(done) == 1
    tk = done.pop()
    assert tk.done
    assert tk.result() is True


def test_logger():
    class FakeLogger:
        def __init__(self):
            self.debug_called = False

        def debug(self, *args, **kwargs):
            self.debug_called = True

    fake = FakeLogger()
    a = StateMixin(logger=fake)
    a.set_state(S.S1)
    assert not fake.debug_called
    a.set_state(S.S2)
    assert fake.debug_called


@pytest.mark.asyncio
async def test_wait_timeout():
    a = StateMixin()
    a.set_state(S.S1)
    res = await a.wait_for_state_change(timeout=0.1)
    assert res is False


def test_only_states1():
    a = OnlyStatesTest()
    a.set_state(S.S1)
    assert a.func() is True
    assert a.func_called is True
    a.func_called = False
    a.set_state(S.S2)
    assert a.func() is None
    assert a.func_called is False


@pytest.mark.asyncio
async def test_only_states2():
    a = OnlyStatesTest()
    a.set_state(S.S1)
    assert await a.async_func() is True
    assert a.func_called is True
    a.func_called = False
    a.set_state(S.S2)
    assert await a.async_func() is None
    assert a.func_called is False


def test_only_states_or_raise():
    a = OnlyStatesTest()
    a.set_state(S.S1)
    assert a.func2() is True
    assert a.func_called is True
    a.func_called = False
    a.set_state(S.S2)
    with pytest.raises(Exception):
        a.func2()
    assert a.func_called is False

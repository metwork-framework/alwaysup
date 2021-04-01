import pytest
import asyncio
import mflog
from alwaysup.utils import log_exceptions, AsyncMutuallyExclusive
from alwaysup.state import StateMixin


class MutuallyExclusiveTest(StateMixin):

    def __init__(self):
        StateMixin.__init__(self)
        self.func1_called = False
        self.func2_called = False
        self.func2_is_running = False

    @AsyncMutuallyExclusive()
    async def func1(self, *args, **kwargs):
        print("start func1")
        if self.func2_is_running:
            raise Exception("func2 is running")
        self.func1_called = True
        await asyncio.sleep(1)
        if self.func2_is_running:
            raise Exception("func2 is running")
        print("end func1")

    @AsyncMutuallyExclusive(False)
    async def func2(self, *args, **kwargs):
        print("start func2")
        self.func2_is_running = True
        self.func2_called = True
        await asyncio.sleep(1)
        self.func2_is_running = False
        print("end func2")


async def delayed_start(f, sleep=0.1):
    await asyncio.sleep(sleep)
    await f()


@pytest.mark.asyncio
async def test_log_exceptions(mocker):
    async def mycoro():
        raise Exception("foo")
    mocker.patch("mflog.exception")
    await log_exceptions(mycoro())
    mflog.exception.assert_called_once()


@pytest.mark.asyncio
async def test_mexclusive1():
    a = MutuallyExclusiveTest()
    task1 = asyncio.create_task(a.func1())
    task2 = asyncio.create_task(delayed_start(a.func2))
    await asyncio.wait([task1, task2])
    assert a.func1_called is True
    assert a.func2_called is False


@pytest.mark.asyncio
async def test_mexclusive2():
    a = MutuallyExclusiveTest()
    task1 = asyncio.create_task(a.func2())
    task2 = asyncio.create_task(delayed_start(a.func1))
    await asyncio.wait([task1, task2])
    assert a.func1_called is True
    assert a.func2_called is True

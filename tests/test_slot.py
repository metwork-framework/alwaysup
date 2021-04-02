import pytest
import os
import asyncio
from alwaysup.slot import ProcessSlot, ProcessSlotState
from alwaysup.cmd import Cmd

DIR = os.path.dirname(os.path.realpath(__file__))


@pytest.mark.asyncio
async def test_slot1():
    a = ProcessSlot(
        "foo", 0, Cmd.make_from_shell_cmd("sleep 1", waiting_for_restart_delay=0)
    )
    await a.start()
    assert a.pid > 0
    a.as_dict()
    assert a.state == ProcessSlotState.RUNNING
    assert a.is_running()
    await asyncio.sleep(2)
    await a.shutdown()
    assert a.is_shutdown()
    await a.wait()


@pytest.mark.asyncio
async def test_slot2():
    a = ProcessSlot(
        "foo", 0, Cmd.make_from_shell_cmd("sleep 1", waiting_for_restart_delay=3000)
    )
    await a.start()
    assert a.pid > 0
    a.as_dict()
    assert a.state == ProcessSlotState.RUNNING
    assert a.is_running()
    await asyncio.sleep(2)
    assert a.state == ProcessSlotState.WAITING_FOR_RESTART
    await a.shutdown()
    assert a.is_shutdown()
    await a.wait()

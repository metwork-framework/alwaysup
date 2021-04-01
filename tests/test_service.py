import pytest
import os
import asyncio
from alwaysup.service import Service
from alwaysup.cmd import Cmd
from alwaysup.options import Options

DIR = os.path.dirname(os.path.realpath(__file__))


@pytest.mark.asyncio
async def test_basic():
    options = Options(waiting_for_restart_delay=0)
    a = Service("foo", 3, Cmd.make_from_shell_cmd("sleep 10"), options)
    await a.start()
    assert a.is_running()
    a.as_dict()
    await asyncio.sleep(1)
    await a.shutdown()
    await a.wait()
    assert a.is_shutdown()


@pytest.mark.asyncio
async def test_scaling_up():
    options = Options(waiting_for_restart_delay=0)
    a = Service("foo", 3, Cmd.make_from_shell_cmd("sleep 10"), options)
    await a.start()
    assert a.number_of_slots_running() == 3
    await asyncio.sleep(1)
    await a.set_slot_number(6)
    assert a.number_of_slots_running() == 6
    await asyncio.sleep(1)
    await a.shutdown()
    await a.wait()


@pytest.mark.asyncio
async def test_scaling_down():
    options = Options(waiting_for_restart_delay=0)
    a = Service("foo", 3, Cmd.make_from_shell_cmd("sleep 10"), options)
    await a.start()
    assert a.number_of_slots_running() == 3
    await asyncio.sleep(1)
    await a.set_slot_number(1)
    assert a.number_of_slots_running() == 1
    await asyncio.sleep(1)
    await a.shutdown()
    await a.wait()

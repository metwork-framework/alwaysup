import pytest
import os
import asyncio
from alwaysup.process import ManagedProcess, ManagedProcessState
from alwaysup.cmd import Cmd

DIR = os.path.dirname(os.path.realpath(__file__))


@pytest.mark.asyncio
async def test_ready():
    a = ManagedProcess("foo", Cmd.make_from_shell_cmd("true"))
    assert a.state == ManagedProcessState.READY


@pytest.mark.asyncio
async def test_start():
    a = ManagedProcess("foo", Cmd.make_from_shell_cmd("sleep 1"))
    await a.start()
    assert a.state == ManagedProcessState.RUNNING
    assert a.pid > 0
    assert a.is_alive()
    assert a.returncode is None
    await a.wait()
    assert a.state == ManagedProcessState.STOPPED
    assert a.returncode == 0
    assert a.pid is None
    assert not a.is_alive()


@pytest.mark.asyncio
async def test_stop():
    a = ManagedProcess("foo", Cmd.make_from_shell_cmd("sleep 1"))
    await a.start()
    assert a.state == ManagedProcessState.RUNNING
    assert a.pid > 0
    assert a.returncode is None
    await a.stop()
    assert a.state == ManagedProcessState.DEAD
    assert a.returncode != 0
    assert a.pid is None


@pytest.mark.asyncio
async def test_smart_stop1():
    a = ManagedProcess("foo", Cmd.make_from_shell_cmd(f"{DIR}/smart_stop.py"))
    await a.start()
    assert a.state == ManagedProcessState.RUNNING
    assert a.pid > 0
    assert a.returncode is None
    await a.stop()
    assert a.state == ManagedProcessState.DEAD
    assert a.returncode == -15
    assert a.pid is None


@pytest.mark.asyncio
async def test_smart_stop2():
    a = ManagedProcess("foo", Cmd.make_from_shell_cmd(f"{DIR}/smart_stop.py 60"))
    await a.start()
    await asyncio.sleep(1)
    assert a.state == ManagedProcessState.RUNNING
    assert a.pid > 0
    assert a.returncode is None
    await a.stop()
    assert a.state == ManagedProcessState.DEAD
    assert a.returncode == -9
    assert a.pid is None


@pytest.mark.asyncio
async def test_misc():
    a = ManagedProcess("foo", Cmd.make_from_shell_cmd("/foo/bar/does_not_exist"))
    await a.start()
    await a.wait()
    assert a.state == ManagedProcessState.DEAD

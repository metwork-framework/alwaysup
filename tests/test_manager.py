import pytest
import os
import asyncio
from alwaysup.manager import Manager
from alwaysup.service import Service
from alwaysup.cmd import Cmd
from alwaysup.options import Options

DIR = os.path.dirname(os.path.realpath(__file__))


@pytest.mark.asyncio
async def test_basic():
    options = Options(waiting_for_restart_delay=0)
    x = Manager()
    assert x.is_running()
    a = Service("foo", 3, Cmd.make_from_shell_cmd("sleep 10"), options)
    await x.add_service(a)
    assert len(x.as_dict()["services"]) > 0
    assert a.is_running()
    await asyncio.sleep(1)
    await x.shutdown()
    await x.wait()
    assert x.is_shutdown()
    assert a.is_shutdown()

from typing import Dict
import enum
import mflog
import asyncio
from alwaysup.state import StateMixin, OnlyStates
from alwaysup.slot import ProcessSlot
from alwaysup.cmd import Cmd
from alwaysup.utils import AsyncMutuallyExclusive
from alwaysup.status import Status, list_of_status_to_status


class ServiceState(enum.Enum):
    """Service state enum."""

    RUNNING = 1
    STOPPED = 2
    STOPPING = 5
    SHUTDOWN = 4
    STARTING = 6
    SCALING_UP = 7
    SCALING_DOWN = 8


class Service(StateMixin):
    def __init__(self, name: str, slot_number: int, cmd: Cmd):
        self.name: str = name
        self.cmd: Cmd = cmd
        self.logger = mflog.get_logger("alwaysup.service").bind(id=self.name)
        StateMixin.__init__(self, logger=self.logger)
        self.slots: Dict[int, ProcessSlot] = {}
        self.slot_number: int = slot_number
        self.set_state(ServiceState.STOPPED)

    @property
    def status(self) -> Status:
        if self.state in [ServiceState.STOPPED, ServiceState.SHUTDOWN]:
            return Status.STOPPED
        statuses = [x.status for x in self.slots.values()]
        if self.state in [
            ServiceState.STOPPING,
            ServiceState.STARTING,
            ServiceState.SCALING_UP,
            ServiceState.SCALING_DOWN,
        ]:
            statuses.append(Status.WARNING)
        return list_of_status_to_status(statuses)

    def as_dict(self):
        return {
            "name": self.name,
            "cmd": self.cmd,
            "state": self.state.name,
            "status": self.status.name,
            "state_since": self.seconds_since_latest_state_change(),
            "state_hsince": self.humanized_time_since_latest_state_change(),
            "slot_number": self.slot_number,
            "number_of_slots_running": self.number_of_slots_running(),
            "slots": {x: y.as_dict() for x, y in self.slots.items()},
        }

    def is_running(self):
        return self.state == ServiceState.RUNNING

    def is_shutdown(self):
        return self.state == ServiceState.SHUTDOWN

    def number_of_slots_running(self):
        return len([x for x in self.slots.values() if x.is_running()])

    @property
    def autostart(self):
        return self.cmd.autostart

    @AsyncMutuallyExclusive()
    @OnlyStates([ServiceState.STOPPED])
    async def start(self):
        self.logger.info("Service is starting")
        self.set_state(ServiceState.STARTING)
        for i in range(0, self.slot_number):
            await self._start_slot(i)
        self.set_state(ServiceState.RUNNING)
        self.logger.info("Service started")

    async def _start_slot(self, i):
        slot = ProcessSlot(self.name, i, self.cmd)
        await slot.start()
        self.slots[i] = slot

    @AsyncMutuallyExclusive()
    @OnlyStates([ServiceState.RUNNING])
    async def stop(self) -> None:
        await self._stop_or_shutdown(shutdown=False)

    async def _stop_or_shutdown(self, shutdown=True):
        self.logger.info("Service is stopping")
        self.set_state(ServiceState.STOPPING)
        if len(self.slots) > 0:
            if shutdown:
                await asyncio.wait([x.shutdown() for x in self.slots.values()])
            else:
                await asyncio.wait([x.stop() for x in self.slots.values()])
        if shutdown:
            self.set_state(ServiceState.SHUTDOWN)
            self.logger.info("Service is shutdown")
        else:
            self.set_state(ServiceState.STOPPED)
            self.logger.info("Service is stopped")

    @AsyncMutuallyExclusive()
    @OnlyStates([ServiceState.RUNNING, ServiceState.STOPPED])
    async def shutdown(self):
        await self._stop_or_shutdown(shutdown=True)
        self.set_state(ServiceState.SHUTDOWN)
        await self.wait()

    @AsyncMutuallyExclusive()
    @OnlyStates([ServiceState.RUNNING, ServiceState.STOPPED])
    async def set_slot_number(self, slot_number: int) -> None:
        if self.state == ServiceState.STOPPED:
            self.slot_number = slot_number
            return
        if slot_number > self.slot_number:
            old_slot_number = self.slot_number
            self.slot_number = slot_number
            self.logger.info(
                f"Service is scaling up {self.slot_number} => {slot_number}"
            )
            self.set_state(ServiceState.SCALING_UP)
            for i in range(old_slot_number, slot_number):
                await self._start_slot(i)
            self.set_state(ServiceState.RUNNING)
        elif slot_number < self.slot_number:
            old_slot_number = self.slot_number
            self.slot_number = slot_number
            self.logger.info(
                f"Service is scaling down {self.slot_number} => {slot_number}"
            )
            self.set_state(ServiceState.SCALING_DOWN)
            for i in range(slot_number, old_slot_number):
                slot = self.slots.pop(i)
                await slot.shutdown()
            self.set_state(ServiceState.RUNNING)
        else:
            # no change
            return

    async def wait(self):
        while self.state != ServiceState.SHUTDOWN:
            await self.wait_for_state_change(1.0)

    @OnlyStates(
        [ServiceState.RUNNING, ServiceState.SCALING_DOWN, ServiceState.STOPPING]
    )
    def kill(self, signal: int):
        for slot in self.slots.values():
            slot.kill(signal)

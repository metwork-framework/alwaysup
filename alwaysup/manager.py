from typing import Dict
import enum
import asyncio
import mflog
from alwaysup.service import Service
from alwaysup.state import StateMixin, OnlyStatesOrRaise, OnlyStates
from alwaysup.utils import AsyncMutuallyExclusive
from alwaysup.status import Status, list_of_status_to_status


class ManagerState(enum.Enum):
    RUNNING = 1
    SHUTDOWN = 2
    STOPPING = 5


class Manager(StateMixin):
    def __init__(self):
        self.logger = mflog.get_logger("alwaysup.manager")
        StateMixin.__init__(self)
        self.services: Dict[str, Service] = {}
        self.set_state(ManagerState.RUNNING)
        self.logger.info("Manager started")

    @property
    def status(self) -> Status:
        if self.state in [ManagerState.SHUTDOWN]:
            return Status.STOPPED
        statuses = [x.status for x in self.services.values()]
        if self.state == ManagerState.STOPPING:
            statuses.append(Status.WARNING)
        return list_of_status_to_status(statuses)

    def is_running(self):
        return self.state == ManagerState.RUNNING

    def is_shutdown(self):
        return self.state == ManagerState.SHUTDOWN

    def as_dict(self):
        return {
            "state": self.state.name,
            "status": self.status.name,
            "state_since": self.seconds_since_latest_state_change(),
            "state_hsince": self.humanized_time_since_latest_state_change(),
            "services": {x: y.as_dict() for x, y in self.services.items()},
        }

    @AsyncMutuallyExclusive()
    @OnlyStatesOrRaise([ManagerState.RUNNING])
    async def stop_all(self):
        self._stop_or_shutdown_all(shutdown=False)

    async def _stop_or_shutdown_all(self, shutdown=True):
        if len(self.services) > 0:
            if shutdown:
                tasks = [x.shutdown() for x in self.services.values()]
            else:
                tasks = [x.stop() for x in self.services.values()]
            await asyncio.wait(tasks)

    @AsyncMutuallyExclusive()
    @OnlyStatesOrRaise([ManagerState.RUNNING])
    async def shutdown(self):
        self.logger.info("Manager is starting to shutdown")
        await self._stop_or_shutdown_all(shutdown=True)
        self.set_state(ManagerState.SHUTDOWN)
        await self.wait()
        self.logger.info("Manager shutdown")

    @AsyncMutuallyExclusive()
    @OnlyStatesOrRaise([ManagerState.RUNNING])
    async def add_service(self, service: Service):
        if service.name in self.services:
            return
        self.logger.info("Adding service: %s to manager" % service.name)
        self.services[service.name] = service
        if service.autostart:
            await service.start()
        self.logger.info("Service: %s added to manager" % service.name)

    @AsyncMutuallyExclusive()
    @OnlyStatesOrRaise([ManagerState.RUNNING])
    async def shutdown_and_remove_service(self, service_name: str):
        if service_name not in self.services:
            return
        await self.services[service_name].shutdown()
        self.services.pop(service_name)

    async def wait(self):
        while self.state != ManagerState.SHUTDOWN:
            await self.wait_for_state_change(1.0)

    @OnlyStates([ManagerState.RUNNING, ManagerState.STOPPING])
    def kill(self, signal: int):
        for service in self.services.values():
            service.kill(signal)

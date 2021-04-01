from typing import Optional, List, cast
import mflog
import asyncio
import signal
import os
import sys
import daemonocle
from pydantic import BaseModel  # pylint: disable=E0611
from pydantic.dataclasses import dataclass
from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import uvicorn
from mfutil.net import ping_tcp_port
from alwaysup.manager import Manager
from alwaysup.cmd import Cmd
from alwaysup.service import Service
from alwaysup.options import Options
from alwaysup.utils import log_exceptions

dir_path = os.path.dirname(os.path.realpath(__file__))
app = FastAPI()
app.mount(
    "/static", StaticFiles(directory=os.path.join(dir_path, "static")), name="static"
)
__daemon: Optional["Daemon"] = None
templates = Jinja2Templates(directory=os.path.join(dir_path, "templates"))


def get_instance():
    if __daemon is None:
        raise Exception("daemon global instance is not set, use set_instance() before")
    return __daemon


def set_instance(i: "Daemon"):
    global __daemon
    __daemon = i


@app.on_event("startup")
async def startup_event():
    daemon = get_instance()
    daemon.start_manager_as_a_task()


@app.on_event("shutdown")
async def shutdown_event():
    daemon = get_instance()
    await daemon.shutdown_manager()


@app.get("/")
async def home(request: Request):
    manager = get_instance().manager
    return templates.TemplateResponse(
        "home.html", {"request": request, "manager": manager.as_dict()}
    )


@app.get("/__content")
async def content(request: Request):
    manager = get_instance().manager
    return templates.TemplateResponse(
        "__content.html", {"request": request, "manager": manager.as_dict()}
    )


@app.get("/manager")
async def get_manager():
    manager = get_instance().manager
    return manager.as_dict()


@app.post("/manager/shutdown")
async def manager_shutdown():
    manager = get_instance().manager
    await manager.shutdown()
    os.kill(os.getpid(), 15)


@app.post("/manager/stop_all")
async def stop_all_services():
    manager = get_instance().manager
    await manager.stop_all()


@app.get("/services")
async def get_services():
    manager = get_instance().manager
    return [x.as_dict() for x in manager.services.values()]


@app.get("/services/{service_name}")
async def get_service(service_name: str):
    manager = get_instance().manager
    if service_name not in manager.services:
        raise HTTPException(status_code=404, detail="service not found")
    return manager.services[service_name].as_dict()


@app.post("/services/{service_name}/stop")
async def stop_service(service_name: str):
    manager = get_instance().manager
    if service_name not in manager.services:
        raise HTTPException(status_code=404, detail="service not found")
    await manager.services[service_name].stop()


@app.post("/services/{service_name}/start")
async def start_service(service_name: str):
    manager = get_instance().manager
    if service_name not in manager.services:
        raise HTTPException(status_code=404, detail="service not found")
    await manager.services[service_name].start()


@app.post("/services/{service_name}/slots/{slot_number}/sigkill")
async def kill_slot(service_name: str, slot_number: int):
    manager = get_instance().manager
    if service_name not in manager.services:
        raise HTTPException(status_code=404, detail="service not found")
    if slot_number not in manager.services[service_name].slots:
        raise HTTPException(status_code=404, detail="slot not found")
    slot = manager.services[service_name].slots[slot_number]
    slot.kill(9)


class ScaleBody(BaseModel):
    workers: int


@dataclass(frozen=True)
class ServiceBody(Options):
    name: Optional[str] = None
    workers: int = 1
    program: Optional[str] = None
    args: Optional[List[str]] = None


@app.post("/services/add", status_code=201)
async def add_service(service_body: ServiceBody = Body(...)):
    if service_body.name is None:
        raise HTTPException(status_code=400, detail="missing name property in the body")
    if service_body.program is None:
        raise HTTPException(
            status_code=400, detail="missing program property in the body"
        )
    manager = get_instance().manager
    if service_body.name in manager.services:
        raise HTTPException(status_code=409, detail="service already exist")
    options: Options = cast(Options, service_body)
    cmd = Cmd(
        service_body.program,
        service_body.args if service_body.args is not None else [],
        options,
    )
    service = Service(service_body.name, service_body.workers, cmd, options)
    await manager.add_service(service)
    return {"name": service_body.name}


@app.post("/services/{service_name}/scale")
async def scale_service(service_name: str, scale_body: ScaleBody = Body(...)):
    manager = get_instance().manager
    if service_name not in manager.services:
        raise HTTPException(status_code=404, detail="service not found")
    await manager.services[service_name].set_slot_number(scale_body.workers)


@app.post("/services/{service_name}/scaleup")
async def scale_service_up(service_name: str):
    manager = get_instance().manager
    if service_name not in manager.services:
        raise HTTPException(status_code=404, detail="service not found")
    service = manager.services[service_name]
    await service.set_slot_number(service.slot_number + 1)


@app.post("/services/{service_name}/scaledown")
async def scale_service_down(service_name: str):
    manager = get_instance().manager
    if service_name not in manager.services:
        raise HTTPException(status_code=404, detail="service not found")
    service = manager.services[service_name]
    await service.set_slot_number(max(service.slot_number - 1, 1))


@app.delete("/services/{service_name}")
async def delete_service(service_name: str):
    manager = get_instance().manager
    if service_name not in manager.services:
        raise HTTPException(status_code=404, detail="service not found")
    await manager.shutdown_and_remove_service(service_name)


@app.post("/services/{service_name}/slots/{slot_number}/stop")
async def stop_slot(service_name: str, slot_number: int):
    manager = get_instance().manager
    if service_name not in manager.services:
        raise HTTPException(status_code=404, detail="service not found")
    service = manager.services[service_name]
    if slot_number not in service.slots:
        raise HTTPException(status_code=404, detail="slot not found")
    await service.slots[slot_number].stop()


@app.post("/services/{service_name}/slots/{slot_number}/start")
async def start_slot(service_name: str, slot_number: int):
    manager = get_instance().manager
    if service_name not in manager.services:
        raise HTTPException(status_code=404, detail="service not found")
    service = manager.services[service_name]
    if slot_number not in service.slots:
        raise HTTPException(status_code=404, detail="slot not found")
    await service.slots[slot_number].start()


class Daemon:
    def __init__(
        self,
        services_to_add: List[Service] = [],
        port: int = 0,
        bind_host: str = "127.0.0.1",
        log_configure_logger: bool = True,
        log_minimal_level: str = "INFO",
        log_fancy_output: Optional[bool] = None,
    ):
        self.manager: Manager = Manager()
        self.__wait_task = None
        self.services_to_add = services_to_add
        self.__shutdown_task = None
        self.port = port
        self.bind_host = bind_host
        self.log_minimal_level = log_minimal_level
        self.log_fancy_output = log_fancy_output
        self.log_configure_logger = log_configure_logger
        if self.log_configure_logger:
            mflog.set_config(
                fancy_output=self.log_fancy_output, minimal_level=self.log_minimal_level
            )
        self.logger = mflog.get_logger("alwaysup.daemon")

    @property
    def api(self):
        return self.port > 0

    def start_manager_as_a_task(self):
        self.__wait_task = asyncio.create_task(log_exceptions(self.__start_manager()))

    async def __start_manager(self):
        for service in self.services_to_add:
            await self.manager.add_service(service)
        await self.manager.wait()

    async def shutdown_manager(self):
        await self.manager.shutdown()
        if self.__wait_task:
            await self.__wait_task
        if self.__shutdown_task:
            await self.__shutdown_task

    def _sig_handler(self, *args, **kwargs):
        if self.__shutdown_task is not None:
            self.kill(9)
            return
        self.__shutdown_task = asyncio.create_task(
            log_exceptions(self.manager.shutdown())
        )

    def _run(self):
        if self.api:
            if ping_tcp_port("127.0.0.1", self.port):
                self.logger.critical(
                    f"the configured TCP port: {self.port} is already used => exit"
                )
                sys.exit(1)
            uvicorn.run(
                app="alwaysup.daemon:app",
                debug=False,
                workers=1,
                reload=False,
                port=self.port,
                host=self.bind_host,
                loop="auto",
                ws="auto",
                lifespan="auto",
                interface="auto",
                factory=False,
                access_log=False,
            )
        else:
            signal.signal(signal.SIGINT, self._sig_handler)
            signal.signal(signal.SIGTERM, self._sig_handler)
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self.__start_manager())
            if self.__shutdown_task is not None:
                loop.run_until_complete(self.__shutdown_task)
            loop.close()

    def run(self, daemonize=False, daemonize_stdout=None, daemonize_stderr=None):
        def is_null(val):
            if val is None:
                return True
            return val.lower() in ("/dev/null", "null")

        if not daemonize:
            return self._run()
        d = daemonocle.Daemon(
            name="alwaysup/run_forever",
            worker=self._run,
            detach=True,
            stdout_file=daemonize_stdout if is_null(daemonize_stdout) else None,
            stderr_file=daemonize_stderr if is_null(daemonize_stderr) else None,
        )
        d.do_action("start")

    def kill(self, signal):
        self.manager.kill(signal)

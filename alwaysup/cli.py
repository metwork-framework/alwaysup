import typer
import json
import requests
from alwaysup.daemon import Daemon, set_instance
from alwaysup.service import Service
from alwaysup.cmd import Cmd
from alwaysup.options import Options

app = typer.Typer()


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def run_forever(
    ctx: typer.Context,
    workers: int = 1,
    bind_host: str = "127.0.0.1",
    port: int = 0,
    daemonize: bool = False,
    daemonize_stdout: str = "/dev/null",
    daemonize_stderr: str = "/dev/null",
):
    if len(ctx.args) == 0:
        raise Exception("you have to provide a program to execute")
    options = Options(stdout="PIPE", stderr="PIPE")  # type: ignore
    cmd = Cmd(ctx.args[0], ctx.args[1:], options)
    service = Service("forever_cmd", workers, cmd)
    daemon = Daemon(services_to_add=[service], bind_host=bind_host, port=port)
    set_instance(daemon)
    daemon.run(
        daemonize=daemonize,
        daemonize_stderr=daemonize_stderr,
        daemonize_stdout=daemonize_stdout,
    )


@app.command()
def start_daemon(
    bind_host: str = "127.0.0.1",
    port: int = 8000,
    foreground: bool = False,
    daemonize_stdout: str = "NULL",
    daemonize_stderr: str = "NULL",
):
    daemon = Daemon(bind_host=bind_host, port=port)
    set_instance(daemon)
    daemon.run(
        daemonize=not foreground,
        daemonize_stderr=daemonize_stderr,
        daemonize_stdout=daemonize_stdout,
    )


@app.command()
def shutdown_daemon(host: str = "127.0.0.1", port: int = 8000, smart=True):
    res = requests.post(f"http://{host}:{port}/manager/shutdown")
    result = res.json()
    print(result)


@app.command()
def status(host: str = "127.0.0.1", port: int = 8000):
    res = requests.get(f"http://{host}:{port}/manager")
    result = res.json()
    print(
        f"Manager state: {result['state']} "
        f"(since {round(result['state_since'])} seconds)"
    )
    print()
    print("Services:")
    for service in result["services"].values():
        print(
            f"- service: {service['name']} (state: {service['state']} "
            f"since {round(service['state_since'])} seconds)"
        )
        for n, slot in service["slots"].items():
            print(
                f"    - slot: {n}, state: {slot['state']} "
                f"(since {round(slot['state_since'])} seconds)"
            )
            if slot["pid"] is not None:
                print(f"        - pid: {slot['pid']}, cmd_line: {slot['cmd_line']}")


@app.command()
def scale_service(
    service_name: str, workers: int, host: str = "127.0.0.1", port: int = 8000
):
    body = {"workers": workers}
    res = requests.post(
        f"http://{host}:{port}/services/{service_name}/scale", data=json.dumps(body)
    )
    print(res)
    print(res.text)


if __name__ == "__main__":
    app()

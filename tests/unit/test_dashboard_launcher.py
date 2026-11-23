import json
import os
import secrets
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "start-mouse-dashboard.sh"
FILES = ["-f", "deploy/compose.yaml", "-f", "deploy/compose.host.yaml"]
RECORDED = [
    "DOCKER_HOST",
    "DOCKER_BUILDKIT",
    "ETT_TILED_URL",
    "ETT_TILED_KEY_FILE",
    "ETT_QUEUE_KEY_FILE",
    "ETT_QUEUES",
    "ETT_CATALOG_ROOTS",
    "ETT_ADAPTER_USER",
    "ETT_HTTP_PORT",
    "ETT_GRAFANA_PORT",
    "ETT_ADAPTER_PORT",
    "ETT_PUBLIC_URL",
    "GF_ADMIN_PASSWORD",
    "COMPOSE_FILE",
    "COMPOSE_PROFILES",
    "COMPOSE_ENV_FILES",
    "COMPOSE_PROJECT_NAME",
]
RECORDER = f"""#!{sys.executable}
import json, os, sys
names = {RECORDED!r}
call = {{"program": os.path.basename(sys.argv[0]), "args": sys.argv[1:], "cwd": os.getcwd(),
        "env": {{name: os.environ.get(name) for name in names}}}}
with open(os.environ["DASHBOARD_TEST_CALLS"], "a") as stream:
    stream.write(json.dumps(call) + "\\n")
"""


def write_secret(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    path.chmod(mode)


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ett = home / "code/event_timeline_tiled"
    (ett / "deploy").mkdir(parents=True)
    (ett / "deploy/compose.host.yaml").touch()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for fake in (home / ".local/bin/docker-compose", bin_dir / "python3"):
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_text(RECORDER)
        fake.chmod(0o755)

    runtime = tmp_path / "run"
    (runtime / "podman").mkdir(parents=True)
    # Bind by a relative name: macOS limits socket paths to 104 bytes.
    monkeypatch.chdir(runtime / "podman")
    podman = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    podman.bind("podman.sock")
    monkeypatch.chdir(tmp_path)

    values = {
        "tiled": secrets.token_hex(16),
        "queue": secrets.token_hex(16),
        "admin": secrets.token_hex(16),
        "viewer": secrets.token_hex(16),
    }
    paths = {
        "tiled": home / ".tiled_api.key",
        "queue": home / ".config/mouse-http-server/dashboard.key",
        "admin": home / ".config/mouse-dashboard/grafana-admin.password",
        "viewer": home / ".config/mouse-dashboard/grafana-viewer.password",
    }
    for name, path in paths.items():
        write_secret(path, values[name])
    calls_file = tmp_path / "calls"
    env = {
        "HOME": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{os.defpath}",
        "XDG_RUNTIME_DIR": str(runtime),
        "DASHBOARD_TEST_CALLS": str(calls_file),
    }

    def run(*args, inherited=None):
        result = subprocess.run(
            [str(LAUNCHER), *args],
            env={**env, **(inherited or {})},
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        for value in values.values():
            assert value not in result.stdout + result.stderr
        calls = [json.loads(line) for line in calls_file.read_text().splitlines()] if calls_file.exists() else []
        return result, calls

    run.home, run.ett, run.runtime, run.paths, run.values = home, ett, runtime, paths, values
    yield run
    podman.close()


def test_start_runs_the_host_stack_on_loopback(launcher):
    result, calls = launcher(inherited={"COMPOSE_PROFILES": "demo", "COMPOSE_FILE": "x.yaml"})
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1
    call = calls[0]
    assert call["program"] == "docker-compose"
    assert call["args"] == [*FILES, "up", "--no-build", "--pull", "never"]
    assert call["cwd"] == str(launcher.ett.resolve())
    assert call["env"] == {
        "DOCKER_HOST": f"unix://{launcher.runtime}/podman/podman.sock",
        "DOCKER_BUILDKIT": None,
        "ETT_TILED_URL": "https://tiled.scicat65.ddnss.de",
        "ETT_TILED_KEY_FILE": str(launcher.paths["tiled"]),
        "ETT_QUEUE_KEY_FILE": str(launcher.paths["queue"]),
        "ETT_QUEUES": "MOUSE=http:http://127.0.0.1:60610",
        "ETT_CATALOG_ROOTS": "",
        "ETT_ADAPTER_USER": "0:0",
        "ETT_HTTP_PORT": "8080",
        "ETT_GRAFANA_PORT": "3000",
        "ETT_ADAPTER_PORT": "8000",
        "ETT_PUBLIC_URL": "http://127.0.0.1:8080/",
        "GF_ADMIN_PASSWORD": launcher.values["admin"],
        "COMPOSE_FILE": None,
        "COMPOSE_PROFILES": None,
        "COMPOSE_ENV_FILES": None,
        "COMPOSE_PROJECT_NAME": None,
    }


def test_install_builds_and_pulls_without_starting(launcher):
    result, calls = launcher("--install")
    assert result.returncode == 0, result.stderr
    assert [call["args"] for call in calls] == [[*FILES, "build"], [*FILES, "pull", "proxy"]]
    assert {call["env"]["DOCKER_BUILDKIT"] for call in calls} == {"0"}


def test_viewer_uses_password_files(launcher):
    result, calls = launcher("--viewer")
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1
    assert calls[0]["program"] == "python3"
    assert calls[0]["args"] == [
        "deploy/grafana_viewer.py",
        "--url",
        "http://127.0.0.1:3000",
        "--login",
        "mouse",
        "--password-file",
        str(launcher.paths["viewer"]),
        "--admin-password-file",
        str(launcher.paths["admin"]),
    ]


def test_compose_passes_arguments_through(launcher):
    result, calls = launcher("--compose", "logs", "--tail", "20", "adapter")
    assert result.returncode == 0, result.stderr
    assert calls[0]["args"] == [*FILES, "logs", "--tail", "20", "adapter"]


def test_viewer_password_is_needed_only_for_viewer(launcher):
    launcher.paths["viewer"].unlink()
    result, calls = launcher()
    assert result.returncode == 0, result.stderr
    result, calls = launcher("--viewer")
    assert result.returncode != 0
    assert "grafana-viewer.password" in result.stderr
    assert len(calls) == 1


@pytest.mark.parametrize("name", ["tiled", "queue", "admin"])
@pytest.mark.parametrize(
    "change, reason",
    [
        ("missing", "missing, unreadable or empty"),
        ("empty", "missing, unreadable or empty"),
        (0o644, "readable by group or others"),
        (0o640, "readable by group or others"),
        (0o604, "readable by group or others"),
        (0o620, "readable by group or others"),
    ],
)
def test_secret_refusals(launcher, name, change, reason):
    path = launcher.paths[name]
    if change == "missing":
        path.unlink()
    elif change == "empty":
        write_secret(path, "")
    else:
        path.chmod(change)
    result, calls = launcher()
    assert result.returncode != 0
    assert calls == []
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert reason in result.stderr and str(path) in result.stderr


@pytest.mark.parametrize(
    "setup, args, reason",
    [
        (lambda r: (r.home / ".local/bin/docker-compose").unlink(), (), "no docker-compose"),
        (lambda r: (r.runtime / "podman/podman.sock").unlink(), (), "Podman's socket is not running"),
        (lambda r: (r.ett / "deploy/compose.host.yaml").unlink(), (), "no event-timeline-tiled checkout"),
        (lambda r: (r.ett / "deploy/.env").touch(), (), "deploy/.env"),
        (lambda r: None, ("--demo",), "unknown option: --demo"),
        (lambda r: None, ("--install", "now"), "unexpected arguments"),
    ],
)
def test_other_refusals(launcher, setup, args, reason):
    setup(launcher)
    result, calls = launcher(*args)
    assert result.returncode != 0
    assert calls == []
    assert len(result.stderr.splitlines()) == 1
    assert reason in result.stderr

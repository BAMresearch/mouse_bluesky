import os
import secrets
import shlex
import socket
import subprocess
from pathlib import Path

import pytest
import yaml
import zmq
from bluesky_httpserver.app import build_app
from bluesky_httpserver.config import construct_build_app_kwargs, parse_configs
from bluesky_httpserver.database.core import initialize_database
from bluesky_httpserver.settings import get_sessionmaker, get_settings
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from uvicorn import Config

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "qserver_profile/http_server/config.yml"
READ_SCOPES = {"read:status", "read:queue"}


@pytest.fixture
def parsed_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUSE_HTTP_READER_PASSWORD", secrets.token_urlsafe(32))
    monkeypatch.setenv("MOUSE_HTTP_DATABASE_URI", f"sqlite:///{tmp_path / 'http.sqlite'}")
    monkeypatch.setenv("MOUSE_HTTP_SSL_CERTFILE", "")
    monkeypatch.setenv("MOUSE_HTTP_SSL_KEYFILE", "")
    return parse_configs(CONFIG)


def test_repository_config(parsed_config):
    auth = parsed_config["authentication"]
    assert auth["allow_anonymous_access"] is False
    assert "single_user_api_key" not in auth
    assert auth["providers"] == [
        {
            "provider": "mouse",
            "authenticator": "bluesky_httpserver.authenticators:DictionaryAuthenticator",
            "args": {"users_to_passwords": {"timeline-reader": os.environ["MOUSE_HTTP_READER_PASSWORD"]}},
        }
    ]
    access = parsed_config["api_access"]
    assert access["policy"] == "bluesky_httpserver.authorization:DictionaryAPIAccessControl"
    assert access["args"] == {
        "roles": {
            "timeline_reader": {"scopes_set": ["read:status", "read:queue", "user:apikeys"]},
            "unauthenticated_public": {"scopes_set": []},
            "unauthenticated_single_user": {"scopes_set": []},
        },
        "users": {"timeline-reader": {"roles": ["timeline_reader"]}},
    }
    assert parsed_config["qserver_zmq_configuration"] == {
        "control_address": "tcp://127.0.0.1:60615",
        "info_address": "tcp://127.0.0.1:60625",
    }
    raw = yaml.safe_load(CONFIG.read_text())
    assert raw["authentication"]["providers"][0]["args"]["users_to_passwords"] == {
        "timeline-reader": "${MOUSE_HTTP_READER_PASSWORD}"
    }
    assert raw["database"]["uri"] == "${MOUSE_HTTP_DATABASE_URI}"
    assert raw["uvicorn"] == {
        "ssl_certfile": "${MOUSE_HTTP_SSL_CERTFILE}",
        "ssl_keyfile": "${MOUSE_HTTP_SSL_KEYFILE}",
    }


def test_loopback_config_accepts_empty_tls_paths(parsed_config):
    # Config.load builds the SSL context without starting a server or contacting ZMQ.
    config = Config("unused:app", host="127.0.0.1", **parsed_config["uvicorn"])
    assert config.is_ssl is False
    config.app = lambda scope, receive, send: None
    config.load()
    assert config.ssl is None


@pytest.fixture
def client(parsed_config, monkeypatch):
    def forbid_zmq(*args, **kwargs):
        pytest.fail("Authentication tests must never connect to an RE Manager")

    monkeypatch.setattr(zmq.Socket, "connect", forbid_zmq)
    # Reserve two unused loopback ports, then release them. Never use live defaults.
    with socket.socket() as control, socket.socket() as info:
        control.bind(("127.0.0.1", 0))
        info.bind(("127.0.0.1", 0))
        ports = [control.getsockname()[1], info.getsockname()[1]]
    assert not {60615, 60625}.intersection(ports)
    parsed_config["qserver_zmq_configuration"] = dict(
        zip(("control_address", "info_address"), (f"tcp://127.0.0.1:{port}" for port in ports), strict=True)
    )
    get_settings.cache_clear()
    app = build_app(**construct_build_app_kwargs(parsed_config, source_filepath=str(CONFIG)))
    settings = app.dependency_overrides[get_settings]()
    engine = create_engine(settings.database_uri)
    initialize_database(engine)
    sessionmaker = get_sessionmaker(settings.database_settings)
    # Deliberately do not enter TestClient's context: startup opens ZMQ connections.
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        sessionmaker.remove()
        sessionmaker.bind.dispose()
        engine.dispose()
        get_sessionmaker.cache_clear()
        get_settings.cache_clear()


def login(client):
    response = client.post(
        "/api/auth/provider/mouse/token",
        data={"username": "timeline-reader", "password": os.environ["MOUSE_HTTP_READER_PASSWORD"]},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_reader_key(client, token):
    response = client.post(
        "/api/auth/apikey",
        headers=token,
        json={"scopes": sorted(READ_SCOPES), "expires_in": None, "note": "event-timeline-tiled"},
    )
    assert response.status_code == 200
    assert set(response.json()["scopes"]) == READ_SCOPES
    assert response.json()["expiration_time"] is None
    return {"Authorization": f"ApiKey {response.json()['secret']}"}


def test_login_and_key_lifecycle(client):
    token = login(client)
    key = create_reader_key(client, token)
    response = client.get("/api/auth/scopes", headers=key)
    assert response.status_code == 200
    assert set(response.json()["scopes"]) == READ_SCOPES
    response = client.get("/api/auth/apikey", headers=key)
    assert response.status_code == 200
    first_eight = response.json()["first_eight"]
    response = client.delete("/api/auth/apikey", headers=token, params={"first_eight": first_eight})
    assert response.status_code == 200
    for route in ("/api/auth/scopes", "/api/status", "/api/queue/get"):
        assert client.get(route, headers=key).status_code == 401


@pytest.mark.parametrize("unknown_user", [False, True])
def test_bad_login(client, unknown_user):
    response = client.post(
        "/api/auth/provider/mouse/token",
        data={
            "username": "unknown" if unknown_user else "timeline-reader",
            "password": os.environ["MOUSE_HTTP_READER_PASSWORD"] if unknown_user else secrets.token_urlsafe(32),
        },
    )
    assert response.status_code == 401


def test_reader_cannot_create_write_key(client):
    response = client.post(
        "/api/auth/apikey", headers=login(client), json={"scopes": ["write:queue:edit"], "expires_in": None}
    )
    assert response.status_code == 400
    assert "must be a subset" in response.json()["detail"]
    assert "secret" not in response.json()


@pytest.mark.parametrize(
    "method, route, body",
    [
        ("POST", "/api/queue/item/add", {"item": {"item_type": "plan", "name": "count"}}),
        ("POST", "/api/queue/start", {}),
        ("POST", "/api/environment/open", {}),
        ("GET", "/api/history/get", None),
        ("POST", "/api/auth/apikey", {"scopes": sorted(READ_SCOPES), "expires_in": None}),
    ],
)
def test_dashboard_key_cannot_write_or_read_history(client, method, route, body):
    key = create_reader_key(client, login(client))
    response = client.request(method, route, headers=key, **({"json": body} if body is not None else {}))
    assert response.status_code in (401, 403)
    assert "Not enough permissions" in response.json()["detail"]


@pytest.mark.parametrize("route", ["/api/status", "/api/queue/get"])
@pytest.mark.parametrize("wrong_key", [False, True])
def test_reads_require_valid_key(client, route, wrong_key):
    headers = {"Authorization": f"ApiKey {secrets.token_hex(32)}"} if wrong_key else {}
    assert client.get(route, headers=headers).status_code == 401


@pytest.fixture
def launcher(tmp_path):
    args_file = tmp_path / "args"
    tls_env_file = tmp_path / "tls-env"
    fake = tmp_path / "start-bluesky-httpserver"
    fake.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$HTTP_TEST_ARGS"\n'
        'printf \'%s\\n\' "${MOUSE_HTTP_SSL_CERTFILE-unset}" "${MOUSE_HTTP_SSL_KEYFILE-unset}" > "$HTTP_TEST_TLS"\n'
    )
    fake.chmod(0o755)
    password = secrets.token_urlsafe(32)
    values = {
        "MOUSE_HTTP_READER_PASSWORD": password,
        "MOUSE_HTTP_DATABASE_URI": f"sqlite:///{tmp_path / 'http.sqlite'}",
    }
    env_file = tmp_path / "env"
    env = {
        "HOME": str(tmp_path),
        "PATH": f"{tmp_path}{os.pathsep}{os.defpath}",
        "HTTP_TEST_ARGS": str(args_file),
        "HTTP_TEST_TLS": str(tls_env_file),
        "MOUSE_HTTP_ENV_FILE": str(env_file),
    }

    def run(*, changes=None, mode=0o600, missing=False, inherited=None):
        content = {**values, **(changes or {})}
        env_file.write_text(
            "".join(f"{key}={shlex.quote(value)}\n" for key, value in content.items() if value is not None)
        )
        env_file.chmod(mode)
        if missing:
            env_file.unlink()
        result = subprocess.run(
            [str(ROOT / "start-mouse-http-server.sh")],
            env={**env, **(inherited or {})},
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert password not in result.stdout + result.stderr
        return result, args_file, tls_env_file

    return run


def test_launcher_defaults(launcher):
    result, args_file, tls_env_file = launcher()
    assert result.returncode == 0, result.stderr
    assert args_file.read_text().splitlines() == [
        "--config_path",
        str(CONFIG),
        "--host",
        "127.0.0.1",
        "--port",
        "60610",
    ]
    assert tls_env_file.read_text() == "\n\n"


@pytest.mark.parametrize(
    "options, reason",
    [
        ({"missing": True}, "environment file is missing"),
        ({"mode": 0o644}, "readable by group or others"),
        ({"mode": 0o640}, "readable by group or others"),
        ({"mode": 0o604}, "readable by group or others"),
        ({"changes": {"MOUSE_HTTP_READER_PASSWORD": ""}}, "MOUSE_HTTP_READER_PASSWORD"),
        ({"changes": {"MOUSE_HTTP_READER_PASSWORD": None}}, "MOUSE_HTTP_READER_PASSWORD"),
        ({"changes": {"MOUSE_HTTP_DATABASE_URI": None}}, "MOUSE_HTTP_DATABASE_URI"),
        ({"changes": {"MOUSE_HTTP_DATABASE_URI": ""}}, "MOUSE_HTTP_DATABASE_URI"),
        ({"changes": {"QSERVER_HTTP_SERVER_SINGLE_USER_API_KEY": ""}}, "QSERVER_HTTP_SERVER_SINGLE_USER_API_KEY"),
        ({"changes": {"QSERVER_HTTP_SERVER_ALLOW_ANONYMOUS_ACCESS": ""}}, "QSERVER_HTTP_SERVER_ALLOW_ANONYMOUS_ACCESS"),
        ({"changes": {"MOUSE_HTTP_HOST": "0.0.0.0"}}, "TLS requires readable"),
        (
            {
                "changes": {
                    "MOUSE_HTTP_HOST": "192.0.2.1",
                    "MOUSE_HTTP_SSL_CERTFILE": "/nonexistent",
                    "MOUSE_HTTP_SSL_KEYFILE": "/nonexistent",
                }
            },
            "TLS requires readable",
        ),
    ],
)
def test_launcher_refusals(launcher, options, reason):
    result, args_file, _ = launcher(**options)
    assert result.returncode != 0
    assert not args_file.exists()
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert reason in result.stderr


@pytest.mark.parametrize(
    "name", ["QSERVER_HTTP_SERVER_SINGLE_USER_API_KEY", "QSERVER_HTTP_SERVER_ALLOW_ANONYMOUS_ACCESS"]
)
def test_launcher_rejects_inherited_auth_overrides(launcher, name):
    secret = secrets.token_hex(32)
    result, args_file, _ = launcher(inherited={name: secret})
    assert result.returncode != 0
    assert not args_file.exists()
    assert name in result.stderr
    assert secret not in result.stdout + result.stderr


def test_launcher_network_tls(launcher, tmp_path):
    certificate, key = tmp_path / "certificate", tmp_path / "key"
    certificate.touch()
    key.touch()
    result, args_file, _ = launcher(
        changes={
            "MOUSE_HTTP_HOST": "192.0.2.1",
            "MOUSE_HTTP_PORT": "9443",
            "MOUSE_HTTP_SSL_CERTFILE": str(certificate),
            "MOUSE_HTTP_SSL_KEYFILE": str(key),
        }
    )
    assert result.returncode == 0, result.stderr
    assert args_file.read_text().splitlines() == ["--config_path", str(CONFIG), "--host", "192.0.2.1", "--port", "9443"]

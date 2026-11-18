import json

import numpy as np
import pytest

from mouse_bluesky import cli
from mouse_bluesky.tiled_replay import REPLAYED_DIRNAME, backup_files, replay_backups

UID = "d4aa77c7-ebbb-47fc-bb52-108054c7cacd"


class FakeStream:
    def __init__(self, rows=0):
        self.rows = rows

    def read(self):
        return {"time": np.zeros(self.rows)}


class FakeRun:
    def __init__(self, start):
        self.metadata = {"start": start, "stop": None}
        self.streams = {}

    def __contains__(self, key):
        return key in self.streams

    def __getitem__(self, key):
        return self.streams[key]


class FakeClient:
    def __init__(self):
        self.runs = {}
        self.deleted = []

    def __contains__(self, uid):
        return uid in self.runs

    def __getitem__(self, uid):
        return self.runs[uid]

    def delete_contents(self, uid, *, recursive, external_only):
        self.deleted.append((uid, recursive, external_only))
        del self.runs[uid]


class FakeWriter:
    """Builds runs in a FakeClient from documents, roughly as TiledWriter does in Tiled."""

    def __init__(self, client, calls, fail_on=None):
        self.client, self.calls, self.fail_on = client, calls, fail_on
        self.descriptors = {}

    def __call__(self, name, doc):
        self.calls.append((name, doc))
        if name == self.fail_on:
            raise RuntimeError("server said no")
        if name == "start":
            self.client.runs[doc["uid"]] = self.run = FakeRun(doc)
        elif name == "descriptor":
            self.descriptors[doc["uid"]] = doc["name"]
            self.run.streams.setdefault(doc["name"], FakeStream())
        elif name == "event_page":
            self.run.streams[self.descriptors[doc["descriptor"]]].rows += len(doc["seq_num"])
        elif name == "stop":
            self.run.metadata["stop"] = doc


def run_documents(uid=UID, primary=3, baseline=2, stop=True):
    docs = [("start", {"uid": uid, "plan_name": "count"})]
    docs += [("descriptor", {"uid": "d-primary", "name": "primary"})]
    docs += [("descriptor", {"uid": "d-baseline", "name": "baseline"})]
    docs += [("event_page", {"descriptor": "d-primary", "seq_num": [i + 1]}) for i in range(primary)]
    docs += [("event_page", {"descriptor": "d-baseline", "seq_num": [i + 1]}) for i in range(baseline)]
    if stop:
        docs.append(("stop", {"exit_status": "success", "num_events": {"primary": primary, "baseline": baseline}}))
    return docs


def write_backup(path, docs):
    path.write_text("".join(json.dumps({"name": name, "doc": doc}) + "\n" for name, doc in docs))
    return path


def preload(client, docs):
    writer = FakeWriter(client, [])
    for name, doc in docs:
        writer(name, doc)


@pytest.fixture
def rig(tmp_path):
    client, calls, lines = FakeClient(), [], []

    def replay(*paths, replace_partial=False, include_unfinished=False, fail_on=None):
        return replay_backups(
            paths or [tmp_path],
            client,
            replace_partial=replace_partial,
            include_unfinished=include_unfinished,
            writer_factory=lambda c: FakeWriter(c, calls, fail_on),
            log=lines.append,
        )

    return client, calls, lines, replay


def test_directory_expands_to_jsonl_files_only(tmp_path):
    (tmp_path / REPLAYED_DIRNAME).mkdir()
    (tmp_path / REPLAYED_DIRNAME / "old.jsonl").write_text("")
    (tmp_path / "notes.txt").write_text("")
    b, a = tmp_path / "b.jsonl", tmp_path / "a.jsonl"
    b.write_text("")
    a.write_text("")
    single = tmp_path / "elsewhere.json"

    assert backup_files([tmp_path, single]) == [a, b, single]


def test_missing_run_is_written_and_file_moved(tmp_path, rig):
    client, calls, lines, replay = rig
    docs = run_documents()
    path = write_backup(tmp_path / "d4aa77c7.jsonl", docs)

    assert replay() == 0

    assert calls == [(name, doc) for name, doc in docs]
    assert client[UID].metadata["stop"]["exit_status"] == "success"
    assert not path.exists()
    assert (tmp_path / REPLAYED_DIRNAME / path.name).exists()
    assert lines == [f"d4aa77c7.jsonl: replayed {len(docs)} documents as run {UID}"]


def test_complete_run_is_skipped_and_moved(tmp_path, rig):
    client, calls, lines, replay = rig
    docs = run_documents()
    preload(client, docs)
    path = write_backup(tmp_path / "d4aa77c7.jsonl", docs)

    assert replay() == 0

    assert calls == []
    assert client.deleted == []
    assert (tmp_path / REPLAYED_DIRNAME / path.name).exists()
    assert "already complete" in lines[0]


@pytest.mark.parametrize(
    "in_tiled",
    [
        pytest.param(run_documents(stop=False), id="no stop in Tiled"),
        pytest.param(run_documents(primary=1), id="stop in Tiled, events missing"),
        pytest.param(run_documents(baseline=0)[:-1] + [run_documents()[-1]], id="stream missing"),
    ],
)
def test_partial_run_is_left_alone_without_flag(tmp_path, rig, in_tiled):
    client, calls, lines, replay = rig
    preload(client, in_tiled)
    path = write_backup(tmp_path / "d4aa77c7.jsonl", run_documents())

    assert replay() == 1

    assert calls == []
    assert client.deleted == []
    assert path.exists()
    assert "partly in Tiled" in lines[0] and "--replace-partial" in lines[0]


def test_partial_run_is_replaced_with_flag(tmp_path, rig):
    client, calls, lines, replay = rig
    preload(client, run_documents(primary=1))
    docs = run_documents()
    path = write_backup(tmp_path / "d4aa77c7.jsonl", docs)

    assert replay(replace_partial=True) == 0

    assert client.deleted == [(UID, True, False)]
    assert calls == [(name, doc) for name, doc in docs]
    assert client[UID]["primary"].rows == 3
    assert not path.exists()
    assert lines[0] == f"d4aa77c7.jsonl: deleted the partial run {UID}"


def test_writer_failure_leaves_file_and_continues(tmp_path, rig):
    client, calls, lines, replay = rig
    first = write_backup(tmp_path / "a.jsonl", run_documents(uid="a-run"))
    second = write_backup(tmp_path / "b.jsonl", run_documents(uid="b-run"))

    assert replay(first, fail_on="descriptor") == 1
    assert first.exists()
    assert "replay failed (RuntimeError: server said no)" in lines[0]

    assert replay(second) == 0
    assert not second.exists()


def test_run_incomplete_after_writing_is_reported(tmp_path, rig):
    client, calls, lines, replay = rig
    path = write_backup(tmp_path / "b.jsonl", run_documents(uid="b-run"))
    original = FakeWriter.__call__

    def lose_events(self, name, doc):
        if name != "event_page":
            original(self, name, doc)

    FakeWriter.__call__ = lose_events
    try:
        assert replay(path) == 1
    finally:
        FakeWriter.__call__ = original
    assert path.exists()
    assert "written but is not complete" in lines[-1]


def test_backup_without_stop_is_left_alone_by_default(tmp_path, rig):
    client, calls, lines, replay = rig
    path = write_backup(tmp_path / "a.jsonl", run_documents(stop=False))

    assert replay() == 1
    assert calls == []
    assert UID not in client
    assert path.exists()
    assert "may still be in progress" in lines[0] and "--include-unfinished" in lines[0]


def test_backup_without_stop_is_replayed_with_flag(tmp_path, rig):
    client, calls, lines, replay = rig
    write_backup(tmp_path / "a.jsonl", run_documents(stop=False))

    assert replay(include_unfinished=True) == 0
    assert UID in client
    assert lines[0].endswith("(the backup has no stop document: the run never finished)")


def test_in_progress_backup_is_not_touched_even_if_run_is_partly_in_tiled(tmp_path, rig):
    client, calls, lines, replay = rig
    preload(client, run_documents(primary=1, stop=False))
    path = write_backup(tmp_path / "a.jsonl", run_documents(stop=False))

    assert replay(replace_partial=True) == 1
    assert client.deleted == []
    assert path.exists()


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("not json\n", id="bad json"),
        pytest.param(json.dumps({"name": "descriptor", "doc": {}}) + "\n", id="no start"),
        pytest.param("", id="empty"),
    ],
)
def test_unreadable_backup_is_left_in_place(tmp_path, rig, content):
    client, calls, lines, replay = rig
    path = tmp_path / "a.jsonl"
    path.write_text(content)

    assert replay() == 1
    assert path.exists()
    assert calls == []
    assert "left in place" in lines[0]


def test_replayed_file_never_overwrites_an_earlier_one(tmp_path, rig):
    client, calls, lines, replay = rig
    (tmp_path / REPLAYED_DIRNAME).mkdir()
    earlier = tmp_path / REPLAYED_DIRNAME / "a.jsonl"
    earlier.write_text("earlier\n")
    write_backup(tmp_path / "a.jsonl", run_documents())

    assert replay() == 0
    assert earlier.read_text() == "earlier\n"
    assert (tmp_path / REPLAYED_DIRNAME / "a.1.jsonl").exists()


def test_no_files_found(tmp_path, rig):
    client, calls, lines, replay = rig
    assert replay() == 0
    assert lines == ["No backup files found."]


# CLI


@pytest.fixture
def fake_from_uri(monkeypatch):
    seen = {}
    client = FakeClient()

    def from_uri(uri, *, api_key):
        seen.update(uri=uri, api_key=api_key)
        return client

    monkeypatch.setattr("tiled.client.from_uri", from_uri)
    monkeypatch.setattr("mouse_bluesky.tiled_replay._default_writer_factory", lambda c: FakeWriter(c, []))
    monkeypatch.delenv("TILED_URI", raising=False)
    return seen, client


def run_cli(argv):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv)
    return exit_info.value.code


def test_cli_replays_and_never_prints_the_key(tmp_path, capsys, fake_from_uri):
    seen, client = fake_from_uri
    key = "0123456789abcdef0123456789abcdef"
    key_file = tmp_path / "key"
    key_file.write_text(key + "\n")
    backups = tmp_path / "backups"
    backups.mkdir()
    write_backup(backups / "d4aa77c7.jsonl", run_documents())

    write_backup(backups / "e0000000.jsonl", run_documents(uid="e-run", stop=False))

    code = run_cli(["tiled-replay", str(backups), "--uri", "http://tiled.invalid", "--api-key-file", str(key_file)])
    assert code == 1
    assert "e-run" not in client

    code = run_cli(
        ["tiled-replay", str(backups), "--uri", "http://tiled.invalid", "--api-key-file", str(key_file)]
        + ["--include-unfinished"]
    )
    assert code == 0
    assert "e-run" in client
    assert seen == {"uri": "http://tiled.invalid", "api_key": key}
    assert UID in client
    assert key not in capsys.readouterr().out


def test_cli_uri_from_environment(tmp_path, monkeypatch, fake_from_uri):
    seen, _ = fake_from_uri
    monkeypatch.setenv("TILED_URI", "http://env.invalid")
    key_file = tmp_path / "key"
    key_file.write_text("k\n")

    assert run_cli(["tiled-replay", str(tmp_path / "none.jsonl"), "--api-key-file", str(key_file)]) == 1
    assert seen["uri"] == "http://env.invalid"


def test_cli_partial_without_flag_exits_one(tmp_path, capsys, fake_from_uri):
    _, client = fake_from_uri
    preload(client, run_documents(stop=False))
    key_file = tmp_path / "key"
    key_file.write_text("k\n")
    write_backup(tmp_path / "a.jsonl", run_documents())

    code = run_cli(
        ["tiled-replay", str(tmp_path / "a.jsonl"), "--uri", "http://x.invalid", "--api-key-file", str(key_file)]
    )

    assert code == 1
    assert "1 backup file(s) need attention" in capsys.readouterr().out


def test_cli_requires_uri(tmp_path, capsys, fake_from_uri):
    assert run_cli(["tiled-replay", str(tmp_path)]) == 2
    assert "--uri or the TILED_URI variable" in capsys.readouterr().err


@pytest.mark.parametrize("content", [None, "  \n"], ids=["missing", "empty"])
def test_cli_key_file_problems_exit_one_without_connecting(tmp_path, capsys, fake_from_uri, content):
    seen, _ = fake_from_uri
    key_file = tmp_path / "key"
    if content is not None:
        key_file.write_text(content)

    code = run_cli(["tiled-replay", str(tmp_path), "--uri", "http://x.invalid", "--api-key-file", str(key_file)])

    assert code == 1
    assert seen == {}
    assert "Tiled API key file" in capsys.readouterr().out

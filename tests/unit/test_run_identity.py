import runpy

import pytest
from bluesky import plan_stubs as bps

from mouse_bluesky.identity import RUN_IDENTITY, configure_run_identity, refuse_identity_keys
from mouse_bluesky.interactive import convenience, exposure, scans
from mouse_bluesky.plans import vacuum
from mouse_bluesky.plans.configure import apply_config
from mouse_bluesky.plans.public import measure_yzstage
from tests.integration.interactive_scans.test_scans_sim import make_peak_bundle
from tests.unit.plans.support import build_startup_namespace
from tests.unit.plans.test_measure_failure import MeasurementRig
from tests.unit.plans.test_vacuum import VacuumRig


@pytest.fixture
def startup_re():
    return runpy.run_path("qserver_profile/profile_mouse/startup/01_re.py")["RE"]


@pytest.fixture
def documents(startup_re):
    docs = []
    startup_re.subscribe(lambda name, doc: docs.append((name, doc)))
    return docs


def assert_run_identity(documents):
    starts = [doc for name, doc in documents if name == "start"]
    assert len(starts) == 1
    assert starts[0]["facility"] == "BAM"
    assert starts[0]["instrument"] == "MOUSE"
    assert "station" not in starts[0]
    stops = [doc for name, doc in documents if name == "stop"]
    assert len(stops) == 1
    assert stops[0]["exit_status"] == "success"


def empty_run(md=None):
    yield from bps.open_run(md=md)
    yield from bps.close_run()


def test_measurement_start_has_identity(startup_re, documents, tmp_path, monkeypatch):
    rig = MeasurementRig(tmp_path)
    monkeypatch.setattr("mouse_bluesky.plans.atomic.mouse_eiger_measure", rig.acquire)

    startup_re(rig.plan())

    assert_run_identity(documents)
    assert len(rig.exposures) == 3


def test_configuration_audit_start_has_identity(startup_re, documents):
    namespace = build_startup_namespace(include_eiger=True)

    startup_re(apply_config(config_id=123, config_root="tests/data/mouse_configs", namespace=namespace))

    assert_run_identity(documents)


@pytest.mark.parametrize("plan, pressure", [(vacuum.evacuate, 1), (vacuum.ventilate, 900)])
def test_vacuum_start_has_identity(startup_re, documents, monkeypatch, plan, pressure):
    rig = VacuumRig()
    rig.pressure.put(pressure)
    monkeypatch.setattr(vacuum, "VENTILATE_PUMP_OFF_DELAY_S", 0)
    monkeypatch.setattr(vacuum, "VENTILATE_HOLD_S", 0)

    startup_re(plan(namespace=rig.namespace))

    assert_run_identity(documents)


def test_interactive_scan_start_has_identity(startup_re, documents, tmp_path, monkeypatch):
    sim = make_peak_bundle()
    monkeypatch.setitem(exposure.configure_detectors_exposure.__kwdefaults__, "output_path", tmp_path / "scan")

    scans.peak_scan(sim.motor, -1, 1, RE=startup_re, dets=[sim.detector], num=21, table=False, plot=False)

    assert_run_identity(documents)


@pytest.mark.parametrize("md", [{"instrument": "MOUSE"}, {"facility": "X"}, {"station": "a"}])
def test_measurement_refuses_identity_before_any_side_effect(startup_re, documents, tmp_path, monkeypatch, md):
    namespace = build_startup_namespace(include_eiger=True)
    reads = []
    messages = []
    startup_re.msg_hook = messages.append
    root = tmp_path / "measurement"

    def record_read(*args, **kwargs):
        reads.append((args, kwargs))
        raise AssertionError("Identity must be refused before generator reads")

    for source in ("cu_generator", "mo_generator"):
        for field in ("voltage", "current"):
            signal = getattr(namespace[source], field)
            monkeypatch.setattr(signal, "get", record_read)
            monkeypatch.setattr(signal, "read", record_read)

    with pytest.raises(ValueError, match=next(iter(md))):
        startup_re(measure_yzstage(root_path=str(root), namespace=namespace, md=md))

    assert documents == []
    assert reads == []
    assert messages == []
    assert namespace["eiger"].writes == []
    assert not root.exists()
    assert list(tmp_path.iterdir()) == []


INTERACTIVE_FUNCTIONS = [
    scans.peak_scan,
    scans.valley_scan,
    scans.edge_scan,
    scans.capillary_scan,
    convenience.ct,
    convenience.test_measure,
]


@pytest.mark.parametrize("function", INTERACTIVE_FUNCTIONS, ids=lambda function: function.__name__)
@pytest.mark.parametrize(
    "md", [{"instrument": "mouse"}, {"instrument": "MOUSE"}, {"facility": "BAM"}, {"station": "a"}]
)
def test_interactive_refuses_identity_before_side_effects(startup_re, documents, tmp_path, monkeypatch, function, md):
    sim = make_peak_bundle()
    output = tmp_path / "output"
    monkeypatch.setitem(exposure.configure_detectors_exposure.__kwdefaults__, "output_path", output)
    writes = []
    messages = []
    temp_calls = []
    startup_re.msg_hook = messages.append

    def record_write(*args, **kwargs):
        writes.append((args, kwargs))
        raise AssertionError("Identity must be refused before detector writes")

    for signal in vars(sim.detector.cam).values():
        monkeypatch.setattr(signal, "set", record_write)

    def record_mkdtemp(*args, **kwargs):
        temp_calls.append((args, kwargs))
        raise AssertionError("Identity must be refused before temporary directory creation")

    monkeypatch.setattr(convenience.tempfile, "mkdtemp", record_mkdtemp)
    kwargs = {"RE": startup_re, "dets": [sim.detector], "md": md}
    if function in (convenience.ct, convenience.test_measure):
        args = ()
        kwargs["output_path"] = output
    else:
        args = (sim.motor, -1, 1)
        kwargs.update(table=False, plot=False)

    with pytest.raises(ValueError, match=next(iter(md))):
        function(*args, **kwargs)

    assert documents == []
    assert messages == []
    assert writes == []
    assert temp_calls == []
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("function", INTERACTIVE_FUNCTIONS, ids=lambda function: function.__name__)
def test_interactive_refuses_identity_before_resolving_devices(monkeypatch, function):
    module = convenience if function in (convenience.ct, convenience.test_measure) else scans

    def unexpected_resolution(*args, **kwargs):
        pytest.fail("Identity must be refused before resolving the RunEngine or detectors")

    monkeypatch.setattr(module, "resolve_run_engine", unexpected_resolution)
    monkeypatch.setattr(module, "resolve_default_detector", unexpected_resolution)
    args = () if module is convenience else (None, -1, 1)

    with pytest.raises(ValueError, match="instrument"):
        function(*args, md={"instrument": "MOUSE"})


@pytest.mark.parametrize("md", [{"station": "a"}, {"instrument": "mouse"}, {"facility": "X"}])
def test_validator_refuses_invalid_plan_identity(startup_re, documents, md):
    with pytest.raises(ValueError, match=next(iter(md))):
        startup_re(empty_run(md))

    assert documents == []


def test_validator_refuses_per_call_override(startup_re, documents):
    with pytest.raises(ValueError, match="instrument"):
        startup_re(empty_run(), instrument="mouse")

    assert documents == []


@pytest.mark.parametrize("key", ["facility", "instrument"])
def test_validator_refuses_missing_identity(startup_re, documents, key):
    del startup_re.md[key]

    with pytest.raises(ValueError, match=key):
        startup_re(empty_run())

    assert documents == []


def test_default_validator_is_preserved(startup_re, documents):
    with pytest.raises(ValueError, match="sample"):
        startup_re(empty_run({"sample": [1, 2]}))

    assert documents == []


def test_configure_run_identity_is_idempotent(startup_re, documents):
    validator = startup_re.md_validator
    configure_run_identity(startup_re)
    configure_run_identity(startup_re)
    assert startup_re.md_validator is validator

    startup_re(empty_run())
    assert_run_identity(documents)
    documents.clear()

    with pytest.raises(ValueError, match="station"):
        startup_re(empty_run({"station": "a"}))
    assert documents == []


def test_custom_validator_is_preserved(startup_re, documents):
    validated = []

    def custom_validator(md):
        validated.append(md)
        if "custom_required" not in md:
            raise ValueError("custom_required is missing")

    startup_re.md_validator = custom_validator
    configure_run_identity(startup_re)
    configure_run_identity(startup_re)

    startup_re(empty_run({"custom_required": True}))
    assert_run_identity(documents)
    assert len(validated) == 1

    documents.clear()
    with pytest.raises(ValueError, match="custom_required"):
        startup_re(empty_run())
    assert len(validated) == 2
    assert documents == []


@pytest.mark.parametrize("md", [None, {}])
def test_refuse_identity_keys_accepts_empty_metadata(md):
    refuse_identity_keys(md)


def test_refuse_identity_keys_names_all_offending_keys():
    with pytest.raises(ValueError, match="facility, instrument, station"):
        refuse_identity_keys({"facility": "BAM", "instrument": "MOUSE", "station": None})


def test_run_identity_is_read_only():
    with pytest.raises(TypeError):
        RUN_IDENTITY["instrument"] = "mouse"

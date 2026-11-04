# Operations

This document describes intended usage during development and beamtime.

## Roles & components

- **Queue Server startup profile**:
  - this repo includes a reference profile in
    `qserver_profile/profile_mouse/startup`,
  - production deployments may mirror/adapt this in an operations repo.
  - startup responsibilities:
    - instantiate devices (Eiger, motors, generators),
    - configure `RunEngine`,
    - configure baseline via `SupplementalData`,
    - optionally subscribe `TiledWriter`,
    - export plans for Queue Server discovery.

- **mouse-bluesky** (this repo):
  - provides plans: `measure_yzstage`, `apply_config`, `save_config`, `snapshot_state`, atomic plans,
  - provides interactive scans: `peak_scan`, `valley_scan`, `edge_scan`, `capillary_scan`,
  - provides protocol compilers and planner that fills the Queue Server.

## Typical workflow

### 1) Author logbook entries

Each entry includes:
- `protocol: str`
- `additional_parameters: Dict[str, str]`
  - optionally with a `__json__` value containing a JSON object for typed parameters
- proposal/sample metadata as needed

### 2) Compile and schedule

- load logbook entries into `Logbook2MouseEntry` objects
- build a protocol registry (e.g., `build_default_registry()`)
- compile entries → scheduled plan items (QueuePlan list)
- insert `apply_config` before every measurement

### 3) Pre-validate (static)

Before pushing items to the queue, run the static validator:
- plan names are known (plan registry or a curated allowlist),
- `config_id.nxs` exists for each used config,
- `/saxs/Saxslab` exists and contains scalar datasets.

Optional live checks (separate tool):
- read-only connectivity checks of a PV allowlist.

### 4) Populate queue via Queue Server API

Use the Queue Server ZMQ control address (default example):
- `tcp://127.0.0.1:60615`

Add items via `queue_item_add` in order produced by the planner.

### 5) Run queue

Start the queue from the Queue Server UI/CLI.

## Runtime behavior

### Vacuum plans

After deploying these plans, close and reopen the Queue Server environment so
`evacuate` and `ventilate` are loaded. From the repository root, use:

```bash
./evacuate.sh
./ventilate.sh --prioritize
```

The scripts only enqueue one item; start the queue separately. Both default to
the back of the queue. `--prioritize` inserts at the front, and the scripts
forward other CLI options such as `--zmq`, `--position`, `--user` and `--user-group`.
The equivalent commands are `mouse-bluesky evacuate` and `mouse-bluesky ventilate`.

Both plans resolve the required devices and read detector position, pressure
and valve outputs before any write. A failed pre-flight read or non-finite
pressure prevents execution. Each plan opens an audit run recording its
activity, target pressure and timeout. It disables checkpoint replay, sends a
best-effort close to each source shutter, then parks the detector at `detx=400`.
Missing, offline or slow shutters produce warnings and the plans continue;
safety relies on the shutters' own interlocks.

`evacuate` confirms `do7=0`, then `do6=1`, and polls pressure every 3 s until
pressure is at most 1 (default timeout 1800 s). The pump remains on at success.
On failure, timeout or abort, `do6` is left as it is, including staying on after
a failed evacuation; an operator decides what happens next.

`ventilate` confirms `do6=0`, waits 1 s, confirms `do7=1`, and polls every 1 s
until pressure is at least 900 (default timeout 600 s). It then holds for 10 s
and reads pressure again. A finalizer inside the audit run closes `do7` when
the valve sequence succeeds, fails, times out, is stopped or is aborted.
Aborting during the initial shutter wait issues no valve commands. An immediate
pause during ventilation ends the plan and runs cleanup rather than leaving
the vent open in a paused plan. If the worker process crashes or power is lost,
the finalizer cannot run and `do7` may stay open.

Valve outputs are always written, even if their cached values already match.
Each write waits for confirmation with a 30 s timeout; the slowly scanned
`do6_RBV` and `do7_RBV` signals are not used. The ordered commands keep `do6`
and `do7` from being enabled together. Every pressure read must be finite;
bad readings or a pressure timeout fail the plan and stop the queue.

### Baseline stream

Baseline devices are configured at RunEngine level via `SupplementalData`.
In the reference startup profile this is wired in `04_baseline.py` using
`build_baseline_signals(namespace=globals())`, and emits `baseline` at run boundaries.
Included baseline signals cover:
- mapped BASE motors,
- optional YZ and GI stage motors when present,
- generator voltage/current readbacks.

Only the generator voltage/current signals in `GENERATOR_BASELINE_SIGNALS`
are wrapped for optional baseline reads. If a generator IOC is offline when a
run opens or crashes during the run, its unavailable baseline values are
recorded as NaN with a warning naming the signal; the run continues. NaN here
means the readback was unavailable. Disconnected signals are not read, avoiding
a connection timeout, and their baseline descriptions stay the same across
connection changes.

Motors, `pressure_gauge` and `arduino` remain strict: a read failure still fails
the run. This tolerance applies only to baseline recording. An offline active
source still stops a measurement because its shutter and the voltage/current
reads in `write_im_craw_nxs` remain strict; the run is recorded as `fail`.

### Measurement failures and interruption

| Exit route | Shutter | `exit_status` | `COMPLETE` file |
|---|---|---|---|
| Success | Strict close, with no extra command | `success` | Written |
| Exception after the shutter open was attempted | One best-effort close | `fail`, with the reason | Not written |
| Abort | One best-effort close | `abort` | Not written |
| Stop | One best-effort close | `success` (Bluesky convention) | Not written |
| Halt | Not closed: Bluesky skips cleanup | `abort` | Not written |

A stopped measurement is recorded as `success`, so a missing `COMPLETE` file
shows that it did not finish. An energy configuration failure or `open_run`
failure sends no shutter close because the shutter open was never attempted.
If the strict close on the normal path fails, the measurement fails and sends
one best-effort retry. The original exception still reaches the caller even
if that retry fails.

The best-effort close waits up to 5 s. A warning means the shutter state is
unconfirmed, and safety relies on the interlocks. No motor moves are added on
failure: by maintainer decision, the beam stop stays where it was because the
detector tolerates the lab flux indefinitely.

Halt skips the close, and the shutter stays open while the RunEngine is paused.
A worker crash or power loss cannot run any cleanup.

### Snapshot stream

`measure_yzstage` emits a `snapshot` stream inside the run immediately before measurement.
This is used for debugging and state auditing.

### Interactive console usage

When running with `qserver-console` or `qserver-qtconsole`, startup exports:
- standard Bluesky plans (`count`, `scan`, `rel_scan`, `list_scan`, `grid_scan`, etc.),
- interactive fitting scans (`peak_scan`, `valley_scan`, `edge_scan`, `capillary_scan`).

Interactive scans support:
- minimal form: `scan_fn(motor, start, stop)`,
- extended form: `scan_fn(motor, start, stop, num, exposure_time)`.

### Tiled storage

Runs are persisted via TiledWriter subscription configured in beamline startup.
Each run’s metadata includes entry identifiers and configuration identifiers.

## Failure modes & recovery

- If a measurement fails:
  - the queue can be paused/stopped,
  - failed item(s) can be retried or removed,
  - because each measurement is one run, partial progress remains in Tiled.
- If configuration is mismatched:
  - recommended: add a lightweight “expected config id” guard to fail early.

## Recommended minimal CLI entrypoints (optional)

Consider adding console scripts (not included here by default):
- `mouse-logbook-validate` → compile + validate only
- `mouse-logbook-enqueue` → compile + validate + enqueue

## Defaults (environment variables)

The planner/CLI uses these environment variables:

- `MOUSE_DATA_ROOT` (default `/data/mouse`)
- `MOUSE_CONFIG_ROOT` (default `/data/mouse_configs`)

They are read via `mouse_bluesky.settings.Settings.from_env()` and can be overridden by CLI flags or by injecting extra kwargs during planning.

## CLI usage

The repository includes a small `mouse-bluesky` CLI:

- `mouse-bluesky validate LOGBOOK PROJECTS_DIR` compiles and statically validates the planned queue.
- `mouse-bluesky enqueue LOGBOOK PROJECTS_DIR` compiles, validates, and enqueues into a running Queue Server via the ZMQ control address.

These commands are intended for operator workflows where you want fast feedback before running the instrument.

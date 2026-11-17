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

### HTTP server (read-only queue access)

`event-timeline-tiled` runs on another server and reads the MOUSE status and queue
through `bluesky-httpserver==0.0.15`. Operators keep using the local ZMQ CLI and
scripts, including enqueue, evacuation and ventilation. The HTTP server connects
to `tcp://127.0.0.1:60615` (control) and `tcp://127.0.0.1:60625` (information), as
configured in `qserver_profile/http_server/config.yml`.

`start-mouse-re-manager.sh` binds both RE Manager ZMQ listeners only to loopback.
This takes effect at the next RE Manager restart. Keep that separate commit out
of deployment until the maintainer has checked for remote ZMQ users. Remote
control or monitoring must go through the HTTP server with its own account and
the scopes needed by that client; the dashboard account remains read-only.

#### Environment, database and TLS

Install the locked dependencies, activate the virtual environment, then create
the private directories and environment file outside the repository:

```bash
install -d -m 700 "$HOME/.config/mouse-http-server" "$HOME/.local/share/mouse-http-server"
touch "$HOME/.config/mouse-http-server/env"
chmod 600 "$HOME/.config/mouse-http-server/env"
```

Edit that file locally with a private editor. It is sourced as Bash assignments,
so quote values containing shell metacharacters. Set these variables (the example
paths below must be adapted to the instrument account):

| Variable | Value/purpose |
|---|---|
| `MOUSE_HTTP_READER_PASSWORD` | A generated, strong password for `timeline-reader`; required and nonempty. |
| `MOUSE_HTTP_DATABASE_URI` | Required fixed URI, e.g. `sqlite:////home/<user>/.local/share/mouse-http-server/http_server.sqlite`. Four slashes denote an absolute SQLite path. |
| `MOUSE_HTTP_HOST` | Defaults to `127.0.0.1`; set the instrument's lab interface address for the dashboard. |
| `MOUSE_HTTP_PORT` | Defaults to `60610`. |
| `MOUSE_HTTP_SSL_CERTFILE` | Absolute path to the site's trusted certificate/full chain, outside the repository, e.g. `/home/<user>/.config/mouse-http-server/tls/fullchain.pem`. |
| `MOUSE_HTTP_SSL_KEYFILE` | Absolute path to its private key, e.g. `/home/<user>/.config/mouse-http-server/tls/key.pem`; restrict it to the instrument account (`chmod 600`). |

The maintainer obtains the certificate, configures the lab interface and firewall,
and creates the real password and key after deployment. The certificate must cover
the hostname used by the dashboard, and its CA must be trusted there. Keep the TLS
directory private and renew certificates before expiry. Uvicorn terminates TLS
directly; there is no reverse proxy. Open the HTTP port only to the dashboard
server in any firewall.

Keep the database across restarts and back it up outside the repository. Stop the
HTTP server before making a plain file copy, or use SQLite's online backup tool.
The database stores identities and API key hashes; protect its directory and backups.
Losing it invalidates the existing keys. Changing the login password does not
revoke existing API keys: revoke those separately when rotating compromised credentials.

`MOUSE_HTTP_ENV_FILE` can select another private environment file; otherwise the
script reads `$HOME/.config/mouse-http-server/env`. It refuses missing/unreadable
files and files readable by group or others, empty required variables, and any set
`QSERVER_HTTP_SERVER_SINGLE_USER_API_KEY` or
`QSERVER_HTTP_SERVER_ALLOW_ANONYMOUS_ACCESS` (even an empty value). Unset these
overrides in the launching shell as well as in the file. Always start through the
script, since the library leaves an unset `${VARIABLE}` reference as literal text.

A network listener requires both TLS paths to be set and readable. For a local
check only, leave both TLS variables unset or empty and keep the host at
`127.0.0.1` or `localhost`; the script exports empty paths, which disable uvicorn
TLS. If either TLS path is supplied, both must be readable even on loopback.

#### Start, stop and check

From the repository, with its virtual environment active:

```bash
screen -S bluesky_http
./start-mouse-http-server.sh
# Detach with Ctrl-A, D.
```

The script locates its config relative to itself, so it also works from another
working directory. To stop, reattach with `screen -r bluesky_http` and press Ctrl-C;
this stops HTTP access without stopping the RE Manager. Restart the HTTP script
after changing its environment or config. Never use `--public`.

After creating the key below, check status with a private header file:

```bash
export MOUSE_HTTP_BASE_URL=https://instrument-hostname:60610
curl --fail --silent --show-error \
  --header @"$HOME/.config/mouse-http-server/dashboard.header" \
  "$MOUSE_HTTP_BASE_URL/api/status"
```

The file contains one line, `Authorization: ApiKey ` followed by the key. Keep it
mode `600`. The key stays out of command arguments and shell history. Use the
site's CA trust (`curl --cacert /path/to/site-ca.pem` if needed); do not disable
certificate verification. For a loopback check without TLS only, use
`http://127.0.0.1:60610`. Avoid verbose HTTP logging, shell tracing and header dumps.

#### Account and API keys

There is one account, `timeline-reader`, authenticated by the `mouse` provider's
`DictionaryAuthenticator`. `DictionaryAPIAccessControl` assigns it the custom
`timeline_reader` role with exactly `read:status`, `read:queue` and `user:apikeys`.
There are no operator or admin accounts. Both `unauthenticated_public` and
`unauthenticated_single_user` roles have no scopes, so accidental public or
single-user mode grants no queue access.

The role needs `user:apikeys` because HTTP server 0.0.15 requires that scope to
create and revoke one's own keys. The dashboard key itself has exactly
`read:status` and `read:queue`: it cannot edit or start the queue, open the worker,
read history or create more keys. Effective key scopes are intersected with the
owner's current role scopes. Anyone holding the account password can create more
read-only keys and revoke the account's keys; keep that password with the maintainer.
Always specify the two scopes when creating a dashboard key; omitting scopes
defaults to `inherit`, which also grants the role's key-management scope.

Log in with `POST /api/auth/provider/mouse/token`, form fields `username` and
`password`. Use the returned bearer token for `POST /api/auth/apikey` with:

```json
{"scopes": ["read:status", "read:queue"], "expires_in": null, "note": "event-timeline-tiled"}
```

For example, the following interactive Python session creates the key without
printing the password, token or key. Run it from the activated environment on a
trusted host. `MOUSE_HTTP_BASE_URL` must be the verified HTTPS URL (loopback HTTP is
permitted for a local check). For a private CA with Requests, set
`REQUESTS_CA_BUNDLE=/path/to/site-ca.pem` first.

```python
import getpass
import os
from pathlib import Path
import requests

base = os.environ["MOUSE_HTTP_BASE_URL"].rstrip("/")
directory = Path.home() / ".config/mouse-http-server"
directory.mkdir(mode=0o700, parents=True, exist_ok=True)
response = requests.post(
    f"{base}/api/auth/provider/mouse/token",
    data={"username": "timeline-reader", "password": getpass.getpass()},
    timeout=15,
)
response.raise_for_status()
token_header = {"Authorization": "Bearer " + response.json()["access_token"]}
response = requests.post(
    f"{base}/api/auth/apikey", headers=token_header,
    json={"scopes": ["read:status", "read:queue"], "expires_in": None,
          "note": "event-timeline-tiled"}, timeout=15,
)
response.raise_for_status()
key = response.json()["secret"]
def private_file(path):
    return open(path, "x", opener=lambda path, flags: os.open(path, flags, 0o600))
with private_file(directory / "dashboard.key") as stream:
    stream.write(key + "\n")
with private_file(directory / "dashboard.header") as stream:
    stream.write("Authorization: ApiKey " + key + "\n")
response = requests.get(
    f"{base}/api/auth/apikey", headers={"Authorization": "ApiKey " + key}, timeout=15,
)
response.raise_for_status()
print("Record first_eight:", response.json()["first_eight"])
del key, token_header, response
```

Use fresh filenames for a rotation: this example refuses to overwrite existing
files. The key has no expiry (`expires_in: null`); rotate it explicitly by creating
a replacement, transferring it securely, updating and checking the dashboard,
then revoking the old key. Transfer the raw `dashboard.key` to the dashboard
operator through a secure channel. Never put any password, token or key in the
repository, logs, a URL or a chat. Although the library accepts `api_key` query
parameters and cookies, use only the `Authorization: ApiKey …` header.

To inspect the current key and record its `first_eight`, use:

```bash
curl --fail --silent --show-error \
  --header @"$HOME/.config/mouse-http-server/dashboard.header" \
  "$MOUSE_HTTP_BASE_URL/api/auth/apikey"
```

This GET reports metadata for the supplied key; it does not list all the account's
keys. Keep an inventory of `first_eight`, purpose and expiry. To revoke a key,
log in again as `timeline-reader` and use the bearer token (not the dashboard key)
for `DELETE /api/auth/apikey?first_eight=…`. The non-secret prefix can go in that
URL; the full key must never go there. In a private Python session:

```python
import getpass
import os
import requests

base = os.environ["MOUSE_HTTP_BASE_URL"].rstrip("/")
response = requests.post(
    f"{base}/api/auth/provider/mouse/token",
    data={"username": "timeline-reader", "password": getpass.getpass()}, timeout=15,
)
response.raise_for_status()
token_header = {"Authorization": "Bearer " + response.json()["access_token"]}
response = requests.delete(
    f"{base}/api/auth/apikey", headers=token_header,
    params={"first_eight": input("Key first_eight to revoke: ").strip()}, timeout=15,
)
response.raise_for_status()
del response, token_header
```

Revocation is limited to the logged-in account's own keys. Confirm that the
revoked key subsequently returns `401`, then remove its private local files.

#### Maintainer's after-deployment checklist

These checks require the instrument and another host. They are deliberately
outside the repository tests:

1. Check whether any other computer uses ZMQ ports 60615/60625. Record each user
   or service and arrange HTTP access with its own account before deploying the
   separate loopback-binding commit. Additional accounts need explicit roles.
2. Provision the environment file, persistent database, trusted certificate and
   private key; restrict firewall access to the dashboard server. Start the HTTP
   screen session and create the two-scope dashboard key.
3. From the dashboard host over verified HTTPS, confirm `GET /api/status` and
   `GET /api/queue/get` return `200` with the dashboard key.
4. With that key, confirm `POST /api/queue/item/add`, `POST /api/queue/start`,
   `POST /api/environment/open`, `GET /api/history/get` and
   `POST /api/auth/apikey` are refused with `401` or `403`. Missing or wrong keys
   must give `401` for both read routes. A revoked key must also give `401`.
5. Once remote ZMQ users have been checked/migrated, deploy the separate
   loopback-binding commit and restart the RE Manager at an operator-approved
   time. From another host, verify ports 60615 and 60625 do not answer. Locally
   verify `mouse-bluesky enqueue …`, `evacuate.sh` and `ventilate.sh` still work
   over `tcp://127.0.0.1:60615`, scheduling hardware actions with the operator.
6. Report the lab HTTPS URL (hostname and port), certificate issuer,
   `bluesky-httpserver` version (`0.0.15`), provider (`DictionaryAuthenticator`),
   key scopes, no expiry and `first_eight`, and whether any remote ZMQ users
   existed. Send the full key only over the secure channel.
7. On the dashboard server, configure `ETT_QUEUES=MOUSE=http:https://<host>:<port>`
   and `ETT_QUEUE_MOUSE_API_KEY_FILE` pointing to the private raw key file, then
   run event-timeline-tiled's live queue-panel check.

### Vacuum plans

After deploying these plans, close and reopen the Queue Server environment so
`evacuate` and `ventilate` are loaded. From the repository root, use:

```bash
./evacuate.sh
./ventilate.sh
```

The Queue Server must be idle with an open worker environment. Each command
inserts its plan at the front followed immediately by a `queue_stop` instruction,
then starts the queue. After the plan, the instruction is consumed and the queue
stops, leaving all existing measurements in their original order. If the queue
is not idle, the command refuses without adding anything: stop the queue, wait
until it is idle, then run the command again.

`--prioritize` and `--position front` are accepted in this default mode and
do not change its behavior. `--position back` requires `--enqueue-only`, which
only enqueues the plan, without adding a stop or starting the queue. In that
mode the default position is the back, and `--position` and `--prioritize` work
as before. For example, `./ventilate.sh --enqueue-only` queues ventilation after
an overnight measurement queue.

The scripts forward CLI options such as `--zmq`, `--user`, `--user-group` and
`--quiet` in both modes. Quiet suppresses success output, but errors are printed.
The equivalent commands are `mouse-bluesky evacuate` and `mouse-bluesky ventilate`.

For a sample rack change:

```bash
qserver queue stop
# Wait until the current measurement finishes and the manager is idle.
./ventilate.sh
# Wait for ventilation to finish, then change the rack.
./evacuate.sh
# Wait for evacuation to finish, then continue the measurements.
qserver queue start
```

If a vacuum plan fails or is aborted, the queue stops and Queue Server
(0.0.24) puts the plan back at the front, still followed by the `queue_stop`
instruction. The next start retries the plan and then stops again. To skip the
retry, remove both the plan and the instruction. A plan ended with
`qserver re stop` counts as finished and is not put back, so only the
instruction stays at the front and the next start stops immediately. This was
checked against a local Queue Server with dummy plans.

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
source stops a measurement at the power check before a run opens. Its shutter
and the voltage/current reads in `write_im_craw_nxs` also remain strict if a
failure occurs later in the measurement; the run then records `fail`.

### Measurement failures and interruption

`measure_yzstage` checks the active source's power once, immediately after
resolving devices and before configuring detector energies. It requires at
least 90% of full power: Cu at least 27 W of 30 W, Mo at least 45 W of 50 W.
The generator readbacks are raw integers: each voltage count is 10 V and each
current count is 10 uA, so power in watts is raw voltage × raw current × 1e-4.
Cu at 5000/60 is 50 kV × 0.6 mA = 30 W. Mo is assumed to use the same scaling;
this cannot be verified while its source is faulted.

Non-finite or insufficient power raises an error naming the generator, power,
minimum and both raw readings. Read failures propagate unchanged. A failed
check stops the queue before anything is written: no detector energy writes,
sequence directory, run documents or shutter commands. The check only reads
the selected generator and does not monitor source trips during exposures.

| Exit route | Shutter | `exit_status` | `COMPLETE` file |
|---|---|---|---|
| Success | Strict close, with no extra command | `success` | Written |
| Exception after the shutter open was attempted | One best-effort close | `fail`, with the reason | Not written |
| Abort | One best-effort close | `abort` | Not written |
| Stop | One best-effort close | `success` (Bluesky convention) | Not written |
| Halt | Not closed: Bluesky skips cleanup | `abort` | Not written |

A stopped measurement is recorded as `success`, so a missing `COMPLETE` file
shows that it did not finish. A source power check failure, energy configuration
failure or `open_run` failure sends no shutter close because the shutter open
was never attempted.
If the strict close on the normal path fails, the measurement fails and sends
one best-effort retry. The original exception still reaches the caller even
if that retry fails.

Strict shutter open and close commands wait up to 10 s, including the
interactive `open_shutter` and `close_shutter` plans. A timeout fails the
measurement and sends one best-effort close, preserving the original error.
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

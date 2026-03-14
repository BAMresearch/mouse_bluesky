# Queue Server demo (no hardware)

This demo starts RE Manager with a local startup directory and enqueues **simulated** plans.
It is safe to run on a laptop with no EPICS/hardware connected.

## Prerequisites

- `mouse_bluesky` installed in the current venv
- `bluesky-queueserver` installed (you have v0.0.24)
- Redis running locally (RE Manager uses Redis by default)

## 1) Create a demo startup file

Ensure the file exists:

- `qserver_profile/profile_mouse/startup/00_sim.py`

It should define the demo plans:
- `sim_count`
- `sim_move_and_count`
- `sim_sleep`

Note:
Create 01_re.py that defines RE = RunEngine({})

## 2) Start RE Manager

In terminal A (repo root):

```bash
start-re-manager --startup-dir ./qserver_profile/profile_mouse/startup
````

Notes:

* On the first run, `existing_plans_and_devices.yaml` does not exist yet.
  This is expected. The file is generated after the environment is opened.

## 3) Open the worker environment

In terminal B:

```bash
qserver environment open
```

Wait until it reports the environment is open.

Check status:

```bash
qserver status
```

You want:

* `worker_environment_exists: True`
* `worker_environment_state: idle`

## 4) Verify plans are discovered

```bash
qserver existing plans
qserver allowed plans
```

You should see:

* `sim_count`
* `sim_move_and_count`
* `sim_sleep`

If needed, force reload:

```bash
qserver permissions reload lists
```

## 5) Enqueue demo plans (CLI)

Add to queue:

```bash
qserver queue add plan '{"name":"sim_sleep","args":[],"kwargs":{"seconds":0.5}}'
qserver queue add plan '{"name":"sim_count","args":[],"kwargs":{"num":3,"delay":0.1}}'
qserver queue add plan '{"name":"sim_move_and_count","args":[],"kwargs":{"pos":2.0,"num":2}}'
```

Inspect queue:

```bash
qserver queue get
```

## 6) Start the queue

```bash
qserver queue start
```

Observe progress with:

```bash
qserver status
qserver history get
```

## 7) Cleanup

Stop the queue (if running):

```bash
qserver queue stop
```

Close the environment:

```bash
qserver environment close
```

Stop RE Manager:

```bash
qserver manager stop
```

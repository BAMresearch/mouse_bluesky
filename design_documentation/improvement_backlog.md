# Improvement Backlog

This document tracks implementation and documentation gaps found during review so
they can be handled incrementally without losing the current design context.

## 1) Measurement defaults and interactive safety

Area:
- `src/mouse_bluesky/plans/public.py`
- related tests under `tests/unit/plans/`

Summary:
- The current `measure_yzstage` defaults encode safety and legacy beamline
  behavior, but that behavior is not documented clearly enough.
- `ymd="20261232"` is an intentional impossible-date sentinel. The goal is to
  prevent an omitted `ymd` from silently writing into an existing date-based
  data tree such as the current day.
- The X-ray source is still selected from the first digit of `config_id`
  (`odd -> cu_generator`, `even -> mo_generator`). This is legacy behavior that
  remains operationally relevant for now.

Why this is an issue:
- The implementation is carrying real beamline intent, but that intent is
  opaque to readers and is currently mismatched with some tests.
- Existing tests assume a simpler interactive-default contract
  (`proposal="interactive"`, `config_id=-1`, `shutter` in namespace), while the
  implementation expects production-like metadata and a generator object.
- The public API currently mixes three concerns:
  - safe output isolation when metadata is incomplete,
  - interactive convenience,
  - legacy source-selection rules.

Questions to resolve:
1. Should the impossible-date sentinel remain the default behavior, but be made
   explicit through a named constant and clearer docs?
2. Should omitted `ymd` remain supported at the API boundary, or should it be
   treated as an incomplete request that must be resolved before writing?
3. Should the legacy `config_id -> generator` mapping remain implicit, or
   should an explicit override parameter be introduced while preserving legacy
   fallback behavior?
4. What is the supported namespace contract for interactive use:
   `shutter`, `cu_generator` / `mo_generator`, or both?

Incremental path:
1. Document the current behavior precisely in code and docs.
2. Align unit tests with the intended current contract.
3. Introduce clearer names or explicit parameters without changing runtime
   semantics.
4. Replace the legacy generator heuristic later, once config/source metadata is
   represented explicitly.

## 2) Broken pytest collection for integration convenience tests

Area:
- `tests/integration/interactive_scans/test_convenience_sim.py`

Summary:
- The repository-level `pytest` entrypoint currently fails during collection
  because `test_convenience_sim.py` uses a relative import but `tests/` is not
  a package.

Why this is an issue:
- The documented test command is not reliable.
- It hides later test failures because collection stops early.

Incremental path:
1. Decide whether `tests/` should be a package.
2. Either add `__init__.py` files or switch the import to a non-relative form.
3. Re-run the documented test command and keep it green.

## 3) Baseline tests have drifted away from the shipped startup namespace

Area:
- `src/mouse_bluesky/plans/configure.py`
- `qserver_profile/profile_mouse/startup/03_init_devices.py`
- `tests/unit/plans/test_configure_baseline.py`

Summary:
- The baseline mapping expects `det_stage.x/y/z`, which matches the shipped
  startup profile.
- The current baseline unit fixture still models detector axes as
  `eiger.cam.x/y/z`, so the unit suite is asserting against an outdated
  namespace shape.

Why this is an issue:
- Unit tests fail even though the mapping is consistent with the current
  startup profile.
- The tests are not protecting the actual runtime contract.

Incremental path:
1. Establish one shared fake namespace that mirrors the startup profile.
2. Reuse it across baseline, config, and measurement tests.
3. Keep the baseline contract documented in one place.

## 4) Dependency installation is tied to a moving Git branch

Area:
- `pyproject.toml`

Summary:
- `mouse-logbook` is installed from the GitHub `main` branch.

Why this is an issue:
- Environments are not reproducible.
- Fresh installs depend on network availability and upstream branch state.

Incremental path:
1. Pin a commit or release tag.
2. Decide whether `mouse-logbook` belongs in base dependencies or in a CLI /
   planner extra.

## 5) Documentation paths and examples have drifted from the repository layout

Area:
- `README.md`
- `design_documentation/demo_setup.md`

Summary:
- Some docs still point at outdated paths such as `qserver_profile/startup/`
  and `tests/unit/interactive/`.

Why this is an issue:
- New contributors can follow the docs and still land in the wrong place.

Incremental path:
1. Sweep the docs for stale paths.
2. Keep examples aligned with the actual startup profile and test layout.

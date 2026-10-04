# Developing Neurath

[한국어](../../ko/contributing/index.md) · [Core contract](core-v2-spec.md)

Read the current user request, `AGENTS.md`, installed policy and project bindings. Inspect the working tree before editing. Recover existing work with `session_status` and `task_list`; claim the checkout only for writes. Follow the Task’s ordered skill phases. Edit packaged originals under `src/neurath/_assets`, not installed projections.

Prepare with `uv sync --locked`. After execution changes, run `uv run --locked python tools/build_manifest.py`, then `uv run --locked python tools/check.py`. The full success marker requires every check to pass. Build and validate the exact distribution separately. `./setup --self` changes installation, not an already running host. Reconnect through the host’s supported path and observe activation. Public release requires authorization and exact asset verification.

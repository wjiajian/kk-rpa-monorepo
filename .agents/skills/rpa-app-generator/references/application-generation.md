# Application generation

## Identity and structure

One requirement has one stable `app_id`, directory, package and entrypoint. Reuse them for later revisions.

Create the standard independent files from `AGENTS.md`, including `app.toml`, `catalog.lock.json`, `pyproject.toml`, `uv.lock`, `.python-version`, local configuration examples, requirement artifacts, package source, tests and reviews. The application uses a local path dependency on `rpa-core`, while its `.venv` and lockfile belong only to that application.

Ignored local-only paths include `.env`, `stores.local.toml`, requirement screenshots, Profiles, runs and runtime artifacts. Do not add placeholder files that make ignored evidence appear tracked.

## Generation order

1. Reserve the conflict-free identity and add ignore rules.
2. Create the human-readable Memory with exactly one `toml requirement-canonical` block.
3. Generate JSON Spec from that canonical model and set one computed requirement hash in Memory, Spec and manifest.
4. Materialize verified snapshots and complete candidates.
5. Generate Program/Step orchestration, input models, validators and CLI.
6. Generate Fake Browser tests for the full ordered flow, failures and recovery.
7. Generate documentation and the implementation report from observable status.
8. Create the application-local environment and lockfile with uv; never hand-edit `uv.lock`.

## Runtime shape

- A separate `login` command owns interactive login; business `run` only requires an authenticated persistent Profile.
- Every external operation goes through `ExecutionContext` services.
- Each Step declares stable ID, inputs, outputs, success conditions, timeout, retries, resume, recovery and side effect.
- Preview permits authorized page reads and downloads but blocks external business writes. Live always requires a separate bounded grant.
- Open candidates make `check`, normal `run` and `resume` fail closed. Refusal must happen before creating a run directory or launching a browser.

Modify an existing application only after a read-only file/step diff is approved. Apply incremental patches and retain human changes.

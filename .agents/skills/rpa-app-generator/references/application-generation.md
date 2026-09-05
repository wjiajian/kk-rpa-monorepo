# Application generation

## Identity and structure

One requirement has one stable `app_id`, directory, package and entrypoint. Reuse them for later revisions.

Create the standard independent files from `AGENTS.md`: `app.toml`, `requirement.md`, `elements.toml`, `pyproject.toml`, `uv.lock`, `.python-version`, `config/stores.example.toml`, package source and focused tests. The application uses a local path dependency on `rpa-core`, while its `.venv` and lockfile belong only to that application.

Ignored local-only paths include `.env`, `stores.local.toml`, requirement screenshots, Profiles, runs and runtime artifacts. Do not add placeholder files that make ignored evidence appear tracked.

## Generation order

1. Reserve the conflict-free identity and add ignore rules.
2. Create `requirement.md` with exactly one `toml requirement-canonical` block; compute one requirement hash and set it in the requirement, manifest and Program.
3. Create one application-local `elements.toml`. Copy only locators already verified for this application; leave unknown locators unresolved and link them to requirement IDs.
4. Generate the ordered Steps, runtime configuration loader, stage-aware element verifier and the short CLI forwarding to `rpa_core.cli`.
5. Add the production Fake context builder required by `ApplicationDefinition`, plus focused happy-flow, failure and recovery tests.
6. Create the application-local environment and lockfile with uv; never hand-edit `uv.lock`.
7. Update concise application documentation from observable status.

## Runtime shape

- `run` owns session recovery: it checks the persistent Profile, logs in when needed, and verifies the configured account identity before business Steps.
- Every external operation goes through `ExecutionContext` services.
- Each Step declares stable ID, inputs, outputs, success conditions, timeout, retries, resume, recovery and side effect.
- Preview permits authorized page reads and downloads but blocks external business writes. Live requires the explicit confirmation and authorization defined by `AGENTS.md`.
- Unresolved requirement or element IDs make normal `run` and `resume` fail before creating a run directory or launching a browser.

Modify an existing application only after a read-only file/step diff is approved. Apply incremental patches and retain human changes.

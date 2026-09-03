# rpa-core

`rpa-core 0.7.0` provides the versioned App/Requirement contracts, reusable Instruction contract, element/instruction Catalog snapshots, repository gates, execution runtime, atomic checkpoints, structured events, Preview/Live policy, and browser boundary used by independent RPA applications.

Key boundaries:

- V1 App/Requirement documents remain readable; new applications use V2.
- `InstructionRegistry` validates exact inputs and outputs, executes an independent verifier, maps unexpected failures to stable errors, and never owns Step checkpoints.
- `snapshot_catalog()` copies verified top-level elements/instructions plus their dependency closure into an application and writes `catalog.lock.json`.
- `verify_catalog_snapshot()` reads only the application copy and fails on missing or changed content, unsafe paths, symlinks, hardlinks, unknown dependencies, cycles, or duplicate IDs.
- `BrowserActions`, unresolved-safe `ElementSpec`, redacted `SecretValue`, `FakeBrowserActions`, the DrissionPage action adapter, and `BrowserManager` prevent DrissionPage objects from escaping into application code.
- `AuthorizationStore` persists versioned JSON records and uses a per-record POSIX `flock` to atomically consume an exact `AuthorizationScope` once before a real browser launch. Callers can bind the store to a trusted application directory with `AuthorizationStore(root, boundary=app_dir)` so symlinked ancestors and path escape fail closed.
- `AuthorizedBrowserActions` rechecks the claimed session, current step, element, action, and top-level tab origin at every browser boundary. Embedded frames in a fixed internal-tool flow are selected by frozen `ElementSpec` locators and are not origin-authorized separately. Resume scopes additionally bind the checkpoint digest and resumed step.
- The DrissionPage adapter still accepts an optional same-context origin guard for stricter integrations, but the standard authorization wrapper does not inject it. Unmanaged new tabs remain outside this fixed-tab adapter; a stricter threat model requires an explicit frame/new-target policy.
- `BrowserStartError.real_browser_launched` is reliable after a Chromium object has been returned. If a trusted Chromium constructor starts a process and raises before returning the object, the caller needs process/port-level observability to prove whether a short-lived launch occurred.
- One separately developer-granted Live `AuthorizationRecord` contains the exact nested external write scopes for that invocation. Each Live adapter atomically claims its matching write immediately before the backend; a legacy in-memory `LiveWriteGrant` alone is never sufficient.
- A normal write API response is not success evidence. The backend must independently read the exact `target` and `data_scope` back in deterministic order; only a matching record count and canonical payload digest produce `SUCCEEDED`. A missing read-back capability is rejected before the write claim or backend call. A post-write query error, invalid response, or mismatch fails closed, records `UNKNOWN`, and cannot be replayed with the consumed write claim.
- `exception_diagnostics()` renders a redacted, root-cause-first exception chain and structured traceback. Trusted project errors with a stable `error_code` include the safe message and repo-relative `file`/`line`/`function`/`code`; untrusted messages and source lines are redacted, absolute external paths are sanitized, and locals are never serialized.

Package tests are side-effect-free. Passing them does not mean a real Chromium session, login, candidate verification, Preview, Live write, developer review, or business acceptance has completed.

```bash
uv sync --locked
uv run --locked pytest
```

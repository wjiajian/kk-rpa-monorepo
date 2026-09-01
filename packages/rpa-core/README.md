# rpa-core

`rpa-core 0.2.0` provides the versioned App/Requirement contracts, reusable Instruction contract, element/instruction Catalog snapshots, repository gates, execution runtime, atomic checkpoints, structured events, Preview/Live policy, and browser boundary used by independent RPA applications.

Key boundaries:

- V1 App/Requirement documents remain readable; new applications use V2.
- `InstructionRegistry` validates exact inputs and outputs, executes an independent verifier, maps unexpected failures to stable errors, and never owns Step checkpoints.
- `snapshot_catalog()` copies verified top-level elements/instructions plus their dependency closure into an application and writes `catalog.lock.json`.
- `verify_catalog_snapshot()` reads only the application copy and fails on missing or changed content, unsafe paths, symlinks, hardlinks, unknown dependencies, cycles, or duplicate IDs.
- `BrowserActions`, unresolved-safe `ElementSpec`, redacted `SecretValue`, `FakeBrowserActions`, the DrissionPage action adapter, and `BrowserManager` prevent DrissionPage objects from escaping into application code.

Package tests are side-effect-free. Passing them does not mean a real Chromium session, login, candidate verification, Preview, Live write, developer review, or business acceptance has completed.

```bash
uv sync --locked
uv run --locked pytest
```

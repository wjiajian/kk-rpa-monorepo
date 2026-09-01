# rpa-core

`rpa-core` provides the versioned application and requirement contracts, repository gates, execution runtime, atomic checkpoints, structured events, Preview/Live write policy, and the browser boundary used by every independent RPA application.

The package includes `BrowserActions`, unresolved-safe `ElementSpec`, redacted `SecretValue`, download/evidence references, `FakeBrowserActions`, and a DrissionPage 4.1.1.4 action adapter. `BrowserManager` now owns Chromium creation, persistent-profile exclusion, dynamic local-port leases, run-scoped action artifacts, and keep/reuse/terminate lifecycle policies. Application command binding and real Chromium verification remain gated work.

```bash
uv sync --locked
uv run --locked pytest
```

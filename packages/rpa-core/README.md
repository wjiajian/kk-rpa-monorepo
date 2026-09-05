# rpa-core

`rpa-core 0.7.0` provides the shared command surface, browser boundary, executable Step assertions, element verification, runtime and checkpoints used by independent RPA applications.

Key boundaries:

- `rpa-app test` builds the application Program itself, executes every declared counterexample against an application Fake context, and only then runs pytest. An application cannot opt out by omitting its own test.
- `rpa-app doctor` checks Python 3.12, local configuration, Chrome, blockers and whether the package environment matches `uv.lock`; it never launches a browser.
- `rpa-app run`, `resume` and `verify-elements` reject configuration or identity errors before launch and report `real_browser_launched` from the actual lifecycle state.
- `BrowserActions`, `ElementSpec`, `SecretValue`, `FakeBrowserActions`, the DrissionPage adapter and `BrowserManager` keep DrissionPage objects out of application code. New-tab switching only accepts a tab that appeared after the click.
- `Runner` executes retries, verification and atomic checkpoints. Resume validates application, program, version, requirement, run, account and mode identity before constructing `BrowserManager`.
- Each application owns one `requirement.md`, one `elements.toml` and its Python Step sequence. Cross-application instruction or element packages are created only after a third application proves real repetition.
- Legacy App/Requirement, Catalog, Instruction and Authorization contracts remain readable for repository compatibility. Neither active application uses them in its runtime path, and new applications must not depend on them.

Package tests are side-effect-free. Passing them does not mean a real Chromium session, login, candidate verification, Preview, Live write, developer review, or business acceptance has completed.

```bash
uv sync --locked
uv run --locked pytest
```

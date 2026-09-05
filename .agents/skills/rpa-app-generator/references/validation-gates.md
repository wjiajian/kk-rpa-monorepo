# Validation gates

Run only side-effect-free validation during initial generation.

## Required checks

- load `app.toml`, `requirement.md` and `elements.toml` through public `rpa-core` loaders;
- recompute the requirement hash and verify manifest, requirement and Program identity alignment;
- run framework-enforced Step counterexamples, ordered-flow, failure and resume tests through `rpa-app test`;
- run syntax/static, architecture-boundary, sensitive-content and ignored-path checks;
- confirm `.venv`, `.env`, `stores.local.toml`, screenshots, Profiles and runs are untracked;
- run `uv lock --check`, `uv sync --check --locked`, repository validation and `git diff --check`.

`doctor` validates local tools and configuration without launching a browser. `test` executes framework counterexamples and offline tests. Normal `run` and `resume` identify open blocker IDs and fail before creating runtime state.

`verify-elements`, `run` and `resume` are real-browser commands and require the exact user authorization required by `AGENTS.md`; command-line `--yes` is only the program's local confirmation and does not grant the agent permission to launch a browser.

## Report language

Keep these states separate:

- framework tests passed;
- application Fake tests passed;
- public login page inspected;
- authenticated element verification completed;
- real Preview completed;
- external write verified;
- developer review passed;
- business acceptance passed.

Passing an earlier state never implies a later one. Stop and report exact blockers and the next authorization needed.

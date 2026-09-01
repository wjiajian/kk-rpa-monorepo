# Validation gates

Run only side-effect-free validation during initial generation.

## Required checks

- load `app.toml`, Memory, Spec and catalog lock through public `rpa-core` loaders;
- compare Memory and Spec field by field and recompute their hash;
- verify manifest identity, revision and hash alignment;
- verify catalog files, dependency closure and hashes;
- run Fake Browser instruction, ordered-flow, failure and resume tests;
- run syntax/static, architecture-boundary, sensitive-content and ignored-path checks;
- confirm `.venv`, `.env`, `stores.local.toml`, screenshots, Profiles and runs are untracked;
- run `uv lock --check` and `git diff --check`.

`doctor` may validate local tools and configuration without launching a browser. `test` may execute offline tests. `check` must identify every open `PC-*`, `UE-*` and `UI-*` and return a failing status while blockers exist.

Normal `run` and `resume` must reject blockers before creating `runs/<run_id>/`. `login` and `verify-candidates` must not proceed without an exact real-browser authorization and resolvable candidate scope.

## Report language

Keep these states separate:

- framework tests passed;
- application Fake tests passed;
- public login page inspected;
- authenticated candidate verification completed;
- real Preview completed;
- external write verified;
- developer review passed;
- business acceptance passed.

Passing an earlier state never implies a later one. Stop and report exact blockers and the next authorization needed.

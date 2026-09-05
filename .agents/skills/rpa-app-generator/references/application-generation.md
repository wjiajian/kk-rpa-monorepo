# Application generation

Each application owns app.toml, a readable requirement.md, elements.toml, pyproject.toml, uv.lock, .python-version, config/stores.example.toml, package source, tests and its own .venv. Use a local path dependency on rpa-core.

app.toml declares app_id, name and entrypoint. Read current interfaces from rpa_core.cli, runtime and verification; do not copy obsolete interfaces from historical ADRs.

## Runtime shape

- ProgramSpec carries app_id and name.
- BaseProgram receives an ordered sequence of Steps; login and account verification are explicit Steps.
- StepSpec carries step_id, name and timeout_seconds.
- Each Step implements execute(context), verify(context, result) and counterexamples().
- ApplicationDefinition binds app_dir, build_program, load_runtime_options, build_test_context and verify_element_stages. build_services(context) optionally provides actual business services.
- load_runtime_options(account) returns RuntimeOptions with account_id, profile_dir, download_dir, optional debug_port/browser_path, inputs and metadata. Put serializable business parameters that must survive resume in inputs; keep credentials and runtime-only objects in metadata.
- Use resolve_download_directory for download paths. The two existing applications default to ../../runs/downloads relative to their app directory. The CLI clears that directory for a new run or verify-elements, and preserves it for resume; evidence remains under each app's runs/<run_id>.
- Runner stops on failure and records the inputs and completed outputs. A new run starts at the first Step; resume <run_id> --from-step <step_id> continues from the position selected by the agent. Do not implement framework-level write retries, compensation or partial-write recovery.

External operations use context services. Missing Feishu, database or Excel services must fail clearly; do not substitute fake backends in production. Implement actual service adapters when a concrete requirement needs them.

run defaults to LIVE without interaction. A service or Step that supports --preview must explicitly implement its preview behavior using context.mode; the mode flag alone does not intercept browser writes.

## Test fixtures

Provide one build_test_context(step, case, temporary_root), shared by CLI and pytest. None selects a successful normal scenario. Counterexample states override only relevant page conditions. Fixtures put business parameters in context.inputs, just like the real application.

Every Step needs a successful baseline and at least one counterexample whose execute succeeds but verify returns False. For expected action failures, declare expected_error. Use after_execute to change a fake page or local test artifact when failure happens after an action.

Keep stage-aware element checks. A menu item expected to be absent before opening must also be absent in the normal test fixture at that stage.

For resume, test that original dates/filter values survive changes to current configuration, the selected suffix executes, completed transient page states are not rechecked, and existing files remain available.

Generate the lockfile with uv and synchronize the application environment. Keep local configuration, Profiles, screenshots, downloaded business data and runtime artifacts untracked.

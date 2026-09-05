# Agent-directed resume

Use this workflow when the user wants the agent to diagnose and continue a failed RPA application.

1. Read the application's requirement.md and source, then its failed runs/<run_id>/result.json and events.jsonl. Identify the failure, completed outputs, original inputs, account, mode and download directory. Check the selected Step's required page state, output fields and actual verify conditions. Keep private run data out of tracked files.
2. Inspect and fix the actual cause. Run focused offline tests when code changes. Use the user's existing authorization for real browser access and continuing the named program; do not request the same permission again.
3. Use rpa_core.cli.open_recovery_session(application, run_id, credentials=credentials) to load the original inputs, completed outputs, account, mode and downloads with the application's usual runtime options and services. Inspect the retained browser and confirm the account and page state. BrowserManager records failed-browser handoffs under runtime/browser-manager/handoffs and adopts that browser for a later command. Use the core BrowserActions boundary for page operations.
4. Prepare the page and files required by the chosen step. If the browser or session is gone, choose an earlier navigation/login step or restore the page before continuing.
5. Select --from-step explicitly. Normally the selected step runs again. If the agent has temporarily completed the failed business step, supply --step-result as its ordinary execute output: the original verify must pass before the framework records success and continues. The prefix must already have successful results. Never change the success condition or mark a step complete by editing result.json.
6. Run the command from the application directory:

    uv run rpa-app resume <run_id> --from-step <step_id>

The command uses the source account, mode, inputs and download directory. Supply --credentials again when using invocation credentials; otherwise local configuration provides them. Credentials are never saved with inputs. Downloaded files and the original failed record remain unchanged; a new record links resumed_from and from_step.

For temporary completion, save the failed step's output to a local JSON file in the ignored run directory and invoke:

    uv run rpa-app resume <run_id> --from-step <failed_step> --step-result "@step-result.local.json" --locator-overrides "@locators.local.json" --credentials "@credentials.local.json"

Omit optional arguments when not needed. A locator override is an object such as `{"demo.page.target":{"locator":"css:#replacement","frame":null}}`. The framework accepts only locator fields, validates the original result condition, and uses the overrides for this attempt's verification and later steps. It never changes elements.toml or automatically reuses the overrides in another attempt. If the original condition still cannot be verified, retain failure and investigate; business-flow changes require updating the requirement and program.

For an observed guide or transient dialog, define a temporary auxiliary ElementSpec and operate through ctx.browser. Keep the observation and result in the run evidence; no permanent catalog entry is required for a one-time action. This is distinct from locator overrides, which can only replace fields of existing catalog IDs. Move auxiliary handling into the application only when it becomes a confirmed part of the normal flow.

The public helper returns context, source_record and browser_adopted:

```python
from rpa_core.cli import open_recovery_session

with open_recovery_session(APPLICATION, run_id, credentials=credentials) as recovery:
    ctx = recovery.context
    # Inspect account and page, then act through ctx.browser using the original inputs.
    # Save actual failed-step output to an ignored local JSON file when needed.

# Invoke resume only after exiting the session and releasing Profile ownership.
```

Opening the session does not execute or verify any Step. It refuses successful runs, other applications' records, missing saved inputs and incomplete completed outputs. Credentials come from this invocation or local configuration. The source result.json is unchanged; recovery-events.jsonl uses the existing redacted diagnostic format. Normal exit and handler errors detach through BrowserManager, releasing the Profile lock and port lease while retaining the browser. browser_adopted reports attachment, not successful login or page recovery. Do not assemble another ExecutionContext or browser manager in application recovery scripts.

Keep a persistent terminal if the execution host reaps child browsers when a command ends. Examples: [Jushuitan S003](../../../../apps/inventory_jushuitan_export_stock/examples/recover-s003.md) and [Jingmai S006](../../../../apps/report_jingmai_export_product_detail/examples/recover-s006.md). Temporary locator changes made in the recovery context still need an explicit --locator-overrides on resume; they do not carry across sessions.

Jingmai example: if export generation succeeded and S006 failed, prepare the download list and resume at S006. The old export dialog need not remain visible, the original target date remains fixed, and S004 does not run again.

Jushuitan example: if filtering succeeded and S005 failed, prepare the inventory page and resume at S005. The original brand remains fixed even if the current local configuration changed.

Each executed or agent-completed step still verifies its result. If resumption fails, inspect the new failed record before selecting another attempt. A new run starts from the beginning and preserves existing downloads; do not use it as a substitute for requested continuation.

Records from older versions without saved inputs cannot be resumed by this command. Do not invent missing business parameters or silently change the task's date, account or scope.

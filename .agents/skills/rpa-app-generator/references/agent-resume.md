# Agent-directed resume

Use this workflow when the user wants the agent to diagnose and continue a failed RPA application.

1. Read the application's requirement.md and source, then its failed runs/<run_id>/result.json and events.jsonl. Identify the failure, completed outputs, original inputs, account, mode and download directory. Keep private run data out of tracked files.
2. Inspect and fix the actual cause. Run focused offline tests when code changes. Use the user's existing authorization for real browser access and continuing the named program; do not request the same permission again.
3. Inspect the retained browser and confirm the account and page state. BrowserManager records failed-browser handoffs under runtime/browser-manager/handoffs and adopts that browser for a later command. Use the core BrowserActions boundary for page operations.
4. Prepare the page and files required by the chosen step. If the browser or session is gone, choose an earlier navigation/login step or restore the page before continuing.
5. Select --from-step explicitly. The selected step runs again, followed by all later steps. The prefix must already have successful results in the source record; the framework does not silently mark an unfinished step complete.
6. Run the command from the application directory:

    uv run rpa-app resume <run_id> --from-step <step_id>

The command uses the source account, mode, inputs and download directory, while loading credentials from local configuration. It keeps downloaded files and creates a new attempt record with resumed_from and from_step. The original failed record remains unchanged.

Jingmai example: if export generation succeeded and S006 failed, prepare the download list and resume at S006. The old export dialog need not remain visible, the original target date remains fixed, and S004 does not run again.

Jushuitan example: if filtering succeeded and S005 failed, prepare the inventory page and resume at S005. The original brand remains fixed even if the current local configuration changed.

Each executed step still verifies its result. If resumption fails, inspect the new failed record before selecting another attempt. A new run intentionally starts from the beginning and clears downloads; do not use it as a substitute for requested continuation.

Records from older versions without saved inputs cannot be resumed by this command. Do not invent missing business parameters or silently change the task's date, account or scope.

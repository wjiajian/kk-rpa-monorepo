# Validation

During implementation, run offline checks for the changed behavior:

- validate app.toml identity, requirement.md presence and elements.toml parsing through the shared CLI;
- run rpa-app test, which executes each Step's normal scenario and counterexamples before application pytest;
- check relevant business order, page readbacks, failed outcomes, a fresh run after failure, and agent-selected resume with saved business inputs;
- run the affected core tests when core interfaces or behavior change;
- verify lock/environment consistency and git diff --check.

Unexpected execute exceptions and errors inside verify fail the test harness. Expected action errors alone cannot prove a verifier; each Step must also reject an incorrect result after successful execution.

doctor only checks local prerequisites and configuration. run, resume and verify-elements use a real browser. In Jingmai, element validation also creates an export task and downloads a report. Apply the user's existing authorization to these operations; a request to resume a named failed program authorizes continuing that program's known scope. Clarify scope only when the intended external operation is not clear.

Use resume <run_id> --from-step <step_id> for continuation. Do not invoke old --yes or --live options. Production unattended operation does not itself authorize an agent's development-time access.

Fix failures caused by the current change, then repeat the affected checks. Report framework/offline application results separately from real element verification, real runs and business acceptance. Mark real validation awaiting authorization when it was not performed; do not claim historical runs validate new code.

Do not commit, push or deploy unless explicitly authorized.

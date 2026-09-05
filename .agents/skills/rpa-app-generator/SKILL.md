---
name: rpa-app-generator
description: Generate or update one independent kk-rpa-monorepo RPA application from a Feishu requirement document using the shared V2 CLI, application-local elements, falsifiable Steps, offline tests, and explicit real-browser gates. Use only inside this repository.
---

# RPA App Generator

Generate one auditable application for one requirement document using the repository's fixed `BrowserActions` / `Element` / `Step` structure.

## Required context

1. Read the repository `AGENTS.md` and `docs/rpa-framework-design.md`.
2. Inspect `git status --short`, the current branch and HEAD. Preserve all existing work.
3. Scan `apps/*/app.toml` and the proposed target directory before creating anything.
4. Treat a matching application as an existing-application change. Inspect its current requirement hash and preserve human changes.

## Workflow

1. For Feishu retrieval, revision pinning, screenshot mapping and redaction, read [references/requirement-ingestion.md](references/requirement-ingestion.md).
2. For the independent application structure and generation order, read [references/application-generation.md](references/application-generation.md).
3. Before validation or a real-browser handoff, read [references/validation-gates.md](references/validation-gates.md).

Generate the complete business flow even when details are missing. Represent uncertainty as a pending confirmation or unresolved element in `requirement.md`; keep its `elements.toml` locator absent. Never invent selectors, silently omit a step, or scatter TODO comments.

Do not create an Instruction layer, catalog snapshot, platform package or top-level element source for a new application. Python functions are the instruction mechanism. Promote shared code only after a third application proves the same behavior is actually repeated.

## Authorization boundary

Initial generation ends after side-effect-free checks. Do not open a real browser, log in, inspect private pages, click, query, download business data, write externally, commit, push or deploy unless the developer separately authorizes the exact next stage.

Stop immediately on an identity conflict, revision mismatch, sensitive-content finding, failed offline test, or need for a new public `rpa-core` interface.

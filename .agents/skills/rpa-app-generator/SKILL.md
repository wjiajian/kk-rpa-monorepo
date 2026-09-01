---
name: rpa-app-generator
description: Generate or incrementally update one independent kk-rpa-monorepo RPA application from a Feishu requirement document, including requirement memory, V2 spec, catalog snapshots, candidate capabilities, offline tests, and authorization gates. Use only inside this repository; real browser validation and external writes remain separately authorized.
---

# RPA App Generator

Generate one auditable application for one requirement document while preserving the repository's authorization boundaries.

## Required context

1. Read the repository `AGENTS.md` and the current implementation proposal.
2. Inspect `git status --short`, the current branch and HEAD. Preserve all existing work.
3. Scan `apps/*/app.toml` and the proposed target directory before creating anything.
4. Treat a matching application as an existing-application change. Stop before edits until its read-only change proposal is approved.

## Workflow

1. For Feishu retrieval, revision pinning, screenshot mapping and redaction, read [references/requirement-ingestion.md](references/requirement-ingestion.md).
2. For verified catalog selection, dependency closure and candidates, read [references/catalog-selection.md](references/catalog-selection.md).
3. For the independent application structure and generation order, read [references/application-generation.md](references/application-generation.md).
4. Before any command or handoff, read [references/validation-gates.md](references/validation-gates.md).

Generate the complete business flow even when details are missing. Represent uncertainty as `PendingConfirmation`, `UnresolvedElement`, or `UnresolvedInstruction`; never invent selectors, silently omit a step, or scatter untracked TODO comments.

## Authorization boundary

Initial generation ends after side-effect-free checks. Do not open a real browser, log in, inspect private pages, click, query, download business data, write externally, commit, push, deploy, or promote candidates unless the developer separately authorizes the exact next stage.

Stop immediately on an identity conflict, revision mismatch, Memory/Spec drift, catalog integrity failure, sensitive-content finding, failed offline test, or need for a new public interface.

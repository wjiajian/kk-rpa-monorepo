---
name: rpa-app-generator
description: Generate or update one independent kk-rpa-monorepo RPA application from a Feishu requirement document using the shared CLI, application-local elements, sequential Steps, normal and failing scenarios, and offline validation. Also guide agent-directed continuation of a failed application. Use only inside this repository.
---

# RPA App Generator

One requirement produces one application. Keep the fixed BrowserActions / Element / Step structure and follow the repository AGENTS.md and docs/rpa-framework-design.md.

Before generation, inspect the existing application identities and working changes. Update the matching application for later requirement revisions and preserve unrelated work.

- To read a Feishu source and handle screenshots, use [requirement ingestion](references/requirement-ingestion.md).
- To generate or update code, use [application generation](references/application-generation.md).
- To validate and report results, use [validation](references/validation-gates.md).
- To diagnose and continue a failed run, use [agent resume](references/agent-resume.md).

Write the complete business flow. Keep uncertain details in requirement.md and leave unverified locators absent in elements.toml.

Use the current rpa_core interfaces. Do not generate requirement hashes, catalog snapshots, an Instruction registry, one-shot authorization records, old automatic checkpoint recovery or compatibility wrappers. Use the shared resume command for agent-selected continuation. Defer shared business abstractions until a third actual application demonstrates repetition.

Production runs are unattended. Agent development actions against real browsers and external systems still require user authorization for their scope; existing authorization remains valid. Complete authorized implementation and offline fixes without introducing another approval step.

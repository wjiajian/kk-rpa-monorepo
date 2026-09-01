# Requirement ingestion

Use the Feishu document as the business-facing source; do not ask the requester to convert it to JSON or YAML.

## Read and pin

1. Use the default Feishu user identity and verify authentication without exposing tokens.
2. Fetch the latest revision first. Compare it with any approved implementation baseline.
3. If the revision changed, stop and produce `REQUIREMENT_CHANGE_PROPOSAL.md`; do not change the accepted requirement or code.
4. Fetch the pinned revision with block identifiers so text and media remain traceable.

## Sanitize immediately

- Replace accounts, passwords, phone numbers, emails, people, stores and brands with stable aliases such as `STORE_001`, `ACCOUNT_PROVIDER_001` and `BRAND_001`.
- Persist only a redacted document URL, a one-way source fingerprint and the revision. Do not persist the real document token.
- Put credentials only in ignored local `.env` data, and business selections only in ignored `stores.local.toml`.
- Never copy real values into source, tests, fixtures, events, checkpoints, reports or examples.

## Screenshots

Download step screenshots to ignored `requirement/assets/` paths. Give each file a step-oriented name, record its source block identifier or one-way source fingerprint and SHA-256 in `REQUIREMENT_MEMORY.md`, and map it to one or more stable step IDs.

Screenshots establish business intent and approximate page position only. They are not evidence for CSS, XPath, coordinates or uniqueness. If the DOM has not been inspected under an explicit authorization, create unresolved candidate elements without locators.

## Extract

Capture ordered steps, inputs, outputs, success conditions, conditions, loops, retries, recovery, side effects, execution schedule and destination rules. Blank output-template fields are not automatically blockers when the prose explicitly says that destination is unused.

Write the readable Memory first. Generate the canonical JSON Spec from the Memory and compute the requirement hash with `rpa_core.requirements.compute_requirement_hash`.

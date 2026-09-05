# Requirement ingestion

Read the Feishu document through the available document skill or connector. Keep the accepted source revision and a readable requirement.md; no canonical TOML block or computed requirement hash is needed.

For an existing application, compare a changed source revision with its accepted baseline and apply the user's requested scope. Clarify only ambiguities that change the business behavior.

Capture the ordered business actions, account and filter inputs, actual success conditions, output destination, scheduling information, and unresolved details. Record retries or repeated runs only when the business requirement calls for them.

Use stable aliases in tracked files. Credentials and real account-specific values belong in ignored local configuration. Keep existing sanitized source identifiers; do not expose real document tokens or account details.

Download requirement screenshots to ignored requirement/assets paths when needed. Map the image and its source to the relevant Step in requirement.md. Screenshots explain intent and approximate position; they do not prove a DOM locator or its matching count.

Leave unknown locators unresolved and continue writing the complete flow. Unused destination fields in the source are not automatically blockers when the requirement explicitly excludes that destination.

For the two current export applications, success means the configured account and report conditions match and a nonempty file is successfully downloaded. Do not add workbook-content reconciliation or write-recovery requirements that the user has excluded.

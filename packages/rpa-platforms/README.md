# rpa-platforms

Compatibility placeholder only. It is no longer the source of shared elements or platform instructions.

- Verified element sources live in repository-level `elements/`.
- Verified Python instruction sources live in repository-level `instructions/`.
- Generated applications copy only their dependency closure into the application package and pin it with `catalog.lock.json`.
- DrissionPage adapters remain behind `rpa-core` BrowserActions.

Do not add new element or instruction definitions here. The directory is retained so existing references can be migrated explicitly instead of being broken by deletion.

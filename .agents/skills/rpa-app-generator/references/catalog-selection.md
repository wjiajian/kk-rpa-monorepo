# Catalog selection

Applications run only from their package-local element and instruction snapshot.

## Verified items

1. Discover top-level `elements/` and `instructions/` using the public `rpa_core.catalog` APIs.
2. Select by stable capability and platform identity, not by filename resemblance alone.
3. Snapshot the complete dependency closure. Never overwrite an existing target or lock.
4. Verify the resulting `catalog.lock.json` and copied hashes before testing.

## Missing items

When no verified item matches, create an application candidate:

- element: stable ID, page/component metadata and `locator = None` in Python;
- instruction: metadata, an `Instruction` implementation using only `ExecutionContext` services, and a focused Fake Browser test;
- lock item: `status = "candidate"`, `source_type = "application_candidate"`, application-relative source/target path, content hash and dependencies;
- requirement: linked `UE-*` and `UI-*` records with candidate state and explicit real-run/review/push blockers.

Candidate instructions may consume candidate elements in Fake tests. They must not import DrissionPage or root catalog packages, own checkpoints, contain real business identities, or claim real-page evidence.

Keep candidates in the application after Fake tests. Promotion to the top-level catalogs requires authorized real verification, Preview evidence, a separate proposed diff and affected-application regression.

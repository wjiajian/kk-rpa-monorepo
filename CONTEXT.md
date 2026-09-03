# RPA Application Generation

This context turns one business requirement into one independently testable, reviewable, recoverable, and runnable RPA Application.

## Language

**Requirement Source**:
The authoritative business request and its revision from which an RPA Application is derived.
_Avoid_: Input document, original file

**Requirement Memory**:
The developer-readable requirement baseline and the only requirement representation developers edit directly.
_Avoid_: Requirements notes, design document

**Requirement Spec**:
The machine-readable representation generated from, and semantically identical to, the Requirement Memory.
_Avoid_: Configuration, generated requirements

**RPA Application**:
The independent delivery unit associated with exactly one Requirement Source and one stable Application ID.
_Avoid_: Script, bot, job

**Program**:
The complete ordered business flow executed by an RPA Application.
_Avoid_: Workflow file, main script

**Step**:
A unit of business progress whose success can be retried, verified, checkpointed, and recovered independently within a Program.
_Avoid_: Instruction, action

**Instruction**:
A reusable, independently verifiable platform capability composed by a Step.
_Avoid_: Step, helper function

**Element**:
A stable identity for a UI target, independent of any live browser object.
_Avoid_: DOM node, selector

**Catalog Snapshot**:
The frozen set of Elements and Instructions owned by one RPA Application for reproducible execution.
_Avoid_: Shared catalog, runtime catalog

**Candidate Asset**:
An application-owned Element or Instruction that has offline evidence but has not completed real verification.
_Avoid_: Verified Asset, shared Asset

**Authorization Record**:
An auditable lifecycle record for requesting, granting, claiming, and completing exactly one bounded real-system invocation.
_Avoid_: Batch constant, approval flag

**Authorization Scope**:
The exact Application, Version, Requirement Hash, Command, Mode, Run ID, Account, Profile fingerprint, Site, Steps, Actions, Targets, Data Scope, and—when resuming—Checkpoint digest and recovery Step an Authorization Record permits.
_Avoid_: General permission, unrestricted access

**Authorization Claim**:
The single attempt to consume an Authorization Record for one matching invocation.
_Avoid_: Authorization check, reusable token

**External Write Authorization**:
An exact write scope inside a separately granted Live Authorization Record, claimed again at its external adapter boundary.
_Avoid_: Live mode flag, unrestricted write permission

**Read-back Verification**:
An independent query after an External Write that must reproduce the authorized Record Count and canonical Payload Digest before the write can be called successful.
_Avoid_: Write API response, assumed success

**Preview Run**:
An authorized real-system run in which reads and downloads may occur while external business writes are redirected to local previews.
_Avoid_: Dry run, test run

**Live Run**:
An authorized real-system run that may perform only the explicitly granted external business writes.
_Avoid_: Production mode, unrestricted run

**Review Record**:
An immutable developer decision tied to one Application Version, Requirement Hash, and tested run scope.
_Avoid_: Approval flag, status note

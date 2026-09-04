# RPA Application Generation

This context turns one business requirement into one independently testable, recoverable, and runnable RPA Application.

## Language

**Requirement Source**:
The authoritative business request and its revision from which an RPA Application is derived.
_Avoid_: Input document, original file

**Requirement**:
The single requirement baseline that developers read and edit directly, and that the agent reads to generate the Program.
_Avoid_: Requirement Memory, Requirement Spec, requirements notes

**RPA Application**:
The independent delivery unit associated with exactly one Requirement Source and one stable Application ID.
_Avoid_: Script, bot, job

**Program**:
The complete ordered business flow executed by an RPA Application.
_Avoid_: Workflow file, main script

**Step**:
A unit of business progress that can be independently executed, verified, retried, checkpointed, and recovered.
_Avoid_: Instruction, action

**Element**:
A stable identity for a UI target, carrying a locator and the match count expected to hold right now.
_Avoid_: DOM node, selector, verified asset

**Expected Count**:
The match count an Element must currently produce, asserted by `verify-elements`.
_Avoid_: Verification record, historical match count

**Counterexample**:
A fake browser state under which a Step must fail, supplied by the Step itself and enforced by the offline test suite.
_Avoid_: Negative test, edge case

**Falsifiable Assertion**:
A `verify()` that at least one Counterexample can drive to `False`. An assertion no Counterexample can falsify is not an assertion.
_Avoid_: Success condition string, declared outcome

**Fake Executor**:
An `execute()` that echoes its inputs instead of reading back page state — the defect Counterexamples exist to catch.
_Avoid_: Stub, placeholder

**Read-only Account**:
A platform-side account restricted to query and export permissions. The only boundary that holds when the code itself is wrong.
_Avoid_: Authorization scope, permission flag

**Preview Run**:
A real-system run in which reads and downloads may occur while external business writes are redirected to local previews.
_Avoid_: Dry run, test run

**Live Run**:
A run explicitly confirmed with `--live` that may perform its declared external business writes.
_Avoid_: Production mode, unrestricted run

**Read-back Verification**:
An independent query after an external write that must reproduce the expected record count and payload digest before the write counts as successful.
_Avoid_: Write API response, assumed success

**Evidence**:
Redacted logs, screenshots, and artifacts written under the run directory that support a run's conclusion.
_Avoid_: Generation report, review record

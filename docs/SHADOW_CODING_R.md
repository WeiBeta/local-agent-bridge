# Shadow PPTX coding validation

LAB-SHADOW-CODING-LIVE-INTEGRATE-01 extends frozen base
5d5842d009d883fff08f27c25683974d10d7d2e7 with task-specific source-only integration.
Product src, first_task_r.py, original SELECT inputs/recipes, production and
configuration are unchanged. Fresh independent Review and a new concentrated real
approval remain required. Offline checks do not establish installed CLI compatibility.

## Input and test matrix

Historical capsule e99a4fcc-6212-4278-8cd8-818c48590280 contributes only PPTX
package reading and finite slide-number selection. The new Worker input is exactly
tool.py, recipe/run_tests.py, recipe/public_tests.py and recipe/shadow_worker_tests.py.
Only work/tool.py is editable. Freeze a new four-file manifest; preserve the old
SELECT three-file archive. Private tests and reference answers stay on the
acceptance side and never enter Worker input.

| Caller / phase | Tests | Failures | Errors | Actual child exit |
| --- | ---: | ---: | ---: | ---: |
| Worker reproduce / management baseline_public | 8 | 0 | 4 | 1 |
| Worker regression / management candidate_public | 8 | 0 | 0 | 0 |
| Management candidate_private | 2 | 0 | 0 | 0 |

The protected wrapper calls the unchanged public recipe with pinned Python,
-I -B, absolute paths and ten-second child timeout. It verifies all eight case IDs,
counts, source files/tree and recipe/interpreter identity before/after execution.
Child console output is discarded so source output cannot masquerade as the one
bounded summary. Actual child exit stays in that summary. Wrapper exit zero means
a well-formed report was produced, including the expected failing baseline.
Regression requires prior reproduction output. A failed/completed phase directory
stays reserved. Changed inputs, missing XML, timeout or other error stop without
a success summary; partial evidence remains.

## Task-side lifecycle and authority

shadow_coding_live.py owns this task's strict v3 permit/context checks for the real
8/8 counts. It does not call the old 1/6 validator or monkeypatch its globals.
It reuses environment/root and installation checks, exclusive consumed marker,
first-execution record, product _execute_once, collector and saved lifecycle checks.
Configuration lease, restoration and owned job cleanup remain product operations.

The unchanged v3 permit's budget_ref pins an external ShadowCodingContract. This
freezes four input files, all six verification-code identities, a separate private
acceptance recipe root and exact budget. The acceptance recipe contains exactly
the original runner/public/private tests with original byte hashes, outside task,
result, run, appdata and installation roots. Public recipe identity remains under
protected work/recipe. Only LayeredAcceptanceUnverified can be waived for this
one execution; other blockers stop before consumption. Existing runtime/layered
acceptances remain empty. This validator records evidence, never product acceptance.

Proposed budget: one host launch, two Worker public runs, two management public runs
and one management private run. Host deadline is 300 seconds; each test child has
ten seconds. Capture creation loads its key once; the separate stdout reader loads
once and authenticates stdout once. Engineering must freeze native backend
credential-read bounds and real runtime/host/config/route identities before approval.
No fallback, second job or automatic retry.

Launch facts retain 0, 1 or null. Original failures/interrupts are saved before
fallible collection, diagnostics and environment restoration. Secondary failures
cannot replace KeyboardInterrupt/SystemExit. Failed outputs and consumed markers
remain reserved; there is no automatic cleanup.

## Native CLI evidence

The [official headless documentation](https://antigravity.google/docs/cli/headless/#tool-calls-in-the-stream),
checked on 2026-10-11, documents completed tool events with conversation/step ID,
tool name, command parameters, output and failure information. It does not verify
the installed binary or OS-observed child argv/shell/numeric exit. Numeric child
exit here comes from the protected wrapper's real subprocess return carried in
native tool output.

shadow_worker_results.py accepts only the two exact frozen PowerShell command
strings, completed run_command events, one conversation and one successful terminal
event, ordered reproduction then regression. The summary must match input/candidate
trees, recipe, Python, full case set, actual exits and collected XML hashes.
Collected summary files must also match. Model final response never supplies
missing tool results. Missing, duplicate, conflicting, incomplete, truncated or
oversized evidence yields Unknown.

Bounds reuse the existing reader: 256 KiB stream/file, 64 KiB line, 1024 lines,
256 steps and strict JSON depth/node/container limits. Sealed-stdout authentication
uses this invocation's isolated appdata and checked lifecycle UID; stdout is
authenticated once, plaintext/key stay in memory, and only scoped hashes/counts
are persisted. Attempt consumption precedes key access. No memory zeroization
or OS attestation is claimed.

CliPublicTestsMatch has origin CliToolResult, a task-specific predicate. Product
worker_execution stays Unknown, shell identity remains unknown, runtime acceptance
is Unverified and accepted is false. Management combines these facts with its own
retests and decides the scoped task outcome. DONE, top-level success, hashes or
Worker-written XML alone cannot establish the predicate.

## Management and saved checks

shadow_coding_r.py preserves exact three-file behavior for original callers.
A live caller supplies the wrapper hash after checking the new pinned contract,
enabling an exact four-file inventory. Each management stage copies source and the
separate recipe, invokes original tests, rechecks inputs and records actual exit,
counts, named XML, layered command bindings and source/recipe/Python identities.

Console/process errors retain the original exception before fallible closure;
a secondary closure type may be recorded. Without an earlier error, a close
failure fails the phase. Remaining stages stop and partial files remain reserved.
HostObserved here describes only management's own subprocess return and checked
local files in the declared same-user boundary, without an OS sandbox.

The live validator persists shadow-validation.json. Saved reread requires an
externally frozen observation SHA and checks first-execution/run/collection/controls,
candidate source, management facts and retained CLI evidence hashes. It reloads
frozen controls, permitting the legitimately changed collected candidate.
It never consumes another permit, launches a process or accesses a key.

After binding and real approval, invoke the bound installation Python with -I -B,
the frozen shadow_coding_live.py path, --permit and --permit-sha256. Saved reread
also requires --saved --observation-sha256. Real values remain null in the draft
packet until engineering binds them. Luna verifies supplied hashes and executes
the bound run_once.ps1 once; it does not construct fields, diagnose, retry or accept.
The script rejects an unbound draft before invoking Python. The old standalone
shadow_coding_r.py entry remains stop-only for compatibility.

## Offline checks and next gate

Task tests live in verification/tests, outside the shipped tests inventory.
Invoke all four test_shadow_*.py modules explicitly alongside applicable product
tests, in the locked/copy environment with task-owned --basetemp and JUnit XML.
Ordinary tests use synthetic host/config/session keys. Real local Python checks
run the unchanged public recipe on synthetic task copies and a reference feasibility
witness; these are self-checks, not independent Review or real Worker acceptance.

The task archive records source identities, exact counts, retained failures,
the four-file manifest, fixed broker draft and unresolved real bindings. Management
arranges fresh integration Review, then one concentrated real authorization.
No OS tracing framework, production refresh, Skill/config change, provider switch
or paid probe is added.

# Shadow PPTX coding validation

LAB-SHADOW-CODING-LIVE-REPAIR-01 repairs LIVE-F01 and LIVE-F02 at frozen base
98abad40d4b8526a3da45db0d7c8c1e827f3e872. Each defect is in its first repair round.
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
Each summary also binds every case ID to its pass/error/failure state. The four
baseline errors must be exactly default_range_has_numeric_source_order,
repeatable_json_bytes, sparse_inclusive_filter and valid_archive_and_input_digest
(each with the public_tests.PublicPackageTests.test_ prefix). Every other baseline
case and all regression cases must pass. Totals and the case-name set alone do
not satisfy this check. Collected XML, native summary, initial validation and saved
reread enforce the same states; management public XML is checked independently.
Child console output is discarded so source output cannot masquerade as the one
bounded summary. Actual child exit stays in that summary. Wrapper exit zero means
a well-formed report was produced, including the expected failing baseline.
Regression requires prior reproduction output. A failed/completed phase directory
stays reserved. Changed inputs, missing XML, timeout or other error stop without
a success summary; partial evidence remains.

The current WP05 matrix, as adjudicated by management on 2026-10-11, requires UTC
start/end, an actual ten-second subprocess timeout and command/source/recipe/XML
bindings carried in the CLI tool result. Child stdout/stderr use DEVNULL. Child
console diagnostics and console identity are unavailable, and no monotonic fields
are added. This is an explicit adjustment to historical preparation WP05, not a
claim that all of its original requirements passed. WP07's historical "8/0 errors"
baseline sentence is corrected here to SELECT's eight cases/four named errors;
the historical preparation archive remains unchanged.

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
and one management private run. New contract templates use a 3600-second work budget;
an explicit integer 1..3600 is valid only when Task, permit and contract budget agree.
The former 300-second budget remains a valid shorter value, without changing any
historical or consumed packet. All other budget fields stay fixed; each test child has
ten seconds. Capture creation loads its key once; the separate stdout reader loads
once and authenticates stdout once. Engineering must freeze native backend
credential-read bounds and real runtime/host/config/route identities before approval.

Task work uses the remainder from validator entry. Antigravity's internal minute
limit rounds that remainder up; the outer wait enforces the precise remainder.
New native minute values are not live-verified. Recovery kill/join remain 30 seconds
each, and prepare/collect/saved-collection retain their separate stage deadlines.
Normal process exit continues immediately to cleanup and terminal evidence; there
is no full-hour wait or callback timer. 3600 is not the whole broker/tool wall limit.
The standalone legacy slice keeps 1020 seconds and its fixed 15m CLI limit.
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

An ACTIVE run_command is not final command evidence. Its parameters may be updated
by a later event while conversation step/tool identity remains stable; exact
command, phase and summary binding are enforced only on DONE. A truncated ACTIVE
preview does not authorize a run, and a truncated or reconstructed DONE command
remains Unknown.

A task may explicitly select worker_provenance version 1 with basis
FinalToolSummaryAndArtifacts. This separate predicate uses the two completed
run_command wrapper summaries in one conversation—each strictly bound to phase,
inner argv/cwd, source tree, protected recipe and Python, full case outcomes,
exit and report hash—together with the existing collected summaries, candidate
tree and management retests. It returns CliBoundPublicResults and records each
outer CommandLine literal as exact/prefix/prefix_ellipsis/different; that literal
diagnostic is not sufficient and does not claim OS argv observation. The default
absence of worker_provenance keeps the older OuterCommandExact/
CliPublicTestsMatch contract unchanged, with no silent fallback between modes.

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

Use the new repair packet; preserve the historical integration packet. Its broker
script rejects an occupied run_root before consuming a broker attempt or invoking
Python. A returned observation must be newly created in the previously vacant
root and bind this task ID and permit SHA, observation kind/version, count domain
and unaccepted evidence state before its facts can enter a receipt. Missing,
malformed or mismatched observation yields Unknown/null, with the actual outer
exit and invocation_started recorded separately. Preflight rejection cannot borrow
Ready/1 from an earlier run. All receipt/attempt writes are exclusive; a later
entry neither executes again nor overwrites the earlier receipt. These checks are
within the existing same-user boundary, without OS isolation claims.

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

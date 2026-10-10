# Shadow PPTX package retest component

Task: LAB-SHADOW-CODING-ADAPT-01. Frozen base:
`225ee6d98cedc5db30ffea1fd9d1c8445540400a`. This source-only candidate adds
`verification/shadow_coding_r.py` and synthetic tests. It does not change the
product, the existing `first_task_r.py`, the wheel, installation or Task schema.
It is **NotExecutionReady**; no real execution authority is supplied here.

Task-only tests live at `verification/tests/test_shadow_coding_r.py`, outside
the frozen shipped `tests/` inventory. They are not shipped in the current wheel
or sdist and must be invoked explicitly alongside the applicable product tests:

```powershell
uv run --no-sync python -B -m pytest verification/tests/test_shadow_coding_r.py tests/test_distribution.py --basetemp '<task-owned-scratch>/final-tests'
```

Use the project-local locked environment with its frozen product distribution
installed; this command does not run a Worker or change runtime acceptance.

## Fixed task matrix

The selected historical Shadow capsule is
`e99a4fcc-6212-4278-8cd8-818c48590280`. Only its PPTX package-reading and finite
slide-number selection slice is in scope. `tool.py` is the only editable source;
`recipe/run_tests.py` and `recipe/public_tests.py` stay byte-frozen. The original
tests are not padded, renamed or changed to match an executor.

| Management subprocess | Suite | Tests | Failures | Errors | Exit |
| --- | --- | ---: | ---: | ---: | ---: |
| baseline_public | public | 8 | 0 | 4 | 1 |
| candidate_public | public | 8 | 0 | 0 | 0 |
| candidate_private | private | 2 | 0 | 0 | 0 |

Each command has a 10-second timeout and uses pinned Python with `-I -B`, an
absolute acceptance recipe, `--source`, `--out` and `--suite`. The output report
is `<stage>/out/tests.xml`. The helper checks the exact eight public or two
private case IDs as well as aggregate counts, skips and individual error/failure
nodes. Public and private results remain separate.

The baseline tool hash is
`fdecaccf115229e86c834dcaa30e533bf0bc2869625c02009da49d1a9e9285cd`.
Recipe and test hashes are pinned in the component from SELECT-01. Acceptance
uses an isolated recipe directory containing exactly `run_tests.py`,
`public_tests.py` and `private_tests.py`. No reference answer, private test,
management helper or acceptance directory may enter Worker input.

## Existing lifecycle and trusted caller boundary

The current `first_task_r.py` binds one consumed permit, installation, trusted
inputs, configuration lease, `_execute_once`, saved run/launch, collection,
restoration and owned cleanup. Keep that lifecycle. This component does not
invoke or replace it. Its live `main()` always returns exit 2 with
`Blocked/WorkerTestEvidenceInterfaceUnverified`, launch_count 0, before any
permit consumption, configuration IO, capture/key access or subprocess.

The retest functions are management-side library functions, not an authorization
API. In a future separately reviewed integration, the trusted caller must first
check the existing saved run and collection gates, then call:

```python
identities = run_manager_retests(
    context=checked_context,
    roots=checked_roots,
    collection=checked_collection,
    recipe_root=frozen_acceptance_recipe_root,
)
summary = read_manager_evidence(
    identities=identities,
    context=checked_context,
    roots=checked_roots,
    collection=checked_collection,
    recipe_root=frozen_acceptance_recipe_root,
)
```

The existing roots are `task_root`, `result_root` and `manager_retest`; baseline
is `task_root/control/snapshot/source` and candidate is `result_root/candidate`.
The caller provides the Task and deployment receipt through the existing context,
with one Python identity and recipe ref `shadow_pptx_package_v1`. It must freeze
these real bindings and acceptance-recipe identities as trusted inputs, include
their read scope and the three retest commands in authorization, and retain the
returned identities as management evidence. The helper accepts no authority
merely from a caller-supplied `origin` field.

The helper reserves a fresh output root once, copies each source and recipe to
management-only stages, and rechecks all inputs before and after each process.
It records existing layered `COMMAND_KEYS`, original exit/counts and report
identity, stdout/stderr, and a binding of Task, receipt, collection, source trees,
recipe, interpreter and roots. Saved reread repeats these checks and validates
argv/cwd, actor, times, named reports and retained source/recipe bytes. Rehashing
a changed command or report identity does not waive these bindings. Diagnostic
failure cannot replace the original interrupt. Stream acquisition/process errors
are saved before fallible console closure; the last observed secondary close
error's type is retained as `console_cleanup_exception_type` when possible.
Without an earlier operation error, a console close error still fails the phase.
A failure leaves partial output reserved and stops the remaining commands.
There is no retry or cleanup.

These facts describe the management subprocesses. `ManagementRetestsPass`
does not establish Worker execution, strict R, product acceptance or deployment.
`HostObserved` here refers only to this caller's subprocess return and checked
local files; candidate code runs within the already declared same-user boundary,
without an OS sandbox or independent audit. Retained console files are diagnostic
material, not the test oracle or a native Worker result.

## Concrete remaining blocker

In the frozen source, `agy_stdout_reanalysis.py` recognizes
`step_update.tool_info.parameters.CommandLine`. Optional `tool_info.exit_code`
is a synthetic-covered extension, not an officially verified native interface.
Its origin remains `CliDeclared`; `DONE` and top-level success do not prove that
the protected test recipe ran against the required source version. See
[the existing evidence boundary](AGY_LIVE_ADAPTER.md).

There is no verified producer in this frozen candidate that links native Worker
test results to the baseline-before-edit and final-candidate source bytes,
protected recipe/test identities, invocation and eight named outcomes. Worker
XML or a model's statement can be `WorkerReported`; neither becomes OS observed
because it has a hash. Native tool results, if later verified, must retain their
own CLI provenance separately from optional OS facts. Missing facts stay Unknown.

The smallest next engineering step is to establish one bounded native result
schema and its source/recipe/result linkage using existing capture/collection,
then independently review the task-specific lifecycle integration and Worker
result predicate. Do not add general OS tracing, guess a schema, weaken positive
Worker-test acceptance or modify product source under this work order. If that
linkage cannot be established, report code delivery and management regression
separately while Worker execution remains Unknown and the task stays open.

## Luna fixed steps and stop conditions

1. Verify the supplied packet and script identities. Only the stop-only
   `broker_preflight.ps1` in this task's execution packet is executable now.
2. Run that exact preflight once. Expected terminal result is exit 2,
   `Blocked/WorkerTestEvidenceInterfaceUnverified`, launch_count 0. Relay the
   retained result reference once and stop.
3. Any identity/path mismatch, unexpected exit/result or missing script: stop
   and relay the fixed failure reference; do not retry, repair or fill fields.
4. Do not run a host/model, alter configuration, read keys/decrypt, call the old
   1/6 helper, or write a launch script. A future real launch requires a new sealed
   package after independent Review and management's concentrated real approval.

Real route, host/config, Task/snapshot/profile/authorization/receipt/bundle/plan,
new single-use permit, capture scope and Worker result interface remain unbound.
The reference-only offline feasibility check is not a Worker candidate or an
independent Review. Luna only executes supplied steps and relays references;
engineering binds and diagnoses, management decides acceptance.

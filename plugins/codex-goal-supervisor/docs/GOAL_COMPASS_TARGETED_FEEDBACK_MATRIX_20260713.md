# Goal Compass Targeted Feedback Matrix

Date: 2026-07-13

## Purpose

This pass generated isolated projects and exercised the installed Goal Compass
CLI instead of relying only on internal function tests. The scenarios were
derived from four long-running project reviews that reported process tax,
incorrect state attribution, lexical false positives, repeated validation,
receipt ceremony, stale phase state, and syntactic-only quality checks.

The matrix lives in:

```text
verification/scenarios/run_feedback_matrix.py
```

It is verification-only and is not copied into user projects by the installer.

## Projects Generated

| Project | Targeted feedback | Result after fix |
|---|---|---|
| `quant-runtime-sqlite` | live non-empty SQLite mistaken for a product edit | PASS |
| `parser-complete-word` | ordinary `complete` verb mistaken for heavy scope | PASS |
| `packaging-negative-semantics` | CSS negative state and negative assertions mistaken for scope conflict | PASS |
| `registry-validation-cache` | `close` repeats unchanged passing validation | PASS |
| `medical-upstream-evidence` | changed premise mislabeled as DRIFT | PASS |
| `bilingual-request-routing` | equivalent Chinese and English requests route differently | PASS |
| `video-artifact-quality` | file existence mistaken for usable artifact quality | PASS |
| `company-phase-lifecycle` | duplicate role ceremony and stale program phase | PASS |
| `foundation-nongit-line-delta` | one-line edit charged as an entire large file | PASS |
| `supply-chain-aggregate-preflight` | blockers exposed one recovery ticket at a time | PASS |
| `compact-supervision-output` | protocol output obscures the operational result | PASS |
| `packaging-change-request-routing` | new aligned work mutates frozen current acceptance | PASS |

All 12 projects completed in under 10 seconds on the final source tree.

## Problems Reproduced Before The Fix

### 1. Non-empty SQLite runtime churn became DRIFT

An initialized and actively written `var/runtime.sqlite` was classified as:

```text
DRIFT: outside writable_paths changed
```

The earlier implementation only recognized an empty SQLite file implicitly.
The fix treats `.sqlite`, `.sqlite3`, and `.db` as runtime state by default,
while preserving explicit ticket contracts in this priority order:

```text
immutable -> explicit runtime -> writable -> read dependency -> implicit runtime
```

This means a ticket can still deliberately produce a database fixture by
placing it in `writable_paths`; otherwise service database churn does not consume
the product diff budget.

### 2. `complete` was still a false heavy-scope signal

The task:

```text
Complete the missing unit test assertion for parser output.
Do not build a platform or framework.
```

produced `complete`, `platform`, and `framework` warnings and a strong
scope-sink signal. The fix routes compile, MDCP time/scope signals, company role
shaping, and goal matching through contextual heavy-scope filtering. A broad
modifier is only heavy when paired with an actual heavy design such as RBAC,
marketplace, security gateway, ERP, MES, or another explicit expansion. Negated
scope remains excluded.

### 3. Equivalent Chinese mutation request was rejected

English `Review and fix the current parser validation behavior` mapped to the
current acceptance, while Chinese `检查并修复当前解析器验证行为` was rejected. The
operation was already correctly recognized as an edit; the mismatch was in
cross-language current-scope mapping. The deterministic normalization now
covers common engineering concepts such as parser, validation behavior, result,
output, error, status, service, data, upstream evidence, coverage, and
regression. Both requests now produce the same bounded verdict.

## Feedback That Did Not Reproduce On The Final Source

- CSS `.negative` and negative test assertions were not classified as noise or
  scope violations.
- `check --run-validation` followed by unchanged `close` executed validation
  once and reused the passing input fingerprint.
- Changed read dependencies returned `UPSTREAM_EVIDENCE_INVALID`, not DRIFT.
- Declared artifact quality required evidence; an existing MP4 alone did not
  pass.
- One `COMPLETED` company result automatically supplied its STARTED event, and a
  passing phase-bound ticket completed the phase during the same close.
- A one-line edit in an 1,800-line non-Git file used a two-line delta rather than
  the whole file size.
- Ready preflight returned all known missing executables and input files in one
  response.
- Default check output omitted full MDCP contracts; `--verbose` retained them.
- New aligned work outside an ACTIVE ticket was routed to a new/split/backlog
  path rather than changing frozen acceptance.

## Explicit Boundaries

This pass does not claim retrospective PID-level file-writer attribution,
cross-thread GPU/port/process leases, or interruption in the middle of an opaque
host tool call. Those require shared runtime infrastructure outside a repo-local
Goal Compass script. Runtime evidence remains evidence, not authority to kill a
different task's process.

Goal Janitor remains `MARK_ONLY`; this pass did not add move or delete authority.

## Verification

```text
Targeted real-install matrix: 12/12 PASS, under 10s
Module verification suite: 223/223 PASS, 50.868s
Discover verification suite: 223/223 PASS, 50.138s
Goal Compass selftest: PASS, 0.48s
```

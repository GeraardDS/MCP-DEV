# Autonomous Readiness — Phase 1 & 2 Design

**Date:** 2026-04-15
**Author:** Claude (sonnet via Claude Code)
**Branch:** new worktree `autonomous-phase-1-2` (recommended)
**Status:** DRAFT — awaiting user review

## 1. Goal

Make the MCP server safe and composable enough that Claude can drive full Power BI development workflows with minimal supervision. This design covers 8 items from the readiness audit: 5 safety items (Phase 1) and 3 workflow-composability items (Phase 2).

Out of scope: the Phase 3 stabilization refactors (splitting `debug_handler.py`, `@handler_op` decorator) and Phase 4 feature unlocks (baseline diff, screenshot, git commit). Those get separate specs.

## 2. Design principles

1. **Fail closed in autonomous mode, fail open outside it.** When `enter_mode` is active, missing audit writes or unconfirmed destructive ops must block. When mode is off, existing behavior is unchanged — we do NOT want to break interactive PBI Desktop use.
2. **Single choke point per concern.** One decorator for gating, one helper for audit append, one engine for cascade rename. No duplicate gating logic sprinkled across handlers.
3. **Schema-level guard rails beat runtime guard rails.** Where we can express a safety rule in JSON Schema (e.g. `maxItems`), do so — bad calls get rejected before dispatch.
4. **Opt-in break-glass.** Every safety gate has a documented bypass flag for power users (`force=True`, `confirm_destructive=true`). Claude should not guess these; they exist for humans.
5. **No silent semantic changes.** If we add a gate to an existing handler, calls that used to work must still work in the default case (interactive mode OFF), or we must return a clear `{error_type, hint}` so Claude can self-correct in one round trip.

## 3. Item-by-item design

### P1-1: Gate destructive handlers on `enter_mode`

**Problem:** `12_Autonomous_Workflow.enter_mode` only protects save/close/reopen/reload. Every other destructive tool (`02_Model_Operations`, `03_Batch_Operations`, `02_TMDL_Operations`, `07_Report_Operations` delete/restore, `11_PBIP_Authoring` delete/clone-overwrite) is ungated. Claude can wipe the model with no activation.

**Design:**

- New module `core/autonomous/gating.py`:
  - Four policies, from loosest to strictest:
    - `GATE_POLICY_OFF` — no gating, fully transparent. Current behavior.
    - `GATE_POLICY_LIGHT` (**new default**) — gate only the *catastrophic* ops (see list below); everything else passes. Logs a one-line notice on every blocked call so Claude learns the pattern.
    - `GATE_POLICY_WARN` — gate everything destructive; log + proceed (never blocks, but emits a `gate_warning` field in the response).
    - `GATE_POLICY_STRICT` — gate everything destructive; block unless mode is active.
  - Module reads `MCP_AUTONOMOUS_GATE_POLICY` env var (default `LIGHT`).
  - Function `require_autonomous_mode(op_name: str, args: dict, severity: str) -> Optional[dict]`:
    - `severity` is `"catastrophic"` or `"destructive"` (set by each handler's wrapper).
    - Policy × severity matrix:
      | Policy | catastrophic (no mode) | destructive (no mode) | read-only |
      |---|---|---|---|
      | OFF | pass | pass | pass |
      | **LIGHT (default)** | **block** | **advisory** (pass + `gate_notice` in response) | pass |
      | WARN | warn | warn | pass |
      | STRICT | block | block | pass |

    - **Advisory mode (LIGHT × destructive):** Response gets an extra field `gate_notice: "Destructive op 'X' ran without autonomous mode. Enter mode for audit logging + snapshot."` and a one-line log entry. Claude sees the hint and can decide whether to escalate. No action required — op proceeds normally.
    - Returns `None` if `args.get("confirm_destructive") is True` (break-glass for one-off interactive deletes).
    - Returns error dict `{success:False, error, error_type:"autonomous_mode_required", hint}` on block; returns `{"gate_warning": "..."}` (merged into response by wrapper) on warn.
  - Decorator `@autonomous_gated(op_label, severity)` for handler functions — wraps the handler, short-circuits on block, merges warning on warn.

- **What counts as catastrophic** (LIGHT default blocks these; everything else is just "destructive"):
  - `03_Batch_Operations` with `batch_operation == "delete"` AND `len(items) > 10` — mass deletion
  - `02_Model_Operations` with `object_type == "table"` AND `operation == "delete"` — dropping a table cascades to columns, relationships, measures
  - `02_TMDL_Operations.bulk_rename` with `cascade_to_reports=True` — cross-artifact mutation
  - `07_Report_Operations.restore` — overwrites live report files
  - `11_PBIP_Authoring` with `operation in {"delete_page", "clone_report"}` — loses work or overwrites big
  - `02_Model_Operations.refresh` with no `tables` param (full-model refresh) — long-running, expensive

- **What counts as destructive** (list matters — under-gating is the whole problem):
  - `02_Model_Operations`: operation ∈ {`delete`, `update`, `create`, `rename`, `move`, `set_translation`, `set_table_filter`, `clear_table_filter`, `add_member`, `remove_member`, `set`, `remove`, `refresh`, `generate_calendar`}. Anything not in {`list`, `describe`, `get`, `find`, `sample_data`, `statistics`, `distribution`, `list_items`, `list_members`}.
  - `03_Batch_Operations`: `batch_operation ∈ {create, update, delete, rename, move, move_display_folder, activate, deactivate, refresh}` AND `dry_run != True`. Dry-run is safe.
  - `02_TMDL_Operations`: `operation ∈ {bulk_rename, bulk_replace, migrate, apply_script}` — read-only ops (`export`, `parse`, `diff`) are safe.
  - `07_Report_Operations`: `operation ∈ {rename, rebind, restore, manage_extension_measures}` with non-list sub-ops.
  - `11_PBIP_Authoring`: `operation ∈ {clone_page, clone_report, create_page, create_visual, create_visual_group, delete_page, delete_visual}`.
  - `12_Autonomous_Workflow`: already gated — no change.

- **Break-glass design choice:** The `confirm_destructive=true` bypass is **per-call**, not session-wide. Rationale: a human hitting `AskUserQuestion` can approve once, but should not leave the door open for the next 100 calls. Claude in autonomous mode should use `enter_mode`, not repeat `confirm_destructive`.

- **Policy default choice:** `LIGHT`. Rationale: `OFF` offered no safety at all, and `STRICT` would block every existing CLAUDE.md user on their first interactive delete. `LIGHT` catches only the catastrophic ops (mass deletes, table drops, cross-artifact renames, full-model refresh) — all of which are already unusual enough that a user hitting them deserves a "you probably meant to enter autonomous mode first" prompt. Interactive users doing ordinary CRUD (create a measure, rename a column, delete one row) are unaffected. Document `MCP_AUTONOMOUS_GATE_POLICY=STRICT` in CLAUDE.md as the recommended setting for truly unsupervised Claude use.

**Files touched (new):**
- `core/autonomous/gating.py` — ~80 LOC

**Files touched (modified):**
- `server/handlers/model_operations_handler.py` — wrap `handle_model_operations` with gate check
- `server/handlers/batch_operations_handler.py` — wrap `handle_batch_operations`
- `server/handlers/tmdl_handler.py` — wrap destructive ops branch only
- `server/handlers/report_operations_handler.py` — wrap `rename`, `rebind`, `restore`, `manage_extension_measures` (writes)
- `server/handlers/authoring_handler.py` — wrap `handle_pbip_authoring`

**Expected output when blocked:**
```json
{
  "success": false,
  "error_type": "autonomous_mode_required",
  "error": "Catastrophic operation '03_Batch_Operations:delete' (42 items) blocked. Policy LIGHT requires autonomous mode for this operation.",
  "hint": "Call 12_Autonomous_Workflow operation=enter_mode first, or pass confirm_destructive=true for a one-off bypass.",
  "blocked_op": "03_Batch_Operations:delete",
  "severity": "catastrophic",
  "policy": "LIGHT"
}
```

**Tests:** `tests/test_autonomous_gating.py` — one test per handler, parametrized across policies OFF/LIGHT/WARN/STRICT × severities {catastrophic, destructive} × {active, inactive, confirm_destructive}.

---

### P1-2: Cap batch blast radius

**Problem:** `03_Batch_Operations.items[]` has no `maxItems`. A single `delete` call with 500 items succeeds silently.

**Design:** Three independent knobs, applied in order.

1. **Schema hard cap** (always on, policy-independent) — `maxItems` on the `items` array, per-object-type. Rejected by JSON Schema before dispatch:
   - measures: 200
   - columns: 200
   - relationships: 100
   - tables: 30
   These caps are intentionally **higher** than the P1-1 catastrophic threshold. Rationale: a legitimate cleanup can touch 150 measures; the cap is to prevent runaway loops, not to guard semantics.

2. **Runtime confirmation gate** (always on, policy-independent) — when `batch_operation == "delete"` and `len(items) > 20`, require `confirm_destructive: true`. Below 20: proceed. This is the "are you sure" guard.

3. **P1-1 catastrophic trigger** (policy-dependent) — `batch delete > 10` is "catastrophic" for policy LIGHT/STRICT. Blocks unless mode active OR `confirm_destructive=true`.

**How they interact** (example: `batch delete` with N items, policy LIGHT, mode inactive):
- N ≤ 10: passes (destructive but below catastrophic threshold → advisory notice only)
- 11 ≤ N ≤ 20: blocked by P1-1 catastrophic gate. Claude either enters mode or passes `confirm_destructive=true`
- 21 ≤ N ≤ 200: blocked by P1-2 runtime confirm AND P1-1 catastrophic gate. `confirm_destructive=true` satisfies both.
- N > 200: rejected at schema level. Split the call.

**Always return** a `would_affect` summary for deletes >10: counts per table, first 10 names. Populated even on block so Claude can sanity-check before retrying.

**Files touched:**
- `server/handlers/batch_operations_handler.py` — schema caps
- `core/operations/batch_operations.py` — add confirm_destructive check at top of `_batch_measures`, `_batch_tables`, `_batch_columns`, `_batch_relationships`
- New helper `core/operations/batch_validation.py` — `check_blast_radius(operation, items) -> Optional[dict]`

**Expected output when blocked:**
```json
{
  "success": false,
  "error_type": "confirmation_required",
  "error": "Deleting 42 measures requires confirm_destructive=true",
  "would_affect": {
    "total": 42,
    "by_table": {"m_Measures": 30, "TestTopBottom": 12},
    "first_10_names": ["Measure A", "Measure B", "..."]
  },
  "hint": "Re-send with confirm_destructive=true if this is intended."
}
```

**Tests:** `tests/test_batch_blast_radius.py` — caps enforced, confirm flag required at right threshold, `would_affect` populated.

---

### P1-3: Real TOM transactions on batch ops

**Problem:** `core/operations/transaction_management.py:1-13` explicitly states it is not ACID. `bulk_delete_measures` and `_batch_item_loop` iterate and each CRUD manager calls `model.SaveChanges()` per item. Mid-batch failure leaves the model in a half-changed state. Per audit: `use_transaction` option is honored nowhere.

**Design decision — the hard one:** There are two ways to implement real transactions.

**Option A: BeginUpdate/EndUpdate + UndoLocalChanges (true TOM transaction).**
- Wrap batch in `model.Model.BeginUpdate()` … mutate all items … `model.SaveChanges()`. On any failure, `model.UndoLocalChanges()` then return errors.
- **Pro:** Real atomic — model always consistent.
- **Con:** CRUD managers today call SaveChanges internally. Every manager needs a `defer_save=True` parameter, or the BatchHandler must call SaveChanges at the end and individual managers must skip it. This is a ~15-file refactor.

**Option B: Per-item snapshot + manual rollback (pragmatic transaction).**
- Before each item, capture its pre-state via TOM (measure expression, column properties, etc.).
- On batch failure, replay the inverse operations to restore.
- **Pro:** No CRUD manager changes needed. Can be added purely at the `BatchOperationsHandler` level.
- **Con:** "Inverse operations" are fragile (deleted measures need full re-creation; renamed objects need renaming back; we can miss edges). Race-prone if other clients mutate concurrently (rare for PBI Desktop but possible).

**Recommendation: Option A, but scoped.** Refactor only the batch code path:
- Add `defer_save` param to the 4 CRUD managers used by batch (`measure_crud_manager`, `table_crud_manager`, `column_crud_manager`, `relationship_crud_manager`) — default `False` (current behavior).
- Add methods `begin_batch()`, `commit_batch()`, `rollback_batch()` on a new `core/operations/tom_transaction.py` that wrap the AMO `Model.BeginUpdate()` / `SaveChanges()` / `UndoLocalChanges()` calls via the existing AMO connection in `connection_state`.
- `BatchOperationsHandler._batch_measures|_tables|_columns|_relationships` opens a transaction at the top, passes `defer_save=True` to the CRUD manager, commits at the end. On any item exception: rollback, return partial state summary.
- `bulk_create_measures` / `bulk_delete_measures` similarly refactored — they already do single SaveChanges at the end today (verified — no `SaveChanges` in `bulk_operations.py`), so they're actually close to right. Just need explicit `BeginUpdate`.

**Files touched:**
- New: `core/operations/tom_transaction.py` — ~80 LOC wrapping `model.BeginUpdate()`/`SaveChanges()`/`UndoLocalChanges()`
- Modified: `core/operations/measure_crud_manager.py`, `table_crud_manager.py`, `column_crud_manager.py`, `relationship_crud_manager.py` — add `defer_save` param to every mutating method. When `True`, skip the final SaveChanges.
- Modified: `core/operations/batch_operations.py` — wrap each `_batch_*` in transaction
- Modified: `core/operations/bulk_operations.py` — wrap `bulk_create_measures`, `bulk_delete_measures` in transaction

**Expected response shape:**
```json
{
  "success": false,
  "operation": "delete",
  "total": 10,
  "succeeded": 0,
  "failed": 1,
  "rolled_back": true,
  "errors": [{"item": "Bad Measure", "error": "Formula dependency still exists: ..."}],
  "message": "Batch failed on item 3/10 — all changes rolled back via UndoLocalChanges"
}
```

**Tests:** `tests/test_tom_transaction.py` — mock AMO model, verify BeginUpdate called, UndoLocalChanges called on exception.

**Risk note:** This is the most invasive item. If test coverage on CRUD managers is zero (audit confirmed), a subtle bug in `defer_save` could corrupt saves in non-batch paths. Mitigation: comprehensive test suite for `defer_save=True` AND `defer_save=False` per manager before merging.

---

### P1-4: Auto-snapshot PBIP folder on `enter_mode`

**Problem:** No pre-change snapshot. If Claude deletes the wrong table mid-autonomous-session, only recovery is user-side git / OneDrive version history — neither guaranteed.

**Design:**

- On `enter_mode`, if a PBIP path is known (via `09_Debug_Operations` set_path state, OR new optional param `pbip_path` on `enter_mode`), snapshot:
  - `{pbip_root}.SemanticModel/definition/` (TMDL, typically 1-5 MB)
  - `{pbip_root}.Report/definition/` (PBIR JSON, typically 1-10 MB)
  - Do **not** include `.Report/StaticResources/` (often large, not safety-critical — images)
  - Do **not** include `.pbip`, `.pbir`, `.pbism` root files (they're tiny pointers, safe to skip)
- Write snapshot as zip to `{audit_log_dir}/{session_id}.snapshot.zip`.
- Store `snapshot_path` in `_ModeState.extras["snapshot_path"]`.
- New op: `12_Autonomous_Workflow operation=restore_snapshot` — extracts zip to a user-specified directory (never overwrites live files without confirmation).

**Size budget:** Cap at 50 MB. Above that, emit a warning and skip snapshot (user's model is too big; they should rely on git). Log the skip in audit.

**Retention:** Keep last 10 session snapshots in the audit log dir. LRU cleanup on new `enter_mode`.

**Files touched:**
- New: `core/autonomous/snapshot.py` — ~120 LOC
- Modified: `core/autonomous/mode_manager.py` — accept `pbip_path`, call snapshot engine, store snapshot_path in extras
- Modified: `server/handlers/autonomous_handler.py` — add `restore_snapshot` op + pass `pbip_path` through

**Expected response:**
```json
{
  "success": true,
  "active": true,
  "session_id": "autonomous-1712345600",
  "snapshot": {
    "path": "C:/Users/.../mcp-pbi-autonomous/autonomous-1712345600.snapshot.zip",
    "size_bytes": 2847291,
    "files_captured": 147,
    "elapsed_ms": 340
  }
}
```

**Tests:** `tests/test_snapshot.py` — create/restore cycle on a fixture PBIP folder, size cap respected, retention LRU works.

---

### P1-5: Fail-closed audit log

**Problem:** `audit_log.py:120` swallows append failures with a `logger.warning`. In active mode, if the log dir becomes unwritable, destructive ops still proceed with no record.

**Design:**

- Change `AuditLog.append` to return `bool` (success flag). Currently returns None.
- Add new method `AuditLog.append_strict(...)` that raises `AuditWriteError` on failure.
- In the gate decorator from P1-1: when mode is active, after running the destructive op, call `append_strict`. If it raises, the op has already executed (too late to prevent the mutation this call) but:
  - Log CRITICAL that audit is broken
  - Automatically call `exit_mode(reason="audit_log_failure")` to prevent further destructive ops
  - Return a warning in the response: `{audit_log_failure: true, mode_exited: true}`
- **Pre-flight check:** At `enter_mode`, write a canary `{"ts": ..., "op": "enter_mode_canary"}` entry. If canary write fails, refuse to activate and return an error. This is the real "fail closed before the bad thing happens" point.

**Why not abort the current op on audit failure?** Because TOM changes are already committed by the time we're writing the audit log — undoing them requires a second AMO round-trip and may itself fail. Cleaner to: (a) canary at `enter_mode` so this rarely happens, (b) exit mode immediately so subsequent ops are blocked, (c) surface the failure loudly in the response.

**Files touched:**
- Modified: `core/autonomous/audit_log.py` — canary + append_strict + exception type
- Modified: `core/autonomous/mode_manager.py` — call canary in `enter_mode`
- Modified: `core/autonomous/gating.py` (from P1-1) — wrap op with post-call `append_strict`; auto-exit on failure

**Tests:** `tests/test_audit_log.py` — add: canary success/failure paths, `append_strict` raises on IOError, gate decorator exits mode on audit failure.

---

### P2-6: Mark reload-required ops

**Problem:** Visual/page/authoring ops write to PBIP files on disk; PBI Desktop ignores until close+reopen. Claude doesn't know which ops need a reload, so it either reloads too often (slow) or too rarely (looks at stale data).

**Design (cheap but high-value):**

- New constant `RELOAD_REQUIRED` in a new module `core/autonomous/reload_hints.py`:
  - `OPS_REQUIRING_RELOAD_AFTER_PBIP_WRITE` = set of `(tool_name, operation)` tuples.
  - Populated from audit findings: all `07_Visual_Operations` write ops, all `07_Page_Operations` write ops, all `11_PBIP_Authoring` ops, `02_TMDL_Operations.bulk_rename`, `07_Theme_Operations` write ops.

- Add a post-processing hook in `server/middleware.py` (or in a small wrapper at each handler): after a successful response from a PBIP-write op, inject:
  ```json
  {
    "reload_required": true,
    "reload_hint": "PBI Desktop holds model in memory; run 12_Autonomous_Workflow operation=close (save_first=true) then operation=reopen to load this change.",
    "reload_op_chain": ["12_Autonomous_Workflow:close", "12_Autonomous_Workflow:reopen", "12_Autonomous_Workflow:wait_ready"]
  }
  ```

- Do NOT inject for live-TOM ops (`02_Model_Operations` measure/table/column updates) — those propagate immediately.

- **Tracking:** `mode_manager` maintains `state.extras["pending_reloads"] = [op_name, ...]` so `12_Autonomous_Workflow.status` can surface "3 PBIP-write ops since last reload".

**Files touched:**
- New: `core/autonomous/reload_hints.py` — ~40 LOC
- Modified: `server/handlers/visual_operations_handler.py`, `page_operations_handler.py`, `authoring_handler.py`, `theme_operations_handler.py`, `tmdl_handler.py` — call `attach_reload_hint(response, tool, op)` at end of successful responses
- Modified: `core/autonomous/mode_manager.py` — add `note_pending_reload(op)` and expose via `status`

**Expected response shape (addition):**
```json
{
  "success": true,
  "visual_id": "abc123",
  "reload_required": true,
  "reload_hint": "...",
  "reload_op_chain": ["12_Autonomous_Workflow:close", "12_Autonomous_Workflow:reopen", "12_Autonomous_Workflow:wait_ready"]
}
```

**Tests:** `tests/test_reload_hints.py` — assert hint appears on PBIP-write ops, absent on live-TOM ops.

---

### P2-7: Cross-artifact cascade rename

**Problem:** `02_TMDL_Operations.bulk_rename` updates TMDL only. Every `visual.json` field reference in every report is broken silently after the rename.

**Design:**

- Extend `core/tmdl/bulk_editor.py:bulk_rename` to accept `cascade_to_reports: bool = False` (default False to preserve existing behavior).
- When `cascade_to_reports=True`:
  1. After TMDL rename completes, walk every `*.Report/` folder sibling to the renamed `*.SemanticModel/`.
  2. Parse every `visual.json`, `bookmarks/*.json`, `filters.json`, `theme.json` (if present).
  3. For each rename `{object_type, old_name, new_name, table_name}`:
     - `object_type=table`: find strings matching `"Entity": "old_name"` and `"Schema": "..."` in field references; update.
     - `object_type=column|measure`: find `{"Name": "old_name", "Entity": "table_name"}` in field references; update.
  4. Write files back only if changed. Track per-file change counts.
- The matching is schema-aware (uses PBIR JSON paths), NOT free-text replace. Rationale: a column named `Date` would false-positive-match any JSON with `"Date"`.

- New helper module: `core/pbip/cascade_rename.py` with:
  - `CascadeRenameEngine` class
  - `walk_reports(pbip_root) -> List[Path]` — find all `.Report/definition/` folders
  - `apply_renames(report_path, renames) -> CascadeResult` — per-report diff + write

**Safety:**
- Always run with `dry_run=True` first by default when `cascade_to_reports=True`. User must pass `dry_run=False` explicitly for real changes.
- Backup the full `.Report/` folder before writing if `backup=True` (default).
- Validate JSON parses before and after write.

**Files touched:**
- New: `core/pbip/cascade_rename.py` — ~200 LOC
- Modified: `core/tmdl/bulk_editor.py:bulk_rename` — add cascade param, invoke engine after TMDL pass
- Modified: `server/handlers/tmdl_handler.py` — surface `cascade_to_reports` in schema

**Expected response:**
```json
{
  "success": true,
  "objects_renamed": 1,
  "references_updated": 23,
  "files_modified": 8,
  "cascade": {
    "reports_scanned": 2,
    "visuals_updated": 15,
    "bookmarks_updated": 3,
    "filters_updated": 5,
    "per_report": [
      {"report": "Sales.Report", "visuals": 10, "bookmarks": 2, "filters": 3},
      {"report": "HR.Report", "visuals": 5, "bookmarks": 1, "filters": 2}
    ]
  }
}
```

**Tests:** `tests/test_cascade_rename.py` — fixture PBIP with 2 reports, rename a column, assert every reference is updated.

---

### P2-8: Measure-ref handoff to `05_DAX_Intelligence`

**Problem:** `09_Debug_Operations` trace returns measure name; `05_DAX_Intelligence.optimize` requires `expression`. Claude has to fetch DAX separately — an extra round trip per optimization.

**Design:**

- In `_resolve_measure_expression` at `debug_handler.py` (already used for `optimize`): this function already exists and resolves by measure name. Good.
- Extend `05_DAX_Intelligence.analyze` (and any other ops that take `expression`) to accept `measure_name` as an alternative. When both are absent, error. When `measure_name` is given, resolve via `_resolve_measure_expression` and use the resolved DAX.
- Also accept `{table, measure}` tuple to disambiguate same-named measures across tables.
- Bonus: when `09_Debug_Operations.visual` trace surfaces a bottleneck, include a `next_action` hint:
  ```json
  {
    "next_action": {
      "tool": "05_DAX_Intelligence",
      "operation": "optimize",
      "args": {"measure_name": "Total Sales", "table_name": "m_Measures"}
    }
  }
  ```
  …so Claude doesn't have to assemble the call itself.

**Files touched:**
- Modified: `server/handlers/debug_handler.py` — (a) extend ops that take `expression` to accept `measure_name`, (b) add `next_action` to trace responses when bottleneck detected
- Modified: `core/dax/analysis_pipeline.py` — thin wrapper accepting measure_ref; delegates to `_resolve_measure_expression`

**Tests:** `tests/test_dax_intelligence_handoff.py` — analyze with `measure_name` alone works, analyze with both `expression` and `measure_name` uses expression (explicit wins), analyze with neither errors.

---

## 4. Execution order

Items are grouped into four landable chunks to keep each PR digestible and reviewable:

| Chunk | Items | Rationale | Est. LOC |
|---|---|---|---|
| **A** | P1-5 (canary), P2-6 (reload hints), P2-8 (measure-ref) | Small, isolated, no architectural changes. Good warm-up. | ~300 |
| **B** | P1-1 (gate decorator), P1-2 (blast radius) | Gate depends on audit (chunk A for canary), blast radius layers on gate. | ~400 |
| **C** | P1-4 (snapshot) | Depends on audit log dir from chunk A; isolates from chunk D. | ~300 |
| **D** | P1-3 (real transactions), P2-7 (cascade rename) | Biggest refactors; land last when test suite is healthy. | ~800 |

Each chunk = one PR, one commit, one round of `pytest`.

## 5. Testing strategy

- **New test files (8):** `test_autonomous_gating.py`, `test_batch_blast_radius.py`, `test_tom_transaction.py`, `test_snapshot.py`, `test_reload_hints.py`, `test_cascade_rename.py`, `test_dax_intelligence_handoff.py`, `test_audit_log.py` (augment existing).
- **Target coverage:** 80% on every new module. We're adding safety code; it must itself be safe.
- **Integration test:** One end-to-end test that activates mode → tries destructive op → asserts blocked without `confirm_destructive`; then enters mode → runs batch → asserts snapshot captured + audit log populated + gate honored.

## 6. Docs updates

- `CLAUDE.md` — new section "Autonomous Gate Policy" documenting `MCP_AUTONOMOUS_GATE_POLICY` env var.
- `core/autonomous/README.md` (new) — architecture diagram of gate → audit → snapshot flow.
- `12_Autonomous_Workflow` tool description — add `restore_snapshot` op.

## 7. Risks + mitigations

| Risk | Mitigation |
|---|---|
| P1-3 `defer_save` refactor introduces silent corruption in non-batch paths | Add characterization tests against real (or mocked) AMO in the same PR: assert `defer_save=False` (default) preserves current behavior byte-for-byte, `defer_save=True` does not call SaveChanges. Ship chunk D last so chunks A–C stabilize the test fixture patterns first. |
| P1-1 gate default too strict, breaks interactive users | Ship default `LIGHT` (blocks only catastrophic ops). Interactive users hitting a block can pass `confirm_destructive=true` or enter mode. Document `STRICT` as the recommended policy for unsupervised Claude use. |
| P1-4 snapshot size blows out disk for big models | 50 MB cap + skip-with-warning; LRU retention of 10 |
| P2-7 cascade rename corrupts `visual.json` | JSON parse validation before + after write; dry_run default when cascade=True; full backup |
| Tests mock AMO — real behavior may diverge | One smoke test that runs against a real PBIP fixture if PBI Desktop available in CI |

## 8. Explicit non-goals for this spec

- Not extending the gate to read-only ops (`list`, `describe`) — those are safe.
- Not adding screenshot, baseline diff, git commit — those are Phase 4.
- Not splitting `debug_handler.py` — Phase 3.
- Not building a UI — this is a server-side change; the UI is Claude's tool-calling.
- Not changing existing tool names or shapes beyond response additions — back-compat matters.

## 9. Definition of done

1. All 8 items implemented, each with tests passing
2. `black`, `mypy`, `flake8` clean on all new/modified files
3. `pytest` green with no regressions (existing 31 tests still pass + ~80 new tests)
4. `CLAUDE.md` + `docs/` updated
5. One integration smoke test against a fixture PBIP
6. User-visible behavior change documented in CHANGELOG or commit messages
7. Verified on a real Power BI Desktop session: `enter_mode` → destructive batch blocked → `enter_mode` activates → batch succeeds → audit log + snapshot populated → `exit_mode` emits summary

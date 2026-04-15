# Autonomous Workflow Tool — Implementation Plan

Single new tool `12_Autonomous_Workflow` plus refresh-error hardening.
Composes three subprojects (A: refresh, B: lifecycle, C: workflow primitives) into one tool.

## Locked design decisions

1. **One consolidated tool** `12_Autonomous_Workflow` in new `AUTONOMOUS` category.
2. **Mode gate**: explicit session activation. Idle timeout 30 min, hard ceiling 4 hours, MCP restart clears.
3. **Save/close/reopen**: hybrid path. PBIP → write files via existing tools, kill process, relaunch. PBIX → UI automation (Ctrl+S, then close, then relaunch). Pending-changes detector decides which path.
4. **Wait-ready**: 5 escalating levels (process / port / ADOMD / identity / refresh-idle). Default target = identity-match. Configurable timeout default 180s.
5. **Audit log**: JSONL during run + markdown summary on exit. Default `%TEMP%/mcp-pbi-autonomous/<session>.jsonl`, configurable path. Before/after snapshots for destructive ops (close/save/refresh).
6. **Refresh hardening**: capture inner CLR exceptions, table/partition context, last query — added to existing handlers in `table_crud_manager.py` and `partition_crud_manager.py`, surfaced through `02_Model_Operations`.
7. **Subproject C extras** (all in scope): post-refresh validation runner, wait-for-condition primitive, retry wrapper, reload macro, ETL round-trip, audit trail.

## Tool operations

| Operation | Purpose |
|---|---|
| `enter_mode` | Flip session flag on. Optional `idle_timeout_minutes`, `max_duration_minutes`, `log_path`. |
| `exit_mode` | Flip flag off. Emit markdown summary. |
| `status` | Return current mode state, time remaining, audit summary. |
| `save` | Save pending TOM changes via UI automation (PBIX) or no-op (PBIP). |
| `close` | Save-if-pending, then kill `PBIDesktop.exe` for the current instance. |
| `reopen` | Launch `PBIDesktop.exe <file>`, wait for ready level, reconnect. |
| `reload` | Macro: save → close → reopen → wait_ready → optional refresh → optional validate. |
| `wait_ready` | Wait for chosen readiness level with timeout. Standalone primitive. |
| `validate` | Run a list of DAX assertions and return pass/fail with diagnostic info. |
| `audit_log` | Read or rotate the JSONL/MD log files. |

## Build order

1. `requirements.txt` — add `pywinauto`.
2. `core/autonomous/` package + modules in dependency order:
   - `mode_manager.py` (no deps): thread-safe singleton with idle/hard timers.
   - `audit_log.py` (no deps): JSONL writer + markdown summary emitter.
   - `pending_changes.py` (TOM): `HasLocalChanges` query + file mtime fallback.
   - `process_manager.py` (psutil): find PBIDesktop by file path, kill, launch.
   - `ui_automation.py` (pywinauto, optional import): Ctrl+S, close confirmation handling.
   - `wait_conditions.py` (psutil + ADOMD): 5 levels, identity match by file path.
   - `validation_runner.py` (query_executor): list of `{name, dax, expected, op}` assertions.
   - `lifecycle_manager.py`: orchestrates everything; gated on `mode_manager.is_active()`.
3. Handlers:
   - `core/operations/table_crud_manager.py` — extend `refresh_table` to capture inner exceptions, table context, return structured detail.
   - `core/operations/partition_crud_manager.py` — same for `refresh_partition`.
   - `server/handlers/autonomous_handler.py` — new `12_Autonomous_Workflow` dispatcher.
4. Registration:
   - `server/registry.py` — add `AUTONOMOUS` category, tool list, info entry.
   - `server/handlers/__init__.py` — import and register.
5. Tests in `tests/`:
   - `test_mode_manager.py` — flag lifecycle, idle expiry, hard ceiling.
   - `test_audit_log.py` — JSONL append, markdown summary.
   - `test_validation_runner.py` — DAX-free unit tests using mock query executor.
6. Lint + test pass.
7. Update `CLAUDE.md` and `MEMORY.md`.

## Out of scope (deferred)

- Power BI Service / XMLA endpoint refresh (Desktop only for now).
- Incremental refresh policy management.
- Data quality rule engine (validation runner is just DAX assertions).
- Multi-instance lifecycle (one PBI Desktop instance at a time).

## Review section

**Status: shipped.** Implementation completed 2026-04-15.

### What landed

- `core/autonomous/` package (9 modules, ~1900 LOC total):
  - `mode_manager.py` — session flag, idle+hard timers, singleton via `get_mode_manager()`
  - `audit_log.py` — JSONL append + markdown summary; uses stdlib `json.dumps(separators=...)` for compact JSONL (do NOT use `dumps_json(indent=None)` — it ignores `indent` and pretty-prints anyway)
  - `pending_changes.py` — TOM `HasLocalChanges` + file-mtime hybrid
  - `process_manager.py` — psutil enumerate + terminate/launch for `PBIDesktop.exe`
  - `ui_automation.py` — optional pywinauto Ctrl+S save path
  - `wait_conditions.py` — 5 escalating readiness levels (process→port→adomd→identity→refresh_idle)
  - `validation_runner.py` — DAX assertion runner with 9 comparison ops
  - `lifecycle_manager.py` — orchestrator; every op gated on `mode_manager.check_active()`
  - `clr_errors.py` — walk `.InnerException` / `System.AggregateException` chains for refresh failures
- Refresh hardening: `table_crud_manager.refresh_table` and `partition_crud_manager.refresh_partition` now return structured CLR-chain errors instead of bare `str(e)`.
- Handler: `server/handlers/autonomous_handler.py` → tool `12_Autonomous_Workflow` with 10 operations.
- Registry: `AUTONOMOUS` category added; handler auto-registered in `server/handlers/__init__.py`. Total tools: 23 → 24.
- Tests: `tests/test_mode_manager.py`, `tests/test_audit_log.py`, `tests/test_validation_runner.py` — 31 tests, all pass. `tests/conftest.py` bootstraps sys.path.

### Gotchas discovered during build

- **`dumps_json(indent=None)` is a trap** — the orjson wrapper ignores the argument and still emits indented output. For JSONL always use stdlib `json.dumps(entry, separators=(",", ":"), default=str)`.
- **`x or DEFAULT` drops `0`** — `enter_mode(idle_timeout_minutes=0)` silently fell back to the default instead of rejecting as invalid. Use explicit `is not None` checks when 0 is a distinct sentinel.
- Fresh worktree had no `tests/` dir; added with `conftest.py` that injects repo root on `sys.path` (so `import core.*` works under pytest without editable install).

### Deferred (still out of scope)

- Power BI Service / XMLA endpoint refresh (Desktop only)
- Incremental refresh policy management
- Multi-instance lifecycle


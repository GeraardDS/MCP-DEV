# Remaining TODOs — Post-Review

**Date:** 2026-03-27
**Status:** All items from the original review have been implemented.

---

## Completed This Session

All items from the original TODO list have been implemented:

- [x] Progress Tracking — async bridge via `server/progress.py`, handler milestones in debug + analysis
- [x] Structured Output — `outputSchema` on 4 key tools (Detect, Run DAX, Measures, Analysis)
- [x] Confirmation Gates — `security.confirm_destructive` config flag, dispatcher enforcement
- [x] PBIP Broken Visual Scan — `core/pbip/pbip_visual_validator.py`, `scan_broken_refs` operation
- [x] Split debug_handler — verified no dead code (all 40+ functions reachable)
- [x] Layering violation — verified already correct (server/ imports from core/, not reverse)
- [x] Path traversal test fix — added `..` check before normpath, 128/128 tests pass

---

## Future Enhancements (Not Requested)

These items were identified during review but explicitly skipped per user direction:

| Feature | Effort | Notes |
|---------|--------|-------|
| Partition management (list/add/remove/refresh) | 4-6h | `PartitionManager` exists with `list`, needs add/remove |
| Resource templates (`powerbi://table/{name}/measures`) | 4-5h | Browsable model objects |
| PII detection and masking | 1d+ | Regex scan on result rows |
| MCP logging (`setLevel` + `notifications/message`) | 2h | Wire to existing Python logging |
| Cloud/Fabric XMLA connector | Very large | Remote model access |
| Streamable HTTP transport | Large | For remote deployment |
| Expand test coverage further | Ongoing | TMDL parser, BPA edge cases, thread safety, PBIP dependency engine |

---

## Reference

- Full findings: [2026-03-27-full-review-findings.md](2026-03-27-full-review-findings.md)
- Prioritized roadmap: [2026-03-27-roadmap.md](2026-03-27-roadmap.md)
- Design spec: [../superpowers/specs/2026-03-27-full-server-review-design.md](../superpowers/specs/2026-03-27-full-server-review-design.md)

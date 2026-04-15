"""
Autonomous Workflow Subsystem

Provides primitives for closed-loop Power BI automation:
- Session-scoped autonomous mode flag (idle + hard ceiling timeouts)
- PBI Desktop save/close/reopen lifecycle (hybrid PBIP/PBIX strategy)
- Wait-for-readiness with escalating verification levels
- DAX assertion runner for post-refresh validation
- JSONL + markdown audit log

All destructive operations (close, save, reopen, reload) are gated on the
mode_manager.is_active() check so they only fire after explicit user activation.
"""

from core.autonomous.mode_manager import (
    AutonomousModeManager,
    get_mode_manager,
)
from core.autonomous.audit_log import AuditLog
from core.autonomous.pending_changes import PendingChangesDetector
from core.autonomous.process_manager import PbiDesktopProcessManager
from core.autonomous.wait_conditions import (
    WaitConditions,
    ReadinessLevel,
)
from core.autonomous.validation_runner import (
    ValidationRunner,
    AssertionResult,
)
from core.autonomous.lifecycle_manager import LifecycleManager

__all__ = [
    "AutonomousModeManager",
    "get_mode_manager",
    "AuditLog",
    "PendingChangesDetector",
    "PbiDesktopProcessManager",
    "WaitConditions",
    "ReadinessLevel",
    "ValidationRunner",
    "AssertionResult",
    "LifecycleManager",
]

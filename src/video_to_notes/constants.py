from __future__ import annotations

STAGES = (
    "visual",
    "transcription",
    "evidence",
    "reconstruction",
    "completion",
    "review",
    "render",
    "audit",
)

VALID_STATUSES = {
    "pending",
    "running",
    "done",
    "failed",
    "skipped",
}

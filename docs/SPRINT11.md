# Sprint 11 — Codex One-Shot Workflow

Version: 1.1.0

## Goal

Turn the existing stage-by-stage Codex handoff into a resumable controller so the user can provide one local video path and let Codex drive the whole pipeline to LaTeX/PDF.

## New CLI

```powershell
video-to-notes workflow "VIDEO"
```

## State-machine behavior

```text
workflow VIDEO
  |
  +-- visual (run/reuse)
  +-- transcription (run/reuse)
  +-- evidence (run/reuse)
  |
  +-- reconstruction
  |     +-- prepare automatically if needed
  |     +-- CODEX_TASK_REQUIRED
  |     +-- apply automatically when responses exist
  |
  +-- completion
  |     +-- prepare automatically if needed
  |     +-- CODEX_TASK_REQUIRED
  |     +-- apply automatically when responses exist
  |
  +-- review
  |     +-- prepare automatically if needed
  |     +-- Luna High / Sol Medium / Terra requests
  |     +-- apply automatically when responses exist
  |
  +-- render
  +-- audit
  |
  +-- WORKFLOW_COMPLETE
```

The controller writes `reports/workflow_report.json` after every invocation.

## Codex behavior

Root `AGENTS.md` now defines `CODEX_TASK_REQUIRED` as an internal Codex action, not a user handoff. Codex reads task files, honors `required_model`, writes responses, and invokes the same workflow command again until terminal output.

## Compatibility

All direct stage commands remain available for testing and diagnosis.

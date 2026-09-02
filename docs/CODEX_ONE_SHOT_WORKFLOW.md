# Codex One-Shot Workflow

## Goal

The user should be able to give Codex only a local video path, for example:

```text
完整处理这个视频：E:\pywork\课程\lesson.mp4
```

Codex then owns the complete interaction with `video_to_notes` until LaTeX/PDF are produced.

## Controller command

```powershell
video-to-notes workflow "E:\pywork\课程\lesson.mp4"
```

The command is a resumable state machine. It advances all deterministic work and stops only when Codex reasoning is required or the pipeline has reached its final outputs.

### First invocation

Typical progression:

```text
visual -> transcription -> evidence -> prepare reconstruction
```

Then the controller returns:

```text
STATUS: CODEX_TASK_REQUIRED
STAGE: reconstruction
TASK_DIR: ...\tasks\reconstruction
RESPONSE_DIR: ...\responses\reconstruction
REQUIRED_MODELS: terra
```

Codex reads the requests, writes responses, and runs the same controller command again.

### Later invocations

The same pattern repeats:

```text
reconstruction apply
-> prepare completion
-> Codex/Terra
-> completion apply
-> prepare review
-> Codex/Luna High + Sol Medium + Terra
-> review apply
-> render
-> audit
```

No user intervention is required between these transitions.

## Final output

Terminal output contains:

```text
STATUS: WORKFLOW_COMPLETE
LATEX: ...\latex\lecture.tex
PDF: ...\output\lecture.pdf
AUDIT: PASS  # or PASS_WITH_NOTES when Sol High still has unresolved targets
AUDIT_REPORT: ...\reports\quality_report.md
```

or, if the PDF was generated but quality gates still block final acceptance:

```text
STATUS: WORKFLOW_COMPLETE_REVIEW_REQUIRED
PDF: ...\output\lecture.pdf
AUDIT: REVIEW_REQUIRED
```

Codex should inspect the audit report and resolve actionable issues where possible before reporting completion.

## Resume behavior

The controller is safe to call repeatedly. Completed deterministic stages are reused when their cache is valid. If the process is interrupted, invoke the same command again; it continues from the persisted workspace state.

## Workflow report

Every invocation writes:

```text
workspace/<lesson>/reports/workflow_report.json
```

This file records the current workflow status, next semantic task (if any), required models, and final artifact paths when available.

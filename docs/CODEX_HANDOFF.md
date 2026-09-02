# Codex Handoff Workflow

Sprint 9.1 changes semantic LLM work from API-first to Codex-first.

## Default mode

```yaml
llm:
  mode: "codex_handoff"
```

No API key is required in this mode.

## Pipeline ownership

```text
visual          Python / ffmpeg
transcription   Whisper
Evidence        Python
reconstruction  Codex handoff
completion      Codex handoff
review          Codex handoff
render          Python / Jinja2 / XeLaTeX
audit           Python
```

## Reconstruction

```powershell
video-to-notes reconstruct prepare "lesson.mp4"
```

This creates:

```text
workspace/<lesson>/tasks/reconstruction/
├── INSTRUCTIONS.md
├── manifest.json
├── chunk_0000.request.json
├── ...
└── merge.request.json
```

Ask Codex to execute `INSTRUCTIONS.md`. Codex writes:

```text
workspace/<lesson>/responses/reconstruction/
├── chunk_0000.json
├── ...
└── lecture.json
```

Then:

```powershell
video-to-notes reconstruct apply "lesson.mp4"
```

`apply` validates evidence references, origin/status rules and the lecture schema before writing the canonical `lecture/lecture.json`.

## Completion

```powershell
video-to-notes complete prepare "lesson.mp4"
# Codex executes tasks/completion/INSTRUCTIONS.md
video-to-notes complete apply "lesson.mp4"
```

## Review

```powershell
video-to-notes review prepare "lesson.mp4"
# Codex executes tasks/review/INSTRUCTIONS.md
video-to-notes review apply "lesson.mp4"
```

The factual, math and pedagogical reviewer roles remain separated.

## Task status

```powershell
video-to-notes codex-tasks "lesson.mp4"
```

Typical output:

```text
[TODO ] reconstruction responses 0/2
[WAIT ] completion     no prepared task
[WAIT ] review         no prepared task
```

When all required responses exist but have not yet been applied, the stage is shown as `READY`. After successful `apply`, it is `DONE`.

## Optional API mode

The old providers remain available for unattended execution:

```powershell
video-to-notes reconstruct api "lesson.mp4"
video-to-notes complete api "lesson.mp4"
video-to-notes review api "lesson.mp4"
```

Only these explicit `api` commands use each stage's `llm.provider` settings and may require an API key.

## State safety

Running `prepare` resets that stage and all downstream Stage Receipts. For the current handoff it preserves only response files whose **individual request_id still matches and whose schema validates**; stale responses are removed. Reconstruction/completion merge responses are preserved only when all of their input chunks are also preserved. This gives request-level resume without mixing old semantic outputs with new inputs.

## Sprint 10 additions

Reconstruction request Evidence items now include `frames` with real frame id/time/path. Codex should inspect these images for visual/geometry tasks and output only `figure_evidence_ids`, never fabricated file paths.

Completion request chunks include inferred `requires_solution` and `solution_completeness` data. For incomplete/missing/uncertain proof tasks with sufficient conditions, Terra must emit `type=derived_solution` instead of merely preserving the gap.

Math review targets now include problem-targeted supplements. Sol must independently validate every `derived_solution`. A clean math review marks the supplement `math_review_status=verified` during apply.

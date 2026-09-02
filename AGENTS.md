# video_to_notes — Codex one-shot workflow

This repository converts a local course video into a visual-first, evidence-traceable LaTeX/PDF lecture note. Normal operation uses Codex handoff for semantic stages and does not require an external LLM API key.

## User-facing rule: one video path is enough

When the user gives a local video path and asks to process/convert it, **do not ask the user to manually run the individual stages**. Treat it as a request to finish the whole workflow.
If the user message is only a plausible local video file path (for example `.mp4`, `.mkv`, `.mov`, `.avi`, `.webm`) while working in this repository, interpret it as the same full-workflow request unless the user explicitly says otherwise.

Start with exactly one controller command:

```powershell
video-to-notes workflow "VIDEO"
```

The command is resumable and idempotent. Keep using the **same command** until it reaches a terminal workflow status.

### Controller statuses

The controller prints a block beginning with `=== VIDEO_TO_NOTES_WORKFLOW ===`.

#### `STATUS: CODEX_TASK_REQUIRED`

This is not a stop for the user. It means Codex must do the semantic handoff now.

1. Read `TASK_DIR/INSTRUCTIONS.md`.
2. Read `TASK_DIR/manifest.json`.
3. Read only the `*.request.json` files needed for the missing outputs. Responses whose exact `request_id` is already valid are intentionally reused and must not be regenerated.
4. Honor each request's `required_model` exactly.
5. Perform the reasoning yourself; do not call an external LLM API.
6. Write the exact JSON response files under `RESPONSE_DIR`.
7. Run the exact same command again:

```powershell
video-to-notes workflow "VIDEO"
```

The controller will validate/apply the responses and continue automatically.

#### `STATUS: WORKFLOW_COMPLETE`

The workflow is complete and Audit passed. Report the final `LATEX`, `PDF`, and `AUDIT_REPORT` paths to the user.

#### `STATUS: WORKFLOW_COMPLETE_REVIEW_REQUIRED`

LaTeX/PDF were generated, but Audit found blocking quality issues. Inspect `AUDIT_REPORT` and make a best effort to resolve actionable issues by rerunning the appropriate semantic stage through the workflow. If the issue is inherently unresolvable from the available video evidence, stop and report the limitation together with the generated PDF path. Never silently call a REVIEW_REQUIRED lecture final-quality.

## Pipeline owned by the controller

```text
visual          -> Python / ffmpeg
transcription   -> Whisper
evidence        -> Python
reconstruction  -> Codex / Terra
completion      -> Codex / Terra
review factual  -> Codex / Luna High
review math     -> Codex / Sol
review pedagogy -> Codex / Terra
render          -> Python / Jinja2 / XeLaTeX
audit           -> Python
```

The controller automatically:

- initializes/reuses the workspace;
- reuses only stages whose Stage Receipt is current and whose recorded outputs still match;
- runs visual/transcription/evidence in order;
- prepares reconstruction/completion/review handoffs when needed;
- reuses exact, schema-valid request responses after interruption/restart;
- applies completed handoff responses;
- invalidates stale downstream stages when an upstream semantic stage is regenerated;
- runs render and audit;
- writes `reports/workflow_report.json` after every controller invocation.


## Freeze architecture: Stage Receipt

`stages/<stage>.receipt.json` is the single authoritative execution/cache/dependency identity. Do not recreate a parallel `state.json`, cache key system, dependency DAG database, or handoff session framework.

A current receipt binds:

- stage version;
- direct upstream receipt identities (or a legacy artifact identity when upgrading an old workspace);
- relevant config;
- semantic prompt contents / render template contents;
- recorded output hashes.

If any of these change, the stage is stale and must be regenerated. Reports describe business results; receipts describe execution identity.

Every Codex response must echo **that individual request's** exact `request_id`. Never apply a response with a missing or stale `request_id`. Do not assume all requests in one stage share the same ID.

For reconstruction/completion, a merge response is reusable only when every chunk response it depends on was also reused. If any chunk is regenerated, regenerate the merge too.

## Model routing is mandatory

Every handoff request contains `required_model`.

```text
reconstruction       -> terra
completion           -> terra
review factual       -> luna-high
review math          -> sol
review pedagogical   -> terra
```

Luna must never be used below **Luna High**. Do not silently downgrade a request. If the current agent environment supports model-specific subagents/delegation, use the requested model. If it cannot honor a required model, do not pretend that it did; surface the limitation.

## Long-running command rule

Prefer blocking waits for ffmpeg, Whisper, XeLaTeX, and other fixed-duration subprocesses. Do not repeatedly query their progress at short intervals. If polling is unavoidable, use about 50 seconds between checks; never poll faster than 40 seconds or slower than 90 seconds unless the subprocess itself returns earlier.

## Global content rules

1. Visual evidence is primary. Transcript only supports interpretation.
2. Reconstruction answers: **what did the video/teacher actually contain?**
3. Completion answers: **what must be added for a complete independent lecture note?**
4. Review checks source fidelity, mathematics, and pedagogy separately.
5. Never silently overwrite teacher source content.
6. Added derivations are always `origin=supplement`; they are never teacher content.
7. Mathematical/special symbols in generated note content use standard LaTeX rather than Unicode math glyphs.
8. Important statements, problems, source answers, and teacher solution steps remain traceable to Evidence IDs.
9. If evidence is insufficient, preserve uncertainty. Do not fabricate source content.

## Reconstruction — visual binding is required

For geometry, diagrams, slides, tables, graphs, or any problem whose meaning depends on the picture:

- actually inspect the relevant frame image paths included in the request;
- populate `figure_evidence_ids` with real Evidence Segment IDs;
- do not invent frame/image paths;
- if the statement says `如图/图中/下图/图示/见图`, a figure binding should normally be present;
- geometry problems may still need a figure even when the statement does not literally say `如图`.

For each problem that needs solving/proving, set:

```json
{
  "requires_solution": true,
  "solution_completeness": "complete|incomplete|missing|uncertain|not_applicable"
}
```

If the teacher only started a proof, keep the teacher solution partial and mark `incomplete`. Reconstruction must not finish it.

## Completion — incomplete proofs must be completed

Critical rule:

> “Do not fabricate what the teacher said” does **not** mean “do not finish the mathematics.”

For every `requires_solution=true` problem whose effective completeness is `incomplete`, `missing`, or `uncertain`:

- if the statement/conditions are sufficient, Terra must independently produce a complete `type=derived_solution` supplement;
- it may continue from a useful teacher construction, but the added steps remain a lecture supplement;
- every nontrivial transformation/construction must be justified;
- do not output placeholders such as “similarly follows” when the missing proof is the main task;
- if evidence/conditions are genuinely insufficient, do not guess. Leave it unresolved so Audit blocks final PASS.

Completion must never modify the original `statement`, `teacher_solution`, or `teacher_answer`.

## Review

### factual / Luna High

Only verify source fidelity against Evidence. A mathematically wrong statement can still be factually faithful to the video.

### math / Sol

Independently verify mathematical correctness. For every `type=derived_solution` supplement:

- solve/check from the original problem conditions;
- inspect every key proof step;
- detect circular reasoning, use of the desired conclusion as an assumption, missing conditions, invalid congruence/similarity, bad calculations, etc.;
- if a derived solution is wrong, target the issue to its supplement id (`sup_XXX`) whenever possible;
- the math response must explicitly list every checked supplement id in `verified_supplements`; absence of an issue is not enough. `review apply` only marks explicitly verified supplements as `math_review_status=verified`.

Teacher mistakes remain source text and are reported as `possible_teacher_error`; never silently rewrite them as teacher content.

### pedagogical / Terra

Check independent readability, including:

- `如图`/geometry content without an actual figure;
- proof problems that have an answer but no complete teacher solution and no derived solution;
- supplement overuse or structural gaps.

## Render and Audit quality gates

Audit must not PASS when:

- a visually dependent problem has no actual bound figure;
- a required solution is incomplete/missing/uncertain and has no `derived_solution`;
- a `derived_solution` has not been verified by the math reviewer;
- review or LaTeX blocking errors remain.

## Direct stage commands

The old individual commands remain available for diagnosis and development, but they are not the normal user-facing workflow. Prefer `video-to-notes workflow "VIDEO"` whenever the user wants a complete conversion.

## API mode

Optional only when explicitly requested. The normal one-shot workflow must not require API keys.

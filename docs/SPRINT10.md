# Sprint 10 — Visual Binding + LLM Proof Completion

Sprint 10 closes two quality gaps found in a real lecture PDF:

1. problem images existed in visual evidence but were not reliably carried into the final PDF;
2. reconstruction correctly preserved an incomplete teacher proof, but completion did not necessarily finish the proof as an explicitly supplemental LLM derivation.

## Figure binding

LLM output only chooses `figure_evidence_ids`. Python resolves those Evidence Segment IDs to actual high-resolution evidence frames. This avoids model-generated file paths.

A render-time fallback infers figure evidence from statement evidence for strongly visual/geometry problems, which allows existing workspaces to gain figures without re-running visual/transcription.

## Derived solutions

Completion request chunks contain an inferred solution assessment. An incomplete/missing/uncertain proof with sufficient conditions should produce:

```json
{
  "target_id": "P03",
  "reason": "incomplete_explanation",
  "type": "derived_solution",
  "why_needed": "...",
  "derivation_basis": ["..."],
  "content": "..."
}
```

The original teacher fields remain unchanged. Derived solutions begin as `math_review_status=pending` and are only considered final after the Sol math review marks them verified by returning no blocking issue for that supplement/problem.

## Audit gates

Audit returns `REVIEW_REQUIRED` if:

- a visual problem lacks a figure;
- an incomplete/missing/uncertain required solution has no derived solution;
- a derived solution has not passed math review.

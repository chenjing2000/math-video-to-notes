# DATA_MODEL.md

# Core Data Model

本文件定义 V1 的核心数据结构。

设计原则：
- Evidence 与 Lecture 分离；
- Visual Segment 是证据时间轴主对象；
- `lecture.json` 是唯一正式内容源；
- 所有重要内容支持来源追溯；
- 不在 V1 过度设计 OCR/VLM 字段。

---

## 1. Metadata

```json
{
  "video_id": "lesson_001",
  "title": "课程标题",
  "source_path": "source/video.mp4",
  "duration": 3625.42,
  "width": 1920,
  "height": 1080,
  "fps": 30.0
}
```

---

## 2. TranscriptSegment

```json
{
  "id": "tr_0001",
  "start": 12.31,
  "end": 18.72,
  "text": "我们来看第一道题。",
  "confidence": 0.96
}
```

必须字段：
- id
- start
- end
- text

confidence 可选。

---

## 3. Frame

```json
{
  "id": "fr_00123",
  "time": 632.4,
  "path": "visual/evidence_frames/fr_00123.jpg",
  "source": "scene"
}
```

`source` 推荐：
- coverage
- scene
- dense
- manual

---

## 4. VisualSegment

视觉时间轴核心对象。

```json
{
  "id": "vs_0023",
  "start": 632.4,
  "end": 681.7,
  "visual_type": "progressive_board",
  "frames": [
    "fr_00123",
    "fr_00128",
    "fr_00135"
  ],
  "confidence": 0.91
}
```

`visual_type` 仅允许：

- stable_slide
- progressive_board
- dynamic_visual
- mixed
- unknown

---

## 5. EvidenceSegment

将 VisualSegment 与对应 transcript 对齐。

```json
{
  "id": "ev_0023",
  "visual_segment_id": "vs_0023",
  "start": 632.4,
  "end": 681.7,
  "frame_ids": [
    "fr_00123",
    "fr_00128",
    "fr_00135"
  ],
  "transcript_ids": [
    "tr_0110",
    "tr_0111",
    "tr_0112"
  ],
  "content_type": "problem_solution",
  "confidence": 0.90,
  "status": "confirmed"
}
```

`content_type` V1 推荐：

- intro
- concept
- definition
- theorem
- method
- problem
- problem_solution
- summary
- other
- unknown

---

## 6. Status

所有需要置信管理的内容统一使用：

- confirmed
- probable
- uncertain
- conflict

禁止私自增加相近状态名。

---

## 7. ContentOrigin

讲义内容来源统一使用：

- video
- reconstructed
- supplement

含义：

### video
视频中直接存在。

### reconstructed
只进行重排、精炼或书面化，不新增外部事实。

### supplement
新增了视频之外的教学知识或推导。

---

## 8. Section

```json
{
  "id": "sec_01",
  "title": "相似三角形基本模型",
  "type": "concept",
  "source_ranges": [
    [120.0, 360.0],
    [510.0, 565.0]
  ],
  "evidence_ids": [
    "ev_0004",
    "ev_0005",
    "ev_0011"
  ],
  "blocks": []
}
```

---

## 9. ContentBlock

```json
{
  "id": "blk_001",
  "type": "observation",
  "content": "连接 AC 后可以构造两组对应角。",
  "origin": "reconstructed",
  "evidence_ids": [
    "ev_0032"
  ],
  "status": "confirmed"
}
```

`type` 推荐：

- knowledge
- definition
- theorem
- property
- observation
- method
- explanation
- warning
- summary
- supplement

---

## 10. Problem

```json
{
  "id": "P01",
  "title": "例题 1",
  "statement": {
    "content": "……",
    "origin": "video",
    "evidence_ids": ["ev_0030"],
    "status": "confirmed"
  },
  "figure_ids": ["fig_001"],
  "analysis": {
    "content": "……",
    "origin": "reconstructed",
    "evidence_ids": ["ev_0031"],
    "status": "confirmed"
  },
  "teacher_solution": {
    "content": "……",
    "origin": "video",
    "evidence_ids": ["ev_0031", "ev_0032"],
    "status": "confirmed"
  },
  "supplement_solution": null,
  "teacher_answer": {
    "content": "40^\\circ",
    "origin": "video",
    "evidence_ids": ["ev_0033"],
    "status": "confirmed"
  },
  "review": {}
}
```

如果视频没有老师答案：

```json
"teacher_answer": null
```

不得用 AI 答案填入该字段。

---

## 11. Supplement

```json
{
  "id": "sup_001",
  "target_id": "P01",
  "reason": "incomplete_explanation",
  "why_needed": "老师直接从第二步跳到结论，缺少关键等角关系说明。",
  "content": "由……可得……",
  "origin": "supplement",
  "status": "confirmed"
}
```

`reason` 仅允许：

- missing_content
- incomplete_explanation
- unclear_explanation
- pedagogical_bridge

---

## 12. Figure

```json
{
  "id": "fig_001",
  "source_frame_id": "fr_00123",
  "source_time": 632.4,
  "evidence_path": "visual/evidence_frames/fr_00123.jpg",
  "publication_path": "images/p01.jpg",
  "usage": "problem_figure",
  "render_mode": "keep_original"
}
```

V1 `render_mode` 默认：
- keep_original

V1.5 可增加：
- crop
- redraw

---

## 13. ReviewIssue

```json
{
  "id": "rv_001",
  "target_id": "P03.teacher_answer",
  "review_type": "math",
  "severity": "warning",
  "status": "open",
  "source_value": "48^\\circ",
  "review_value": "46^\\circ",
  "reason": "按前述条件重新计算得到 46°。",
  "label": "possible_teacher_error"
}
```

`review_type`：
- factual
- math
- pedagogical

`status`：
- open
- resolved
- accepted_source
- accepted_review

---

## 14. Lecture JSON

最终唯一正式内容模型：

```json
{
  "schema_version": "1.0",
  "metadata": {},
  "overview": {
    "topic": "",
    "main_line": "",
    "core_methods": [],
    "learning_objectives": []
  },
  "sections": [],
  "problems": [],
  "supplements": [],
  "figures": [],
  "summary": [],
  "review": {
    "issues": []
  }
}
```

---

## 15. State JSON

```json
{
  "visual": "done",
  "transcription": "done",
  "evidence": "done",
  "reconstruction": "running",
  "completion": "pending",
  "review": "pending",
  "render": "pending",
  "audit": "pending"
}
```

阶段状态仅允许：

- pending
- running
- done
- failed
- skipped

---

## 16. Cache Metadata

每阶段至少记录：

```json
{
  "stage": "transcription",
  "input_sha256": "...",
  "config_hash": "...",
  "prompt_version": null,
  "model": "whisper-large-v3",
  "status": "done"
}
```

LLM 阶段必须记录：
- model；
- prompt_version；
- config_hash。

---

## 17. Quality Report

建议结构：

```json
{
  "status": "PASS",
  "sections": 7,
  "problems": 13,
  "figures": 17,
  "evidence_coverage": {
    "problems_total": 13,
    "problems_with_evidence": 13
  },
  "content_status": {
    "confirmed": 11,
    "probable": 2,
    "uncertain": 0,
    "conflict": 0
  },
  "supplements": 4,
  "review_open": 0,
  "latex_errors": 0,
  "missing_characters": 0,
  "missing_figures": 0
}
```

最终还应生成适合人工阅读的 `quality_report.md`。

## Sprint 10 fields

Problems may include:

```json
{
  "requires_solution": true,
  "solution_completeness": "complete|incomplete|missing|uncertain|not_applicable",
  "figure_evidence_ids": ["ev_0012"]
}
```

`figure_evidence_ids` contains Evidence Segment IDs only. Python resolves them to `lecture.figures` entries containing actual evidence frame ids/paths.

A mathematically derived completion is stored only as a supplement:

```json
{
  "id": "sup_001",
  "target_id": "P03",
  "reason": "incomplete_explanation",
  "type": "derived_solution",
  "why_needed": "...",
  "derivation_basis": ["..."],
  "content": "...",
  "origin": "supplement",
  "status": "probable",
  "math_review_status": "pending"
}
```

After a clean Sol math review, `math_review_status` becomes `verified` and `status` becomes `confirmed`.

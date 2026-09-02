# video_to_notes

`video_to_notes` 是一个视觉优先、证据驱动的课程视频 → LaTeX/PDF 讲义工作流。

核心原则：

> 视觉优先、音频辅助、证据驱动、课程重构、必要教学补全、数学独立复核、重要事实可追溯。

## 一键 Codex 工作流

正常使用时，用户不需要逐个执行 stage。只要在 Codex 中给出视频本地路径，例如：

```text
完整处理这个视频：E:\course\lesson.mp4
```

Codex 按根目录 `AGENTS.md` 执行统一控制器：

```powershell
video-to-notes workflow "E:\course\lesson.mp4"
```

控制器会自动推进：

```text
visual
→ transcription
→ evidence
→ reconstruction / Terra
→ completion / Terra
→ factual review / Luna High
→ math review / Sol
→ pedagogical review / Terra
→ render
→ audit
→ lecture.tex / lecture.pdf
```

当输出 `STATUS: CODEX_TASK_REQUIRED` 时，Codex 自己读取 task request、按 `required_model` 完成 JSON response，然后再次运行**同一条** `workflow` 命令。用户不需要手工执行 `prepare/apply`。

最终产物：

```text
workspace/<lesson>/latex/lecture.tex
workspace/<lesson>/output/lecture.pdf
workspace/<lesson>/reports/quality_report.md
workspace/<lesson>/reports/workflow_report.json
```

详细说明见：

```text
AGENTS.md
docs/CODEX_ONE_SHOT_WORKFLOW.md
```

## 模型路由

```text
reconstruction       -> terra
completion           -> terra
review factual       -> luna-high
review math          -> sol
review pedagogical   -> terra
```

Luna 不允许低于 Luna High。

## 环境

- Python >= 3.11
- ffmpeg / ffprobe
- XeLaTeX
- `faster-whisper`

推荐：

```powershell
cd video_to_notes
uv venv
.venv\Scripts\activate
uv pip install -e .
```

## 工作流特点

### Visual-first

先重建视频视觉内容，再用 Whisper 转录辅助解释。题目图、几何图、板书关键状态会进入 Evidence Timeline，并在 reconstruction 中绑定到真实 evidence frame。

### Reconstruction

只恢复老师/视频实际包含的内容。老师证明没有讲完时必须保留 `incomplete`，不得在此阶段伪造为老师完整证明。

### Completion

老师未讲、未讲完或未讲清但为了形成独立讲义必须补足的内容，由 Terra 以 `origin=supplement` 补充。证明题条件充分时必须生成完整 `derived_solution`。

### Review

- Luna High：事实忠实性；
- Sol：数学正确性及 derived solution 独立验算；
- Terra：结构、图文完整性和教学可读性。

### Render / Audit

Jinja2 生成标准 LaTeX，XeLaTeX 编译两次。Audit 会阻止以下内容被错误标记为 PASS：

- `如图`/几何题却没有实际插图；
- 必须解答的题只有答案，没有完整老师解法或 verified derived solution；
- derived solution 未经过数学审校；
- unresolved review / LaTeX blocking errors。

## 诊断命令

完整工作流优先使用：

```powershell
video-to-notes workflow "VIDEO"
```

仍保留以下低层命令用于开发和诊断：

```powershell
video-to-notes status "VIDEO"
video-to-notes codex-tasks "VIDEO"
video-to-notes visual "VIDEO"
video-to-notes transcribe "VIDEO"
video-to-notes evidence "VIDEO"
video-to-notes reconstruct prepare "VIDEO"
video-to-notes reconstruct apply "VIDEO"
video-to-notes complete prepare "VIDEO"
video-to-notes complete apply "VIDEO"
video-to-notes review prepare "VIDEO"
video-to-notes review apply "VIDEO"
video-to-notes render "VIDEO"
video-to-notes audit "VIDEO"
```

## v1.2 Freeze 可靠性机制

- `stages/*.receipt.json`：唯一的阶段状态、缓存和依赖身份；
- `request_id`：Codex handoff 响应防串台；
- `lecture/reconstruction.json`、`completed.json`、`reviewed.json`：语义阶段不可变快照；
- Sol 必须通过 `verified_supplements` 逐条确认 LLM 补充证明；
- 同名但内容不同的视频自动分离 workspace；
- prompts/default config/LaTeX template 内置为 package resources，不依赖当前工作目录；
- `golden/` 保存两个真实视频的轻量回归契约。


## 测试

普通测试：

```powershell
pytest -q tests --ignore=tests/integration
```

包含 XeLaTeX 的集成测试建议逐文件运行，避免多个外部子进程堆在同一个 pytest 进程中。

当前版本：`1.2.0`（个人自用冻结版）。

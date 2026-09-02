# WORKFLOW.md

# Video-to-Lecture Workflow

## 1. 目标

将课程视频重建为一份结构完整、逻辑清晰、可独立阅读、重要事实可追溯到原视频的高质量讲义。

本工作流不是“字幕总结”，也不是“视频逐字稿”。它首先尽可能完整地恢复课程中的视觉与语音信息，再重建课程结构，最后允许 LLM 对未讲、未讲完或未讲清的内容进行最小必要教学补充。

---

## 2. 最高层原则

### 2.1 视觉优先，音频辅助

视频视觉信息是课程事实恢复的主线。

优先恢复：
- 课件页面；
- 完整题面；
- 几何图、示意图、图表；
- 板书新增与擦除过程；
- 动态演示中的关键状态；
- 老师没有口头读出的屏幕信息。

音频与 Whisper 主要用于：
- 解释视觉内容；
- 理解老师的讲解意图；
- 补充屏幕上没有写出的口头说明；
- 帮助判断视觉片段属于知识点、题目、解答还是总结。

禁止使用音频先决定“哪里值得看视频”，然后只在少数位置截图。

### 2.2 前期多保留，后期再筛选

证据提取阶段以“不漏”为优先，不以最终讲义简洁为优先。

允许内部 Evidence 保存大量候选帧和板书过程。
最终放入讲义的 publication images 可显著少于 Evidence images。

### 2.3 证据层禁止补知识

Evidence 层只负责：
- 记录；
- 对齐；
- 分类；
- 建立来源。

Evidence 层禁止：
- 补充课程知识；
- 替老师完成推导；
- 纠正老师；
- 重新解题；
- 根据模糊内容猜测题目条件或数字。

### 2.4 课程事实与讲义补充必须分离

所有讲义内容的 `origin` 必须属于：

- `video`：视频中直接存在的课程内容；
- `reconstructed`：仅重排、改写或补足表达，不新增外部事实；
- `supplement`：为教学完整性新增的知识、解释、推导或桥接内容。

任何 `supplement` 都不得伪装为老师原话、老师原解或原视频内容。

### 2.5 最小充分补充

允许 LLM 补充：
- 视频未讲但理解当前课程必需的内容；
- 老师讲了但没有讲完的部分；
- 老师讲了但表达不清的部分；
- 明显跳步的推导；
- 前后知识之间缺失的必要逻辑桥梁。

补充必须满足：
1. 不补会影响学生理解当前课程；
2. 补充范围只达到理解当前课程所需的最低程度；
3. 不扩张成与当前课程无关的教材内容。

### 2.6 重要事实必须可追溯

至少以下内容必须绑定 Evidence：
- 题目条件；
- 数字；
- 图形；
- 老师给出的答案；
- 老师给出的关键公式；
- 老师板书的结论；
- 与视频内容直接相关的重要判断。

---

## 3. 总体流水线

```text
VIDEO
  ↓
1. Visual Reconstruction
  ↓
Visual Timeline
  ↓
2. Audio / Whisper
  ↓
3. Multimodal Evidence Timeline
  ↓
4. Course Reconstruction
  ↓
5. Pedagogical Completion
  ↓
6. Review
  ↓
lecture.json
  ↓
7. Rendering
  ↓
LaTeX / PDF
  ↓
8. Audit
```

---

## 4. 阶段 1：Visual Reconstruction

### 4.1 视频探测

读取：
- 总时长；
- 分辨率；
- 帧率；
- 音轨；
- 视频标题与来源元数据。

### 4.2 Coverage Frames

按固定间隔抽取低成本概览帧，用于保证整段视频没有完全未观察区域。

推荐默认间隔：45 秒。

Coverage Frame 不是最终关键帧，只是覆盖兜底。

### 4.3 Visual Change Detection

检测：
- PPT 换页；
- 新题目出现；
- 黑板新增内容；
- 黑板擦除；
- 几何图变化；
- 软件操作变化；
- 动画或实验状态变化。

### 4.4 Visual Segment Classification

每个视觉片段至少分类为：

- `stable_slide`
- `progressive_board`
- `dynamic_visual`
- `mixed`
- `unknown`

不同类型采用不同保存策略：

#### stable_slide
强去重，仅保留一张或少量代表帧。

#### progressive_board
弱去重，必须保留能体现推导演化的关键状态：
- 初始题面；
- 关键中间步骤；
- 最终板书。

#### dynamic_visual
按关键状态变化保留多个帧。

### 4.5 去重顺序

禁止在视觉类型判断之前简单强去重。

推荐顺序：

```text
候选帧
↓
视觉片段分类
↓
按片段类型选择不同去重强度
↓
Evidence Frames
```

V1 可使用 pHash 或 SSIM 中的一种作为主要去重算法。

---

## 5. 阶段 2：Audio / Whisper

提取音频并生成带时间戳的 transcript。

至少输出：
- `transcript.json`
- `transcript.srt`
- `transcript.txt`

`transcript.json` 必须保留：
- segment id；
- start；
- end；
- text。

Whisper 的作用是辅助解释 Visual Segment，而不是决定哪些视频区域值得保留。

---

## 6. 阶段 3：Multimodal Evidence Timeline

以 `VisualSegment` 为主对象，将对应时间段的 transcript 挂接到视觉片段上。

每个 Evidence Segment 至少包含：
- segment id；
- start / end；
- visual type；
- frame list；
- transcript；
- content type；
- confidence；
- source paths。

V1 不要求 OCR 或复杂 VLM。
OCR / VLM 可在 V1.5 作为可选字段加入。

Evidence 层不得写入 `supplement` 内容。

---

## 7. 阶段 4：Course Reconstruction

第一次 LLM 内容理解阶段只做课程结构恢复，不直接生成最终 LaTeX。

需要识别：
- 课程主题；
- 章节；
- 知识点；
- 定义；
- 方法；
- 例题；
- 解答；
- 总结。

允许将同一知识点在视频中分散出现的内容合并。

课程结构可以优于课堂口语顺序，但必须保留 `source_ranges` 与 `evidence_ids`。

### 7.1 题目一级建模

每道题必须单独建立 Problem 对象。

至少保存：
- `statement`
- `figure`
- `teacher_solution`
- `teacher_answer`
- `evidence_ids`
- `status`

不得根据常识猜测视频中看不清的题目数字。

---

## 8. 阶段 5：Pedagogical Completion

对课程进行完整性检查。

检查：
- 定义是否完整；
- 公式是否有适用条件；
- 推导是否跳步；
- 题目是否只有答案没有分析；
- 前后知识是否缺桥梁；
- 老师是否出现明显“没讲完”或“没讲清”。

补充原因仅允许：

- `missing_content`
- `incomplete_explanation`
- `unclear_explanation`
- `pedagogical_bridge`

每个 supplement 必须记录：
- reason；
- affected section/problem；
- content；
- why_needed；
- origin=`supplement`。

---

## 9. 阶段 6：Review

使用能力路由，不绑定具体模型名。

### factual reviewer

负责：
- 视频事实一致性；
- 题目条件；
- 数字；
- 老师答案；
- 视频与 lecture.json 的证据支持关系。

### math reviewer

负责：
- 公式正确性；
- 推导正确性；
- 证明逻辑；
- 计算结果；
- 符号一致性。

若老师原内容疑似有错误，不得静默覆盖老师内容。
应保留 source content，并记录 `possible_teacher_error`。

### pedagogical editor

负责：
- 章节结构；
- 去除口语重复；
- 关键观察；
- 方法提炼；
- 易错点；
- 补充内容是否过量。

---

## 10. 审校触发规则

不要机械地让所有模型串行运行全部内容。

建议：
- `confirmed`：一般不触发事实复核；
- `probable`：触发事实复核；
- `uncertain`：必须复核；
- `conflict`：必须解决；
- 数学公式、证明、数学题：触发 math reviewer；
- 整份讲义：最终可运行一次 pedagogical editor。

---

## 11. 阶段 7：Rendering

唯一正式内容源是 `lecture.json`。

禁止让 LLM 直接生成整份最终 LaTeX。

采用：

```text
lecture.json
↓
Jinja2
↓
lecture.tex
↓
XeLaTeX × 2
↓
lecture.pdf
```

以后 Markdown、HTML、Anki 等输出也必须从 `lecture.json` 派生。

---

## 12. 阶段 8：Audit

Audit 分四类：

### Evidence Audit
- 所有重要题目是否有 Evidence；
- 关键数字是否可追溯；
- 所有引用图片是否存在；
- 时间戳是否合法。

### Content Audit
- 是否漏题；
- 是否存在空章节；
- Problem ID 是否重复；
- 是否存在 unresolved conflict。

### Supplement Audit
- supplement 是否显式标记；
- 是否有 reason；
- 是否存在 AI 补充冒充视频内容；
- 是否超过“最小充分补充”。

### LaTeX Audit
硬性要求：
- LaTeX error = 0；
- Undefined control sequence = 0；
- Missing character = 0；
- Missing image = 0。

---

## 13. 状态机

每阶段状态仅允许：

- `pending`
- `running`
- `done`
- `failed`
- `skipped`

阶段完成后写入 `state.json`。

重新执行时：
- 输入与配置未变化；
- 阶段状态为 done；
- cache hash 匹配；

则必须复用已有结果，不重复运行。

---

## 14. 缓存

至少分层缓存：
- video metadata；
- transcript；
- frames；
- evidence；
- reconstruction；
- completion；
- reviews；
- render。

仅修改 LaTeX 模板时，不得重新执行 Whisper、抽帧或 LLM 分析。

---

## 15. 长耗时任务等待规则

对 ffmpeg、Whisper、模型审校、LaTeX 等长耗时任务：

- 优先阻塞等待；
- 不允许通过高频 `status` 查询制造轮询；
- 若必须轮询，默认间隔 50 秒；
- 禁止低于 40 秒；
- 禁止高于 90 秒；
- 若程序本身可以等待子进程结束，则不要额外轮询。

---

## 16. V1 范围

V1 实现：
- 本地视频；
- coverage；
- scene/change detection；
- visual segment；
- 简单去重；
- Whisper；
- visual/transcript alignment；
- Evidence Timeline；
- Course Reconstruction；
- Problem Reconstruction；
- Pedagogical Completion；
- factual/math/editor review；
- lecture.json；
- Jinja2；
- XeLaTeX；
- Audit；
- 状态恢复；
- 分层缓存。

V1 暂不实现：
- 网络视频下载；
- 高级 OCR；
- 数学公式 OCR；
- 自动裁图；
- 自动重绘；
- 互动 HTML；
- Zotero；
- Anki；
- 知识图谱。

---

## 17. 完成标准

一节课程只有在以下条件全部满足时才为 PASS：

1. 整个视频视觉覆盖满足配置要求；
2. Transcript 具有完整时间轴；
3. Evidence Timeline 构建成功；
4. 所有重要题目具有 evidence；
5. unresolved conflict = 0；
6. 所有 supplement 均有明确来源标记；
7. LaTeX 编译成功；
8. Missing character = 0；
9. Missing image = 0；
10. 生成 `quality_report.md`；
11. 生成最终 `lecture.tex` 与 `lecture.pdf`。

## Sprint 10 semantic split

```text
Teacher/video evidence
        |
        v
Reconstruction: preserve source + mark incomplete + choose figure evidence
        |
        v
Completion: add explicit derived_solution where required
        |
        v
Math Review (Sol): independently verify derived_solution
        |
        v
Render: resolve/copy evidence figures + render source/supplement separately
        |
        v
Audit: block missing figures or unverified incomplete solutions
```

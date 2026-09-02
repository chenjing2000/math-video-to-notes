# QUALITY_RULES.md

# Quality Rules

本文件定义视频讲义工作流中的硬性质量红线。
任何 Agent、LLM、脚本或审校器都必须遵守。

---

## 1. 事实红线

### Q1. 禁止虚构题目条件

看不清的：
- 数字；
- 字母；
- 长度；
- 角度；
- 选项；
- 图形标记；

不得根据常识猜测。

应标记：
- probable；
- uncertain；
- conflict。

### Q2. 禁止虚构老师答案

视频没有给出答案时，不得把 AI 解出的答案标为老师答案。

可另写：
- `teacher_answer = null`
- `supplement_answer = ...`

### Q3. 禁止静默修改老师内容

若老师疑似写错或算错：

必须保留原视频内容，并记录：
- `possible_teacher_error`
- math reviewer 建议。

禁止直接覆盖。

### Q4. 所有主要题目必须有 Evidence

每道主要题目至少绑定一个 `evidence_id`。
题面、图、答案最好分别有可追溯证据。

---

## 2. 视觉红线

### Q5. 禁止以音频决定全部截图位置

视觉分析必须独立覆盖整个视频。

Whisper 只能辅助解释，不得成为视觉证据选择的唯一主线。

### Q6. 禁止过早强去重板书过程

Progressive Board 不能只保留最终状态。

若中间步骤具有教学意义，必须保留其关键演化帧。

### Q7. 禁止把截图数量当成质量目标

不要求“至少 15 张”等固定数量。
应根据课程内容决定。

---

## 3. 补充红线

### Q8. Supplement 必须显式标记来源

所有新增教学内容：
- origin = supplement；
- 必须记录 reason。

### Q9. Supplement 不得冒充老师原话或原解

以下表达必须区分：
- 老师解法；
- 讲义补充解法；
- 审校建议。

### Q10. Supplement 必须满足最小充分原则

补充必须直接服务于理解当前课程。

禁止：
- 无关扩展；
- 大段百科式背景；
- 为展示模型能力而增加额外解法；
- 将一节视频讲义扩张成完整教材章节。

---

## 4. 课程重构红线

### Q11. 可以重排表达，不可改变事实

允许：
- 合并分散知识点；
- 删除重复口语；
- 完成跳跃表达；
- 改善章节逻辑。

禁止：
- 改题；
- 改数字；
- 改老师结论而不标记；
- 新增视频没有涉及的主主题。

### Q12. reconstructed 不得新增外部事实

如果新增了视频之外的知识，必须使用 supplement，而不是 reconstructed。

---

## 5. 数学红线

### Q13. 数学审校不能覆盖 Source

若老师原推导有错误，Source 与 Review 必须并存。

### Q14. 推导补全必须保持前提一致

不得在补全过程中偷偷加入题目没有的假设。

### Q15. 变量与符号必须一致

同一问题中不得无理由改变：
- 点名；
- 变量；
- 单位；
- 角标；
- 函数符号。

---

## 6. Evidence 红线

### Q16. Evidence 层禁止生成补充知识

Evidence 只允许记录原视频信息。

### Q17. Evidence 不确定性不得被下游静默抹除

如果源 Evidence 是 uncertain 或 conflict，下游不能直接变成 confirmed，除非经过明确审校并记录理由。

### Q18. 重要事实必须能回到原视频

至少要能定位到：
- 时间段；
- 相关视觉帧；
- 相关 transcript（若有）。

---

## 7. 审校红线

### Q19. unresolved conflict > 0 时不得 PASS

存在未解决冲突时：
- 可以生成草稿；
- 不得标记为最终通过。

### Q20. factual reviewer 与 math reviewer 职责分离

事实审校回答：
> 视频是不是这样说/写的？

数学审校回答：
> 这样说/写在数学上是否正确？

二者结论不得混为一谈。

---

## 8. LaTeX 红线

最终正式讲义必须满足：

- LaTeX Error = 0
- Undefined control sequence = 0
- Missing character = 0
- Missing image = 0

XeLaTeX 默认编译两遍。

带圈数字等字符必须使用模板中兼容的 CJK 设置。

---

## 9. 运行红线

### Q21. 已完成且缓存有效的阶段不得重复执行

除非：
- 输入变化；
- 配置变化；
- prompt version 变化；
- 用户明确 reset；
- cache invalid。

### Q22. 禁止高频轮询长任务

长任务优先阻塞等待。

若必须轮询：
- 默认 50 秒；
- 不低于 40 秒；
- 不高于 90 秒。

---

## 10. 最终 PASS 条件

只有同时满足以下条件才能 PASS：

- 视觉覆盖完成；
- Transcript 时间轴完整；
- Evidence Timeline 有效；
- 主要题目均有 Evidence；
- supplement 来源标记完整；
- unresolved conflict = 0；
- 重要数学内容经过必要审校；
- LaTeX 编译成功；
- Missing character = 0；
- Missing image = 0；
- quality_report.md 已生成。

## Sprint 10 blocking gates

The final Audit must return `REVIEW_REQUIRED` when any of the following is true:

- a visually dependent/geometry problem has no bound publication figure;
- a required problem solution is incomplete, missing, or uncertain and no `derived_solution` supplement exists;
- a `derived_solution` exists but has not been independently verified by the math reviewer;
- existing review or LaTeX blocking errors remain.

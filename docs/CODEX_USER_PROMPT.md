# Codex user prompt

正常情况下只需要把视频路径告诉 Codex：

```text
E:\pywork\学而思数学讲义\视频\倍长中线2.mp4
```

或者更明确地说：

```text
按照项目 AGENTS.md 的完整工作流处理这个视频，直到生成并审计 LaTeX/PDF：
E:\pywork\学而思数学讲义\视频\倍长中线2.mp4
```

Codex 应自行运行：

```powershell
video-to-notes workflow "VIDEO"
```

并在每个 `CODEX_TASK_REQUIRED` 节点自己完成 handoff、再次调用同一条 workflow 命令，直到输出 `WORKFLOW_COMPLETE`，或已经生成 PDF 但 Audit 明确给出无法从现有证据自动解决的 `REVIEW_REQUIRED`。

用户不需要手工执行 reconstruction/completion/review 的 prepare/apply 命令。

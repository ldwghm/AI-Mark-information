# Codex Web Scheduled 设置与迁移

## 当前交付状态

仓库已经具备 Codex 云端影子运行所需的 GitHub 侧能力。Codex 更新 trigger 文件后，GitHub Actions 会立即抓取对应时段的数据，并把本次 `request_id` 写进 latest。影子候选位于 `stock_report/data/shadow/`，不会触发邮件。

本地 IDE/CLI 不能创建或管理 Web Scheduled。下面两项任务需要在 ChatGPT Web 或桌面端的 Scheduled 页面创建；创建后电脑可以关机。

## 前置条件

1. 在 ChatGPT 中连接能够访问 `ldwghm/AI-Mark-information` 的 GitHub 账号。
2. 允许该连接器读取和更新仓库内容。影子方案不要求把 PAT 写进 prompt，也不依赖 Actions write 权限。
3. 保留现有 Claude 生产 routine，直到至少完成 5 个交易日的影子对比。

## 创建两项影子任务

早报任务设为北京时间工作日 08:30，任务正文使用：

```text
使用已连接的 GitHub 连接器读取仓库 ldwghm/AI-Mark-information 的 main 分支文件 stock_report/prompts/codex_morning_prompt.md，并逐条执行其中的完整影子任务。不要把文件内容只做摘要。任何触发、轮询或提交失败时停止并报告实际失败点，不得改写正式候选或发送邮件。
```

午报任务设为北京时间工作日 14:00，任务正文使用：

```text
使用已连接的 GitHub 连接器读取仓库 ldwghm/AI-Mark-information 的 main 分支文件 stock_report/prompts/codex_afternoon_prompt.md，并逐条执行其中的完整影子任务。不要把文件内容只做摘要。任何触发、轮询或提交失败时停止并报告实际失败点，不得改写正式候选或发送邮件。
```

创建前各手动运行一次，确认连接器写操作不需要运行中临时批准。云端调度通常不保证精确到分钟；报告中必须保留实际 `requested_at` 和 `fetch_time`。

## 每日验收

每个时段检查以下四项：

1. `stock_report/triggers/{mode}.json` 出现新的 Codex request ID。
2. 对应 latest 的 `orchestration_request.request_id` 与 trigger 完全相同。
3. `fetch_time` 不早于 `requested_at`，且影子候选引用相同 request ID。
4. 只有 shadow candidate 更新，没有触发 `send-report*.yml` 邮件 workflow。

连续记录数据年龄、缺失市场、分析结构、上一期复盘和失败原因。至少观察 5 个交易日，再决定是否切换。

## 生产切换门禁

生产切换必须按以下顺序执行：

1. 确认两个时段的影子运行均稳定，并保存对比结论。
2. 先停用对应 Claude routine，确保同一时段只有一个分析调度器。
3. 再把 Codex 输出目标从 shadow candidate 改为正式 candidate；正式路径更新会触发校验和邮件发送。
4. 当天人工核对 `verdict.json`、`delivery.json`、归档 manifest 和收件箱。

不要在 Claude routine 仍启用时让 Codex 写正式 candidate，否则可能重复发信或互相覆盖。切换生产属于独立变更，应另做一次小提交和验证。

## 故障恢复

- trigger 更新失败：检查 GitHub 连接器 Contents write 权限，不要把 PAT 粘进任务。
- 8 分钟仍无匹配快照：查看对应 fetch workflow；保持影子候选不变。
- latest 有新数据但 request ID 不匹配：视为关联失败，不提交分析。
- Actions 抓数失败：可手动运行原有 workflow_dispatch；这不会替代 Connector request 的影子验收。
- 准点性仍不足：再引入 Cloudflare Cron 等专用调度器，只替换触发时钟，不迁移分析和邮件逻辑。

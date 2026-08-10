# Codex Cloud 早报影子任务

在 GitHub 仓库 `ldwghm/AI-Mark-information` 的 `main` 分支执行 `stock_report/prompts/morning_prompt.md` 的完整生产 playbook。

约束：

- 使用已连接的 GitHub 身份，不在日志或提交中输出凭据。
- 只产出 `morning_latest.json` 和 `morning_analysis_candidate.json`；邮件、最终 analysis 和归档全部交给 GitHub Actions。
- 必须报告本次 `request_id`、匹配的 workflow run ID、snapshot freshness、候选 commit SHA；缺少 Actions write 或 Contents write 权限时明确失败点并停止。
- 本任务处于影子验证期。在用户明确切换前，不与 Claude 生产任务同时向同一候选路径写入；影子运行改用临时分支并只比较候选，不触发发信。

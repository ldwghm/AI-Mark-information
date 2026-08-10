# GitHub Actions 运维说明

## 生产边界

- `fetch-market-data*.yml` 只负责抓数并提交 latest 文件。
- 云端模型只提交 `*_analysis_candidate.json`。
- `send-report*.yml` 在同一个 job 内完成 verify、render/send、finalize、archive，避免依赖 `GITHUB_TOKEN` 提交后再次触发另一条 workflow。
- `pipeline-health.yml` 检查当日 latest 与 archive 中的 `delivery.json`。

## 手动恢复

1. 手动运行对应 fetch workflow，填写唯一 `request_id`。
2. 确认 run title 含该 ID，且 latest 的 `fetch_time` 晚于 dispatch。
3. 修复或重新提交对应 candidate 文件；candidate push 会自动触发发送。
4. 在当日 archive 中核对 `verdict.json`、`delivery.json` 与 `manifest.json`。
5. 不要直接修改 final analysis 触发邮件；final 文件由发送 workflow 生成。

## 失败语义

- verify `0`：通过，可能带软降级。
- verify `2`：硬失败；仍发送，但 HTML 显示红色校验失败横幅并将退出码写入邮件回执。
- 其他退出码：工作流中止，不发送。
- Resend 失败：不产生送达回执，health workflow 后续告警。

## 并发

早报与午报分别使用独立 concurrency group。归档提交前会恢复 workflow 对候选文件的本地校验写回，再执行 `git pull --rebase`，降低与抓数提交并发冲突的概率。

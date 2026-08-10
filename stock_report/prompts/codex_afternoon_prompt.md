# Codex Web Scheduled 午报影子任务

运行模式：`shadow`。北京时间工作日约 14:00 执行。仓库为 `ldwghm/AI-Mark-information`，分支为 `main`。全程只使用已连接的 GitHub 连接器，不使用 shell、PAT 或自行构造 GitHub API 请求。

## 安全边界

- 影子任务只写 trigger 和 `stock_report/data/shadow/afternoon_analysis_candidate.json`，不触发发信。
- 不修改正式候选、最终 analysis、archive 或邮件回执。
- 只接受本次 request 对应的新快照；超时或关联失败时停止，不用旧数据补交候选。
- 今日盘中价、昨收和缓存数据必须区分；事实与 `social_signal` 分层。

## 1. 通过 Connector 触发抓数

1. 用 GitHub 连接器 `fetch_file` 读取 `stock_report/triggers/afternoon.json`（`ref=main`），取得当前内容和 blob SHA。
2. 生成 `request_id=codex-afternoon-<UTC YYYYMMDDTHHMMSSZ>-<8位随机串>`，记录当前 UTC `requested_at`。
3. 用 `update_file` 原子替换同一路径，branch 为 `main`，sha 使用上一步取得的 SHA，完整内容为：

```json
{
  "schema_version": 1,
  "mode": "afternoon",
  "request_id": "本次唯一ID",
  "requested_at": "ISO-8601 UTC",
  "requested_by": "codex-scheduled"
}
```

保存连接器返回的 trigger commit SHA。

## 2. 只读取本次新快照

用 `fetch_file` 读取 `stock_report/data/afternoon_latest.json`。若尚未满足下列全部条件，则每 15 秒重读一次，最多 8 分钟：

- `report_type == "afternoon"`；
- `orchestration_request.request_id` 与本次 `request_id` 精确相等；
- `orchestration_request.requested_at` 与本次请求一致；
- `fetch_time` 不早于 `requested_at`。

超时或字段不符时，报告实际 request ID、trigger commit SHA 和最后看到的快照状态，然后停止，不提交影子候选。

## 3. 生成分析候选

通过 `fetch_file` 读取：

- `stock_report/prompts/afternoon_prompt.md`；
- `stock_report/data/morning_analysis.json`（今日早报 final）；
- `stock_report/data/afternoon_analysis.json`（上一期午报 final）；
- 本次匹配的 `afternoon_latest.json`。

只执行生产 playbook 的分析要求与 JSON schema，不执行其中 Step 0、Step 1 的 shell 抓取和 Step 3 的 token 提交。检验早报情景，分析技术面/基本面/情绪面是否相互确认，调查异常与跨市场背离，维护稳定 thesis，并给出盘中、下一交易日和一周概率情景。把 `orchestration_status` 写成包含本次 `request_id`、`requested_at`、trigger commit SHA、`state=completed`、`conclusion=success` 和快照 freshness 的对象。所有价格与涨跌幅逐字取自本次 latest。

## 4. 提交影子结果

先验证候选是可解析 JSON、概率合计 100、证据 ID 可追溯。再用 `fetch_file` 读取 `stock_report/data/shadow/afternoon_analysis_candidate.json` 获取当前 SHA，用 `update_file` 将完整候选 JSON 写回该路径，提交信息为 `shadow: codex afternoon candidate <YYYY-MM-DD>`。

最终只报告：request ID、trigger commit SHA、latest 的 fetch_time、freshness、影子候选 commit SHA 和降级项。不得把影子任务描述成已经发送邮件。

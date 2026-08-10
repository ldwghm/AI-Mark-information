# Codex Web Scheduled 连接器触发设计

## 目标与边界

让 Codex Web Scheduled 在用户电脑关机时也能启动早报和午报链路，同时不依赖模型运行阶段不可用的 `GH_PAT/GITHUB_TOKEN`。GitHub 继续负责确定性抓数、校验、发信和归档；Codex 只通过已连接的 GitHub 身份提交触发请求和候选分析。迁移先采用影子模式，避免 Claude 与 Codex 同时写生产候选而重复发信。

## 方案比较与选择

1. 直接调用 `workflow_dispatch`：沿用现有生产 playbook，但需要 Actions write token，和 Codex 云端凭据边界冲突。
2. GitHub Connector 更新固定触发文件：连接器只需 Contents write；文件 push 立即触发抓数 workflow，输出快照携带本次 `request_id`。这是本次采用的最小方案。
3. Cloudflare Cron 调用 GitHub API：可获得更稳定的准点触发，但增加新的部署面和密钥管理，留作时钟精度不足时的后续选项。

## 数据流与契约

Codex 读取 `stock_report/triggers/{mode}.json` 及其内容 SHA，生成唯一 `request_id` 和 UTC `requested_at` 后原子更新该文件。对应 GitHub Actions 监听 trigger 路径的 push，完成行情抓取，再由 `stock_report.connector_trigger` 校验 trigger 并把请求元数据写入 latest 的 `orchestration_request`。Codex 每 15 秒读取 latest，最多等待 8 分钟，只接受模式正确且 `orchestration_request.request_id` 精确匹配的快照。

影子期候选写到 `stock_report/data/shadow/{mode}_analysis_candidate.json`，不会命中发信 workflow 的路径过滤器。切换生产时只把 Codex prompt 中的目标路径改为正式 candidate，并先停用对应 Claude routine。候选内容仍遵守已有分析 schema，由 GitHub Actions 完成 verify、render/send、finalize 和 archive。

## 失败处理与验收

trigger 缺字段、模式不符或 JSON 无效时，抓数 workflow 失败且不提交带错误关联的快照。Codex 超时、latest 请求 ID 不匹配、快照时间早于请求时间或连接器无写权限时，停止候选提交并明确报告失败点。验收包括：早午 trigger 路径可独立触发、快照精确携带请求元数据、Codex prompt 不再依赖 PAT 或 workflow run API、影子候选不会触发邮件、现有 workflow_dispatch 和 schedule 仍可使用。

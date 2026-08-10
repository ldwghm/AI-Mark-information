# AI 市场报告可靠性与连续分析设计

## 目标

在不引入付费行情 API 的前提下，先解决三类基础问题：定时任务是否真正执行不可见、主动 dispatch 可能误认旧 run、报告只保留 latest 导致复盘断链。后续多市场、新闻与基本面扩展必须建立在这层可靠性底座上。

## 方案选择

采用“GitHub 为确定性数据与交付平面，Claude/Codex 为可替换分析平面”的增量方案。

- GitHub Actions 负责抓数、验证、渲染、发信、归档和健康记录。
- Claude routine 与 Codex Scheduled 都只负责读取数据并提交候选分析，不直接发信。
- 候选分析进入 GitHub 后，由同一个 workflow 运行 `verify.py`，再使用本次候选文件渲染和发信。
- 每次成功运行保存按日期与时段命名的不可变快照；`latest` 只作为便捷指针。
- Cloudflare Cron 后续只负责准时调用 GitHub workflow，不保存行情或分析逻辑。

## 数据流

1. 外部调度器触发抓数 workflow，并传入唯一 `request_id`。
2. 抓数 workflow 的 `run-name` 包含 `request_id`，云端分析任务只接受本次 dispatch 之后、ID 匹配且成功完成的 run。
3. 分析任务读取当次数据、上一期分析和连续状态，生成 `*_analysis_candidate.json`。
4. candidate push 触发处理 workflow：确定性校验 → 本地渲染 → Resend 发信 → 写入 final、archive 与运行状态。
5. 健康检查验证 expected date、fetch time、analysis date、delivery status 和源覆盖率；失败时只发送运维告警，不伪造正常报告。

## 连续性与成长机制

归档目录按 `stock_report/data/archive/YYYY-MM-DD/<mode>/` 保存 data、analysis、verdict 与 delivery status。后续阶段增加两个稳定状态文件：

- `thesis_ledger.json`：主题、首次提出日期、证据、反证、状态和下一观察点。
- `forecast_ledger.json`：预测对象、方向、期限、置信度、验证值、误差和错误分类。

日报只更新仍活跃或被新证据改变的主题。次日先用确定性价格结果给上一期预测结算，再允许模型解释原因；周报从 ledger 生成方法修订，避免模型自行宣称“已吸取教训”。

## 风险边界

- “消息及时性优先”不等于允许旧行情伪装成实时行情。所有数值必须携带 `observed_at`、`market_date`、`source` 与 freshness 状态。
- 小作文和博主观点属于 `social_signal`，必须与官方事件、行情事实分栏，不参与硬事实校验。
- 本阶段不引入付费数据源，不承诺韩股、日股和基本面实时覆盖；这些列入下一阶段适配器扩展。
- Codex 网页 Scheduled 可在关机时运行，但当前会话没有 Scheduled 管理入口；仓库改造完成后需在网页端创建并先做影子运行。

## 验收标准

- 旧 `workflow_dispatch` run 不能被误认为本次 run。
- 候选分析使用本次 checkout 文件验证和渲染，不读取远端旧 final。
- 一次邮件处理产生可追溯的 data、analysis、verdict 与 delivery 状态。
- Claude/Codex 两种提示词写入同一 candidate 契约。
- 单元测试覆盖 dispatch 关联、快照新鲜度、本地输入优先和归档路径。

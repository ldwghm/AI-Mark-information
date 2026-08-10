# AI-Mark-information

自动生成并邮件发送 AI 产业链市场早报、午报。生产链路把“定时分析”和“可靠交付”拆开：Claude Code 或 Codex 只生成候选分析，GitHub Actions 负责抓数、校验、渲染、发送和归档。

## 当前链路

```text
Claude Code routine（生产）/ Codex Scheduled（影子评估）
  → 带 request_id 主动 dispatch 抓数 workflow
  → 只接收与本次 request_id 匹配的 run，并校验 snapshot 新鲜度
  → 生成 latest.json + analysis_candidate.json
  → GitHub Actions 校验候选
  → 使用 checkout 中同一份 latest/candidate 渲染并通过 Resend 发送
  → 写 final analysis + 按日期归档数据、分析、verdict、HTML、邮件回执和 SHA-256 manifest
```

GitHub 的 `schedule` 仍作为数据预取兜底，不再承担准点触发生产报告的职责。

## 关键文件

| 文件 | 作用 |
|---|---|
| `stock_report/orchestration.py` | 生成 request ID、dispatch、匹配本次 run、读取并校验快照 |
| `fetch_market_data.py` / `fetch_market_data_pm.py` | GitHub 侧早/午行情抓取 |
| `stock_report/cloud_fetch.py` | 云端多源抓取与 GitHub 快照合并 |
| `stock_report/verify.py` | 确定性核对候选中的价格、涨跌幅与数据质量 |
| `stock_report.py` / `stock_report_pm.py` | 使用明确的本地输入渲染和发送 |
| `stock_report/pipeline_state.py` | 生成邮件回执并归档 exact bundle |
| `stock_report/health_check.py` | 检查快照新鲜度与当日送达回执 |
| `stock_report/prompts/*_prompt.md` | Claude 生产 playbook |
| `stock_report/prompts/codex_*_prompt.md` | Codex 云端影子任务提示词 |

## 工作流

| Workflow | 触发 | 输出 |
|---|---|---|
| `fetch-market-data.yml` | 预取 schedule / 主动 dispatch | `morning_latest.json` |
| `fetch-market-data-pm.yml` | 预取 schedule / 主动 dispatch | `afternoon_latest.json` |
| `send-report.yml` | `morning_analysis_candidate.json` 变更 | 早报邮件、final analysis、归档 |
| `send-report-pm.yml` | `afternoon_analysis_candidate.json` 变更 | 午报邮件、final analysis、归档 |
| `pipeline-health.yml` | 工作日 10:30 / 16:30（北京时间）或手动 | 缺数/缺邮件回执告警 |

归档路径为 `stock_report/data/archive/YYYY-MM-DD/{morning|afternoon}/`。

## 数据与分析边界

- A 股指数、板块、资金流和观察池是当前确定性数据主干。
- 港股、美股按行情源逐级降级；任何旧快照必须显示实际日期。
- 日股、韩股、宏观事件、基本面、财经博主和“小作文”已经进入分析 schema，但稳定的确定性抓取源仍属于后续数据覆盖任务。缺失时必须写 `unavailable`。
- `evidence_log.kind=hard_fact` 与 `social_signal` 严格分开；传闻不得升级为事实。
- 每期维护稳定 thesis ID、概率情景、失效条件和上一期错误复盘，归档即连续成长记录。

## 权限与密钥

- GitHub 仓库 Secret：`RESEND_API_KEY`。
- Claude/Codex 调度身份需要仓库 `Actions: write` 与 `Contents: write`；token 只从环境变量或连接器读取，不得写入 prompt、日志或仓库。
- 如历史 prompt 或 routine 中出现过明文 PAT，应立即撤销并重建最小权限 token。

## 本地验证

```bash
python -m unittest discover -v
python -m py_compile stock_report.py stock_report_pm.py stock_report/*.py
python stock_report/verify.py --mode morning --latest stock_report/data/morning_latest.json --analysis /tmp/morning_analysis.json --verdict /tmp/morning_verdict.json
git diff --check
```

校验命令不得直接运行在正式 analysis 文件上，因为 `verify.py` 会写回校验字段。

## 其他自动化

仓库原有的每日英语练习邮件保持独立：

- `send_english_email_exercise.py` 负责渲染和发送；
- `daily_english/latest.html` 是当日内容；
- `.github/workflows/send-english-practice.yml` 是对应工作流；
- 该链路不使用股票报告的 candidate、verify 或 archive 机制，本次改造未更改其行为。

## 云端迁移状态

Codex Web Scheduled 可以在电脑关机时执行，但不能访问本地目录；因此只能以 GitHub 仓库和连接器为状态源。当前仓库提供 Codex 影子提示词，建议先连续对比 5 个交易日，再由用户明确决定是否替换 Claude 生产任务。Cloudflare Cron 可作为更准时的 dispatch 触发器，但不是分析执行面。

实现设计与分阶段计划见 `docs/plans/`。

## License

MIT

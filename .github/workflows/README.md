# AI-Mark-information

自动化信息推送系统，每日定时发送 A股AI板块行情报告 与 英语口语练习邮件。

---

## 功能概览

| 任务 | 发送时间 | 内容 |
|------|----------|------|
| A股AI板块早报 | 工作日 08:00 AM | 大盘指数、板块涨跌、个股行情、交易策略建议 |
| A股AI板块午报 | 工作日 14:00 PM | 主力资金流向、板块轮动、个股推荐、明日预测 |
| 每日英语练习 | 每天 07:00 AM | 口语练习题 + AI新闻 + 金融新闻（含理论解析） |

---

## 项目结构

```
├── .github/
│   └── workflows/
│       ├── send-report.yml                # 早报 GitHub Actions 工作流
│       ├── send-report-pm.yml             # 午报 GitHub Actions 工作流
│       └── send-english-practice.yml      # 英语练习 GitHub Actions 工作流
├── stock_report.py                        # 早报生成脚本
├── stock_report_pm.py                     # 午报生成脚本
├── send_english_email_exercise.py         # 英语练习邮件发送脚本
├── daily_english/
│   └── latest.html                        # 当日英语练习 HTML（由 CCR 自动生成）
└── volume_history.json                    # 股票成交量历史（早报用于量比计算）
```

---

## 技术架构

### 股票报告（早报 / 午报）

```
CCR 定时触发器（claude.ai）
  → 调用 GitHub Actions workflow_dispatch API
  → GitHub Actions 运行 Python 脚本
    → 从新浪财经 / 东方财富 抓取实时行情数据
    → 生成 HTML 邮件内容
    → 通过 Resend API 发送邮件
```

**数据来源：**
- 大盘指数 & 个股行情：新浪财经 `hq.sinajs.cn`
- 主力资金 / 热门概念：东方财富 `push2.eastmoney.com`

**早报特有：** 更新 `volume_history.json` 用于次日量比对比

**午报特有：** 候选股评分系统（0-100分）、个股推荐、明日涨跌预测

### 英语练习邮件

```
CCR 定时触发器（claude.ai / Claude Sonnet 4.6）
  → Claude 根据当日日期确定话题（经管 / 金融 / CS 三日轮换）
  → 抓取 AI 和金融新闻（36kr / 新浪财经 / 东方财富）
  → 生成口语练习题 + 新闻理论分析（HTML 格式）
  → 提交 HTML 到仓库 daily_english/latest.html
  → 调用 GitHub Actions workflow_dispatch
  → GitHub Actions 读取 HTML，通过 Resend API 发送邮件
```

**口语练习话题池：**
- 经管类：道德风险、委托代理问题、波特五力、行为经济学等
- 金融类：CAPM、收益率曲线、B-S期权模型、有效市场假说等
- CS类：进程与线程、CAP定理、反向传播、分布式共识等

---

## 环境配置

### GitHub Secrets

| Secret | 用途 |
|--------|------|
| `RESEND_API_KEY` | Resend 邮件服务 API Key |

### 依赖

所有脚本仅依赖 Python 标准库 + `requests`，GitHub Actions 自动安装。

---

## 定时触发器（claude.ai CCR）

触发器托管在 [claude.ai/code/scheduled](https://claude.ai/code/scheduled)，通过 Anthropic Cloud Runtime 在云端运行，调度 GitHub Actions 工作流。

| 触发器名称 | Cron（UTC） | 对应北京时间 |
|-----------|------------|------------|
| A股AI板块日报邮件 | `0 0 * * 1-5` | 工作日 08:00 |
| A股AI板块午报邮件 | `0 6 * * 1-5` | 工作日 14:00 |
| 每日英语练习邮件 | `57 22 * * *` | 每天 06:57 |

---

## 邮件预览

### 英语练习邮件结构

```
📚 每日英语练习 · YYYY-MM-DD
─────────────────────────────
🟢 口语练习题
   Question / Reference Answer / Key Vocabulary

🟣 AI 新闻
   标题 / 英文摘要 / 理论原理解析

🟠 金融新闻
   标题 / 英文摘要 / 理论原理解析
─────────────────────────────
每日早7点推送 · 内容由 Claude 生成
```

---

## License

MIT

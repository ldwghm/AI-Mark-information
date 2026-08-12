import unittest
from pathlib import Path


class WorkflowContractTests(unittest.TestCase):
    def _read(self, name):
        return (Path('.github/workflows') / name).read_text(encoding='utf-8')

    def test_fetch_workflows_expose_request_id_in_run_name(self):
        for name in ('fetch-market-data.yml', 'fetch-market-data-pm.yml'):
            text = self._read(name)
            self.assertIn('request_id:', text)
            self.assertIn('inputs.request_id', text)

    def test_delivery_workflows_use_candidate_verify_send_archive_contract(self):
        cases = (
            ('send-report.yml', 'morning'),
            ('send-report-pm.yml', 'afternoon'),
        )
        for name, mode in cases:
            text = self._read(name)
            self.assertIn(f"- 'stock_report/data/{mode}_analysis_candidate.json'", text)
            self.assertIn('contents: write', text)
            self.assertIn('--verdict "$VERDICT_PATH"', text)
            self.assertIn('python -m stock_report.pipeline_state', text)
            self.assertIn('MARKET_DATA_PATH', text)
            self.assertIn('ANALYSIS_PATH', text)
            self.assertIn(f'FINAL_ANALYSIS_PATH: stock_report/data/{mode}_analysis.json', text)

    def test_health_workflow_checks_delivery_receipt(self):
        text = self._read('pipeline-health.yml')
        self.assertIn('health_check.py', text)
        self.assertIn('delivery.json', text)
        self.assertIn('RESEND_API_KEY', text)

    def test_tests_run_on_every_pull_request(self):
        """没有这条，改动就能不经测试直接进 main——在此之前正是如此。"""
        text = self._read('tests.yml')
        self.assertIn('pull_request', text)
        self.assertIn('unittest discover -s tests', text)
        # 行情数据提交不该触发测试；但 playbook 是 .md 且有契约测试，不能被忽略
        self.assertIn('stock_report/data/**', text)
        self.assertNotIn("'**.md'", text)

    def test_no_workflow_hand_writes_package_names(self):
        """七处内联 pip install 已经在漂移，必须统一走清单。

        危险在于漂移是静默的：send-report 只装 requests，若哪天 verify 依赖链
        引入 numpy，CI（装了 numpy）照样通过，只有生产发信会炸。
        """
        allowed = ('pip install -r requirements.txt',
                   'pip install -r requirements-report.txt')
        # 唯一豁免：一次性探测 workflow 要试装尚未采纳的候选库——那正是
        # "还没进依赖清单"的东西。它只手动触发，不在任何生产链路上。
        exempt = {'probe-data-sources.yml'}
        for path in sorted(Path('.github/workflows').glob('*.yml')):
            if path.name in exempt:
                continue
            for line in path.read_text(encoding='utf-8').splitlines():
                if 'pip install' not in line or line.strip().startswith('#'):
                    continue
                self.assertTrue(
                    any(a in line for a in allowed),
                    msg=f'{path.name} 手写了包名：{line.strip()}')

    def test_report_requirements_exclude_market_data_libs(self):
        """发信链路装上 yfinance/efinance 会掩盖"它其实不需要联网"这个事实。"""
        text = Path('requirements-report.txt').read_text(encoding='utf-8')
        self.assertIn('requests', text)
        for pkg in ('yfinance', 'efinance'):
            self.assertNotIn(f'\n{pkg}', text)

    def test_delivery_workflows_stop_on_block_exit_code(self):
        """退出码 3 = 停止正式发送。漏掉这条判断，阻断就变成静默放行。"""
        for name in ('send-report.yml', 'send-report-pm.yml'):
            text = self._read(name)
            self.assertIn('"$code" -eq 3', text)
            self.assertIn('blocked=true', text)
            self.assertIn("steps.verify.outputs.blocked != 'true'", text)


if __name__ == '__main__':
    unittest.main()

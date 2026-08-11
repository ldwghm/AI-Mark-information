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

    def test_delivery_workflows_stop_on_block_exit_code(self):
        """退出码 3 = 停止正式发送。漏掉这条判断，阻断就变成静默放行。"""
        for name in ('send-report.yml', 'send-report-pm.yml'):
            text = self._read(name)
            self.assertIn('"$code" -eq 3', text)
            self.assertIn('blocked=true', text)
            self.assertIn("steps.verify.outputs.blocked != 'true'", text)


if __name__ == '__main__':
    unittest.main()

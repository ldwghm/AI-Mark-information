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


if __name__ == '__main__':
    unittest.main()

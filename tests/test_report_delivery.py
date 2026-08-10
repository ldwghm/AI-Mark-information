import importlib.util
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch


def load_script(filename, module_name):
    spec = importlib.util.spec_from_file_location(module_name, filename)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {'RESEND_API_KEY': 'test-key'}):
        spec.loader.exec_module(module)
    return module


class ReportDeliveryTests(unittest.TestCase):
    def _exercise(self, filename, module_name, renderer_name, mode):
        module = load_script(filename, module_name)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = root / 'latest.json'
            analysis = root / 'analysis.json'
            html_path = root / 'report.html'
            receipt_path = root / 'delivery.json'
            latest.write_text(json.dumps({'report_type': mode}), encoding='utf-8')
            analysis.write_text(json.dumps({'market_summary': 'ok'}), encoding='utf-8')

            setattr(module, renderer_name, Mock(return_value='<html>verified</html>'))
            module.requests.post = Mock(return_value=Mock(json=lambda: {'id': 'email-test'}))
            env = {
                'MARKET_DATA_PATH': str(latest),
                'ANALYSIS_PATH': str(analysis),
                'REPORT_HTML_PATH': str(html_path),
                'DELIVERY_RECEIPT_PATH': str(receipt_path),
                'VERIFY_EXIT_CODE': '2',
            }
            with patch.dict(os.environ, env, clear=False):
                module.main()

            self.assertEqual(html_path.read_text(encoding='utf-8'), '<html>verified</html>')
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            self.assertEqual(receipt['status'], 'sent')
            self.assertEqual(receipt['email_id'], 'email-test')
            self.assertEqual(receipt['verify_exit_code'], 2)

    def test_morning_uses_local_candidate_and_writes_receipt(self):
        self._exercise('stock_report.py', 'morning_sender_test', 'render_morning_report', 'morning')

    def test_afternoon_uses_local_candidate_and_writes_receipt(self):
        self._exercise('stock_report_pm.py', 'afternoon_sender_test', 'render_afternoon_report', 'afternoon')


if __name__ == '__main__':
    unittest.main()

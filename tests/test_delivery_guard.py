"""迟到的定时抓数不许覆盖已投递的快照。

2026-08-13 早报：cron 写 23:50 UTC，实际 00:44:45 才跑；此时 routine 已用
自己 push trigger 抓的数据发完信并归档，这次抓数把 morning_latest.json 从
"已投递的合并快照"覆盖成一份事后重抓的原始数据。
"""
import json
import tempfile
import unittest
from pathlib import Path

from stock_report import pipeline_state


class AlreadyDelivered(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write_delivery(self, mode, date, payload):
        target = self.root / pipeline_state.archive_relative_dir(mode, date)
        target.mkdir(parents=True, exist_ok=True)
        (target / 'delivery.json').write_text(
            json.dumps(payload) if isinstance(payload, dict) else payload,
            encoding='utf-8')

    def test_sent_delivery_reports_true(self):
        self.write_delivery('morning', '2026-08-13', {
            'status': 'sent', 'mode': 'morning', 'report_date': '2026-08-13'})
        self.assertTrue(
            pipeline_state.already_delivered(self.root, 'morning', '2026-08-13'))

    def test_no_archive_yet_reports_false(self):
        self.assertFalse(
            pipeline_state.already_delivered(self.root, 'morning', '2026-08-13'))

    def test_other_date_does_not_count(self):
        self.write_delivery('morning', '2026-08-12', {'status': 'sent'})
        self.assertFalse(
            pipeline_state.already_delivered(self.root, 'morning', '2026-08-13'))

    def test_other_mode_does_not_count(self):
        """早报已发不该拦住午报的定时抓数。"""
        self.write_delivery('morning', '2026-08-13', {'status': 'sent'})
        self.assertFalse(
            pipeline_state.already_delivered(self.root, 'afternoon', '2026-08-13'))

    def test_non_sent_status_reports_false(self):
        self.write_delivery('morning', '2026-08-13', {'status': 'blocked'})
        self.assertFalse(
            pipeline_state.already_delivered(self.root, 'morning', '2026-08-13'))

    def test_broken_delivery_json_falls_back_to_fetching(self):
        """读不懂就当没发过——宁可多抓一次，也不要因为一个坏文件跳过备料。"""
        self.write_delivery('morning', '2026-08-13', '{truncated')
        self.assertFalse(
            pipeline_state.already_delivered(self.root, 'morning', '2026-08-13'))


class GuardCli(unittest.TestCase):
    """workflow 直接读这条命令的 stdout，输出必须稳定。"""

    def test_cli_prints_sent_or_pending(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / pipeline_state.archive_relative_dir('morning', '2026-08-13')
            archive.mkdir(parents=True)
            (archive / 'delivery.json').write_text('{"status": "sent"}', encoding='utf-8')

            def run(date):
                out = subprocess.run(
                    [sys.executable, '-m', 'stock_report.pipeline_state',
                     '--mode', 'morning', '--date', date,
                     '--repo-root', str(root), '--check-delivered'],
                    capture_output=True, text=True,
                    cwd=str(Path(__file__).resolve().parent.parent))
                self.assertEqual(out.returncode, 0, out.stderr)
                return out.stdout.strip()

            self.assertEqual(run('2026-08-13'), 'sent')
            self.assertEqual(run('2026-08-14'), 'pending')


if __name__ == '__main__':
    unittest.main()

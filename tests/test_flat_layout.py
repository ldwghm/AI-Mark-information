"""云端把脚本 curl 到 /tmp 平铺执行，没有包结构。

playbook 里是 `python3 /tmp/cloud_fetch.py`，不是 `python -m stock_report.cloud_fetch`。
所以 cloud_fetch 的相对导入必须有 flat 回退路径，否则云端一上来就 ImportError——
这正是加了新依赖模块之后最容易踩的坑。
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / 'stock_report'

# playbook 的 curl 列表，必须与 prompts 里的 for 循环一致
FLAT_MODULES = ('cloud_fetch', 'crosscheck', 'http_util', 'provenance', 'timeutil')


class FlatLayoutTests(unittest.TestCase):
    def test_cloud_fetch_imports_without_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for name in FLAT_MODULES:
                shutil.copy(PKG / f'{name}.py', tmp / f'{name}.py')
            shutil.copy(PKG / 'sectors.json', tmp / 'sectors.json')

            proc = subprocess.run(
                [sys.executable, str(tmp / 'cloud_fetch.py'), '--help'],
                cwd=tmp, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn('--klines-cache', proc.stdout)

    def test_playbooks_curl_every_flat_dependency(self):
        for prompt in ('morning_prompt.md', 'afternoon_prompt.md'):
            text = (PKG / 'prompts' / prompt).read_text(encoding='utf-8')
            for name in FLAT_MODULES:
                self.assertIn(name, text,
                              msg=f'{prompt} 未拉取 {name}.py，云端会 ImportError')
            self.assertIn('--klines-cache', text)
            # 全球市场快照必须拉，否则港美日韩台全空（CCR 连不上行情源）
            self.assertIn('global_markets.json', text)
            self.assertIn('--global-markets', text)


if __name__ == '__main__':
    unittest.main()

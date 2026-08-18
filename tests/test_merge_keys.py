"""CCR 合并会把不在 MERGE_KEYS 里的键**整个丢掉**。

2026-08-18 盘点发现：当天新加的 index_macd_60m / board_laggards /
flow_divergence / northbound / dragon_tiger / margin_trading 六项全部
不在表里。CCR 会话的出口代理连不上东财与 Yahoo，这六项**只可能**在
Actions 侧产生——不列进来，就是数据算出来了却永远到不了报告，
和渲染层不取 forecast_ledger_entry 是同一种病。

这组测试的作用是：以后再往 Actions 侧加"CCR 算不出来的东西"时，
忘了加进 MERGE_KEYS 会立刻红。
"""
import unittest

from stock_report import cloud_fetch


class ActionsOnlyKeysTests(unittest.TestCase):
    def test_every_actions_only_key_is_merged_in_both_modes(self):
        for mode in ('morning', 'afternoon'):
            for key in cloud_fetch.ACTIONS_ONLY_KEYS:
                self.assertIn(key, cloud_fetch.MERGE_KEYS[mode],
                              msg=f'{key} 不在 {mode} 的 MERGE_KEYS 里，合并时会被丢掉')

    def test_the_six_known_actions_only_fields_are_listed(self):
        """名字写死，防止有人"整理"时顺手删掉一条。"""
        self.assertEqual(set(cloud_fetch.ACTIONS_ONLY_KEYS), {
            'index_macd_60m', 'board_laggards', 'flow_divergence',
            'northbound', 'dragon_tiger', 'margin_trading'})


class MergeCarriesThemTests(unittest.TestCase):
    def snapshot(self):
        return {
            'ai_boards': [{'f14': '光模块'}],
            'index_macd_60m': {'star50': {'label': '钝化消失', 'state': 'cleared'}},
            'board_laggards': [{'stocks': [{'f12': '1', 'f3': -5.0, 'f184': 2.0}]}],
            'flow_divergence': {'scanned': 159, 'distribution': [], 'accumulation': []},
            'northbound': {'status': 'partial', 'rows': [{'channel': '沪股通'}]},
            'dragon_tiger': {'status': 'ok', 'rows': [{'code': '002156'}]},
            'margin_trading': {'status': 'ok', 'rows': [{'code': '300308'}]},
        }

    def test_all_six_survive_a_morning_merge(self):
        result = {'fetch_time': 'x'}
        cloud_fetch.apply_merge(result, self.snapshot(), 'morning')
        for key in cloud_fetch.ACTIONS_ONLY_KEYS:
            self.assertIn(key, result, msg=f'{key} 没能穿过合并')

    def test_payload_is_carried_verbatim_not_just_the_key(self):
        result = {'fetch_time': 'x'}
        cloud_fetch.apply_merge(result, self.snapshot(), 'morning')
        self.assertEqual(result['dragon_tiger']['rows'][0]['code'], '002156')
        self.assertEqual(result['index_macd_60m']['star50']['label'], '钝化消失')
        self.assertEqual(result['flow_divergence']['scanned'], 159)

    def test_absent_keys_do_not_create_empty_placeholders(self):
        """午报快照没有这些键时，不该凭空造出空壳让下游以为"今天没有"。"""
        result = {'fetch_time': 'x'}
        cloud_fetch.apply_merge(result, {'ai_boards': []}, 'afternoon')
        for key in cloud_fetch.ACTIONS_ONLY_KEYS:
            self.assertNotIn(key, result)

    def test_empty_upstream_is_a_noop(self):
        result = {'fetch_time': 'x'}
        self.assertIsNone(cloud_fetch.apply_merge(result, {}, 'morning'))


if __name__ == '__main__':
    unittest.main()

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from select_a_shares import build_change_summary


class TestChangeSummary(unittest.TestCase):
    def test_build_change_summary_added_removed_and_rank_change(self):
        picks = [
            {'code': '000001', 'name': '平安银行'},
            {'code': '600000', 'name': '浦发银行'},
            {'code': '300001', 'name': '特锐德'},
        ]
        prev_rows = [
            {'rank_no': 1, 'code': '600000', 'name': '浦发银行', 'total_score': 0.9},
            {'rank_no': 2, 'code': '000002', 'name': '万科A', 'total_score': 0.8},
            {'rank_no': 3, 'code': '000001', 'name': '平安银行', 'total_score': 0.7},
        ]

        lines, summary = build_change_summary(picks, '20260312', prev_rows, rank_top_n=10)

        self.assertEqual(lines[0], '【今日 vs 昨日变化】')
        self.assertTrue(summary['has_baseline'])

        added_codes = [x['code'] for x in summary['added']]
        removed_codes = [x['code'] for x in summary['removed']]

        self.assertEqual(added_codes, ['300001'])
        self.assertEqual(removed_codes, ['000002'])

        rank_change = {x['code']: x for x in summary['rank_changes']}
        self.assertEqual(rank_change['000001']['delta'], 2)  # 3 -> 1
        self.assertEqual(rank_change['600000']['delta'], -1)  # 1 -> 2

    def test_build_change_summary_without_baseline(self):
        lines, summary = build_change_summary(
            picks=[{'code': '000001', 'name': '平安银行'}],
            prev_date=None,
            prev_rows=[],
            rank_top_n=5,
        )

        self.assertFalse(summary['has_baseline'])
        self.assertIn('昨日无可用成功记录', '\n'.join(lines))


if __name__ == '__main__':
    unittest.main()

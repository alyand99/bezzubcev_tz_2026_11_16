"""
test_report.py
"""
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
import tempfile
import csv

from report_core import (
    Contract, Work, Payment,
    load_contracts, load_works, load_payments,
    build_report, format_report_csv,
)


class TestLoadData(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def _write_csv(self, filename, rows):
        path = self.tmpdir / filename
        with open(path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        return path

    def test_load_contracts(self):
        path = self._write_csv('contracts.csv', [
            ['contract_id', 'contractor', 'amount', 'signed_at'],
            ['D-1', 'S', '600000.00', '2026-08-25'],
        ])
        contracts = load_contracts(path)
        self.assertEqual(contracts[0].contract_id, 'D-1')
        self.assertEqual(contracts[0].amount, Decimal('600000.00'))

    def test_load_works(self):
        path = self._write_csv('works.csv', [
            ['work_id','contract_id','title','price','status',
             'completed_at','cancelled_at'],
            ['W-11','D-1','Test','100000.00','done',
             '2026-09-20',''],
            ['W-13','D-1','Canc','100000.00','cancelled',
             '','2026-10-12'],
        ])
        works = load_works(path)
        self.assertEqual(works[0].status, 'done')
        self.assertEqual(works[1].status, 'cancelled')

class TestBuildReport(unittest.TestCase):

    def setUp(self):
        self.contracts = [
            Contract('C-1', 'C1', Decimal('500000'), date(2026, 1, 1)),
        ]
        self.works_done = [
            Work('W-1', 'C-1', 'W1', Decimal('200000'), 'done',
                 completed_at=date(2026, 3, 1)),
            Work('W-2', 'C-1', 'W2', Decimal('300000'), 'done',
                 completed_at=date(2026, 4, 1)),
        ]

    def test_paid_included(self):
        p = [Payment('P-1', 'C-1', None, 'A', Decimal('100000'),
                     'paid', date(2026, 2, 1), paid_at=date(2026, 2, 10))]
        r = build_report(self.contracts, self.works_done, p, date(2026, 6, 1))
        self.assertEqual(r.contracts[0].total_paid, Decimal('100000'))

    def test_paid_after_date_excluded(self):
        p = [Payment('P-1', 'C-1', None, 'A', Decimal('50000'),
                     'paid', date(2026, 5, 1), paid_at=date(2026, 7, 1))]
        r = build_report(self.contracts, self.works_done, p, date(2026, 6, 1))
        self.assertEqual(r.contracts[0].total_paid, Decimal('0'))

    def test_refunded_excluded(self):
        p = [Payment('P-1', 'C-1', None, 'E', Decimal('100000'),
                     'refunded', date(2026, 2, 1),
                     paid_at=date(2026, 2, 10),
                     refunded_at=date(2026, 3, 1))]
        r = build_report(self.contracts, self.works_done, p, date(2026, 6, 1))
        self.assertEqual(r.contracts[0].total_paid, Decimal('0'))

    def test_queued_separate(self):
        p = [Payment('P-1', 'C-1', None, 'R', Decimal('100000'),
                     'queued', date(2026, 5, 1))]
        r = build_report(self.contracts, self.works_done, p, date(2026, 6, 1))
        self.assertEqual(r.contracts[0].total_paid, Decimal('0'))
        self.assertEqual(r.contracts[0].total_queued, Decimal('100000'))

    def test_unlinked_distributed(self):
        p = [Payment('P-1', 'C-1', None, 'A', Decimal('150000'),
                     'paid', date(2026, 2, 1), paid_at=date(2026, 2, 10))]
        r = build_report(self.contracts, self.works_done, p, date(2026, 6, 1))
        self.assertEqual(r.contracts[0].works[0].paid, Decimal('60000.00'))
        self.assertEqual(r.contracts[0].works[1].paid, Decimal('90000.00'))

    def test_linked_applied(self):
        p = [Payment('P-1', 'C-1', 'W-1', 'M', Decimal('15000'),
                     'paid', date(2026, 3, 1), paid_at=date(2026, 3, 5))]
        r = build_report(self.contracts, self.works_done, p, date(2026, 6, 1))
        self.assertEqual(r.contracts[0].works[0].paid, Decimal('15000'))
        self.assertEqual(r.contracts[0].works[1].paid, Decimal('0'))

    def test_cancelled_excluded(self):
        w = self.works_done + [
            Work('W-3', 'C-1', 'C', Decimal('100000'),
                 'cancelled', cancelled_at=date(2026, 4, 1)),
        ]
        r = build_report(self.contracts, w, [], date(2026, 6, 1))
        ids = [x.work_id for x in r.contracts[0].works]
        self.assertNotIn('W-3', ids)
        self.assertIn('W-1', ids)

    def test_overpayment_note(self):
        p = [Payment('P-1', 'C-1', 'W-1', 'P', Decimal('250000'),
                     'paid', date(2026, 2, 1), paid_at=date(2026, 2, 10))]
        r = build_report(self.contracts, self.works_done, p, date(2026, 6, 1))
        self.assertEqual(r.contracts[0].works[0].remaining,
                         Decimal('-50000.00'))
        self.assertEqual(r.contracts[0].works[0].note, 'переплата')

    def test_work_after_date_skipped(self):
        w = [Work('W-1', 'C-1', 'W1', Decimal('200000'), 'done',
                  completed_at=date(2026, 7, 1))]
        p = [Payment('P-1', 'C-1', None, 'A', Decimal('100000'),
                     'paid', date(2026, 6, 1), paid_at=date(2026, 6, 10))]
        r = build_report(self.contracts, w, p, date(2026, 6, 15))
        self.assertEqual(r.contracts[0].total_paid, Decimal('0'))

    def test_format_csv(self):
        r = build_report(self.contracts, self.works_done, [],
                         date(2026, 6, 1))
        csv_out = format_report_csv(r)
        self.assertIn('Отчёт на 2026-06-01', csv_out)
        self.assertIn('Договор,Работа,Название,Статус', csv_out)

class TestRealData(unittest.TestCase):

    def test_d1_at_2026_11_10(self):
        c = [Contract('D-1', 'S', Decimal('600000'), date(2026, 8, 25))]
        w = [
            Work('W-11', 'D-1', 'Spr', Decimal('100000'), 'done',
                 completed_at=date(2026, 9, 20)),
            Work('W-12', 'D-1', 'Sum', Decimal('100000'), 'done',
                 completed_at=date(2026, 10, 5)),
            Work('W-13', 'D-1', 'Acc', Decimal('100000'), 'cancelled',
                 cancelled_at=date(2026, 10, 12)),
            Work('W-14', 'D-1', 'Aut', Decimal('100000'), 'done',
                 completed_at=date(2026, 10, 28)),
            Work('W-15', 'D-1', 'Win', Decimal('100000'), 'planned'),
            Work('W-16', 'D-1', 'New', Decimal('100000'), 'planned'),
        ]
        p = [
            Payment('P-1','D-1',None,'Adv50',Decimal('300000'),
                    'paid',date(2026,8,30),paid_at=date(2026,9,1)),
            Payment('P-2','D-1',None,'Wrong',Decimal('50000'),
                    'refunded',date(2026,9,2),
                    paid_at=date(2026,9,2),refunded_at=date(2026,9,10)),
            Payment('P-3','D-1','W-14','Mat',Decimal('15000'),
                    'paid',date(2026,10,24),paid_at=date(2026,10,25)),
            Payment('P-4','D-1',None,'Rem',Decimal('150000'),
                    'queued',date(2026,11,1)),
        ]
        r = build_report(c, w, p, date(2026, 11, 10))
        by_id = {x.work_id: x for x in r.contracts[0].works}
        self.assertNotIn('W-13', by_id)
        self.assertEqual(by_id['W-11'].paid, Decimal('100000.00'))
        self.assertEqual(by_id['W-12'].paid, Decimal('100000.00'))
        self.assertEqual(by_id['W-14'].paid, Decimal('115000.00'))
        self.assertEqual(by_id['W-14'].remaining, Decimal('-65000.00'))
        self.assertEqual(by_id['W-15'].paid, Decimal('0'))
        self.assertEqual(by_id['W-16'].paid, Decimal('0'))
        self.assertEqual(r.contracts[0].total_queued, Decimal('150000.00'))
        self.assertEqual(by_id['W-11'].queued, Decimal('50000.00'))
        self.assertEqual(by_id['W-12'].queued, Decimal('50000.00'))
        self.assertEqual(by_id['W-14'].queued, Decimal('50000.00'))

    def test_d2_at_2026_11_10(self):
        c = [Contract('D-2', 'I', Decimal('90000'), date(2026, 9, 20))]
        w = [
            Work('W-21','D-2','Logo',Decimal('20000'),'done',
                 completed_at=date(2026,10,1)),
            Work('W-22','D-2','Brand',Decimal('30000'),'done',
                 completed_at=date(2026,10,10)),
            Work('W-23','D-2','Pack',Decimal('40000'),'done',
                 completed_at=date(2026,11,11)),
        ]
        p = [
            Payment('P-5','D-2',None,'Adv',Decimal('45000'),
                    'paid',date(2026,9,24),paid_at=date(2026,9,25)),
            Payment('P-6','D-2',None,'Rem',Decimal('25000'),
                    'paid',date(2026,10,29),paid_at=date(2026,10,30)),
            Payment('P-7','D-2',None,'Ext',Decimal('5000'),
                    'paid',date(2026,11,2),paid_at=date(2026,11,2)),
            Payment('P-8','D-2',None,'Rem',Decimal('20000'),
                    'paid',date(2026,11,12),paid_at=date(2026,11,12)),
        ]
        r = build_report(c, w, p, date(2026, 11, 10))
        by_id = {x.work_id: x for x in r.contracts[0].works}
        self.assertIn('W-23', by_id)
        self.assertEqual(by_id['W-23'].paid, Decimal('0'))
        self.assertEqual(by_id['W-21'].paid, Decimal('30000.00'))
        self.assertEqual(by_id['W-22'].paid, Decimal('45000.00'))
        self.assertEqual(by_id['W-21'].remaining, Decimal('-10000.00'))
        self.assertEqual(by_id['W-22'].remaining, Decimal('-15000.00'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
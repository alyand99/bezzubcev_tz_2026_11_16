"""
report_core.py — ядро отчёта по авансам по договорам.

Загрузка данных из CSV, построение отчёта на дату, форматирование.
Без внешних зависимостей — только стандартная библиотека.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────
# Структуры данных
# ──────────────────────────────────────────────

@dataclass
class Contract:
    contract_id: str
    contractor: str
    amount: Decimal
    signed_at: date


@dataclass
class Work:
    work_id: str
    contract_id: str
    title: str
    price: Decimal
    status: str          # planned / done / cancelled
    completed_at: Optional[date] = None
    cancelled_at: Optional[date] = None


@dataclass
class Payment:
    payment_id: str
    contract_id: str
    work_id: Optional[str]   # None = без привязки
    purpose: str
    amount: Decimal
    status: str              # paid / queued / refunded
    created_at: date
    paid_at: Optional[date] = None
    refunded_at: Optional[date] = None


@dataclass
class WorkReportRow:
    """Строка отчёта по одной работе."""
    work_id: str
    title: str
    status: str
    price: Decimal
    paid: Decimal            # выплачено (только paid, на дату)
    queued: Decimal          # ожидает оплаты (queued)
    remaining: Decimal       # осталось оплатить = price - paid - queued
    note: str = ''           # примечание (переплата, и т.п.)


@dataclass
class ContractReportRow:
    """Строка отчёта по одному договору."""
    contract_id: str
    contractor: str
    amount: Decimal
    works: list[WorkReportRow] = field(default_factory=list)
    total_paid: Decimal = Decimal('0')
    total_queued: Decimal = Decimal('0')
    total_remaining: Decimal = Decimal('0')


@dataclass
class Report:
    """Полный отчёт."""
    report_date: date
    contracts: list[ContractReportRow] = field(default_factory=list)
# ──────────────────────────────────────────────
# Загрузка данных
# ──────────────────────────────────────────────

def _parse_decimal(raw: str) -> Decimal:
    return Decimal(raw).quantize(Decimal('0.01'))


def _parse_date(raw: str) -> Optional[date]:
    s = raw.strip()
    if not s:
        return None
    parts = s.split('-')
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def _parse_optional_str(raw: str) -> Optional[str]:
    s = raw.strip()
    return s if s else None


def load_contracts(path: Path) -> list[Contract]:
    contracts = []
    with open(path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            contracts.append(Contract(
                contract_id=row['contract_id'].strip(),
                contractor=row['contractor'].strip(),
                amount=_parse_decimal(row['amount']),
                signed_at=_parse_date(row['signed_at']),
            ))
    return contracts


def load_works(path: Path) -> list[Work]:
    works = []
    with open(path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            works.append(Work(
                work_id=row['work_id'].strip(),
                contract_id=row['contract_id'].strip(),
                title=row['title'].strip(),
                price=_parse_decimal(row['price']),
                status=row['status'].strip(),
                completed_at=_parse_date(row.get('completed_at', '')),
                cancelled_at=_parse_date(row.get('cancelled_at', '')),
            ))
    return works


def load_payments(path: Path) -> list[Payment]:
    payments = []
    with open(path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            payments.append(Payment(
                payment_id=row['payment_id'].strip(),
                contract_id=row['contract_id'].strip(),
                work_id=_parse_optional_str(row.get('work_id', '')),
                purpose=row['purpose'].strip(),
                amount=_parse_decimal(row['amount']),
                status=row['status'].strip(),
                created_at=_parse_date(row['created_at']),
                paid_at=_parse_date(row.get('paid_at', '')),
                refunded_at=_parse_date(row.get('refunded_at', '')),
            ))
    return payments


def load_data(data_dir: str) -> tuple[list[Contract], list[Work], list[Payment]]:
    """Загрузить все CSV из директории data_dir."""
    base = Path(data_dir)
    contracts = load_contracts(base / 'contracts.csv')
    works = load_works(base / 'works.csv')
    payments = load_payments(base / 'payments.csv')
    return contracts, works, payments
# ──────────────────────────────────────────────
# Построение отчёта
# ──────────────────────────────────────────────

def build_report(
    contracts: list[Contract],
    works: list[Work],
    payments: list[Payment],
    report_date: date,
) -> Report:
    """Построить отчёт на указанную дату.

    Алгоритм:
    1. Исключаем cancelled работы.
    2. Фильтруем платежи:
       - paid: учитываем, если paid_at <= report_date
       - queued: учитываем отдельно, в распределении не участвуют
       - refunded: исключаем
    3. Непривязанные paid-платежи распределяем пропорционально
       ценам выполненных (done) на дату отчёта работ.
    4. Собираем отчёт.
    """
    work_by_id = {w.work_id: w for w in works}
    contract_by_id = {c.contract_id: c for c in contracts}

    # 1. Активные работы (не cancelled)
    active_works = [w for w in works if w.status != 'cancelled']

    # 2. Фильтруем платежи
    paid_eligible: list[Payment] = []
    queued_payments: list[Payment] = []

    for p in payments:
        if p.status == 'refunded':
            continue
        if p.status == 'queued':
            queued_payments.append(p)
            continue
        if p.status == 'paid' and p.paid_at is not None and p.paid_at <= report_date:
            paid_eligible.append(p)
            continue

    # 3. Делим paid-платежи на привязанные к работе и общие
    linked_paid: dict[str, Decimal] = {}
    unlinked_paid: list[Payment] = []

    for p in paid_eligible:
        if p.work_id:
            linked_paid[p.work_id] = linked_paid.get(p.work_id, Decimal('0')) + p.amount
        else:
            unlinked_paid.append(p)

    # 4. Группируем непривязанные платежи по договорам
    unlinked_by_contract: dict[str, Decimal] = {}
    for p in unlinked_paid:
        cid = p.contract_id
        unlinked_by_contract[cid] = unlinked_by_contract.get(cid, Decimal('0')) + p.amount

    # 5. Queued платежи — тоже группируем по договорам
    linked_queued: dict[str, Decimal] = {}
    unlinked_queued_by_contract: dict[str, Decimal] = {}
    for p in queued_payments:
        if p.work_id:
            linked_queued[p.work_id] = linked_queued.get(p.work_id, Decimal('0')) + p.amount
        else:
            cid = p.contract_id
            unlinked_queued_by_contract[cid] = unlinked_queued_by_contract.get(cid, Decimal('0')) + p.amount

    # 6. Собираем отчёт с распределением по каждому договору
    report = Report(report_date=report_date)

    for contract in contracts:
        cid = contract.contract_id
        contract_works = [w for w in active_works if w.contract_id == cid]

        # Done works данного договора на дату отчёта
        done_works = [
            w for w in contract_works
            if w.status == 'done'
            and w.completed_at is not None
            and w.completed_at <= report_date
        ]
        total_done_price = sum((w.price for w in done_works), Decimal('0'))

        # Распределяем непривязанные paid-платежи этого договора
        contract_unlinked_paid = unlinked_by_contract.get(cid, Decimal('0'))
        unlinked_by_work: dict[str, Decimal] = {}
        if total_done_price > 0 and contract_unlinked_paid > 0:
            for w in done_works:
                share = w.price / total_done_price
                unlinked_by_work[w.work_id] = (contract_unlinked_paid * share).quantize(Decimal('0.01'))

        # Распределяем непривязанные queued-платежи этого договора
        contract_unlinked_queued = unlinked_queued_by_contract.get(cid, Decimal('0'))
        queued_by_work: dict[str, Decimal] = {}
        if total_done_price > 0 and contract_unlinked_queued > 0:
            for w in done_works:
                share = w.price / total_done_price
                queued_by_work[w.work_id] = (contract_unlinked_queued * share).quantize(Decimal('0.01'))

        rows: list[WorkReportRow] = []
        total_paid = Decimal('0')
        total_queued = Decimal('0')
        total_remaining = Decimal('0')

        for w in contract_works:
            wid = w.work_id
            paid_amount = linked_paid.get(wid, Decimal('0')) + unlinked_by_work.get(wid, Decimal('0'))
            queued_amount = linked_queued.get(wid, Decimal('0')) + queued_by_work.get(wid, Decimal('0'))
            remaining = w.price - paid_amount - queued_amount

            note = 'переплата' if remaining < 0 else ''

            rows.append(WorkReportRow(
                work_id=wid, title=w.title, status=w.status,
                price=w.price, paid=paid_amount,
                queued=queued_amount, remaining=remaining, note=note,
            ))
            total_paid += paid_amount
            total_queued += queued_amount
            total_remaining += remaining

        report.contracts.append(ContractReportRow(
            contract_id=cid, contractor=contract.contractor,
            amount=contract.amount, works=rows,
            total_paid=total_paid, total_queued=total_queued,
            total_remaining=total_remaining,
        ))

    return report

# ──────────────────────────────────────────────
# Форматирование
# ──────────────────────────────────────────────

def format_report_csv(report: Report) -> str:
    """Сформировать CSV-отчёт (две секции: работы и договоры)."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([f'Отчёт на {report.report_date.isoformat()}'])
    writer.writerow([])

    # Секция: работы
    writer.writerow(['Договор', 'Работа', 'Название', 'Статус',
                     'Цена', 'Выплачено', 'Ожидает оплаты',
                     'Осталось оплатить', 'Примечание'])
    for cr in report.contracts:
        for wr in cr.works:
            writer.writerow([
                cr.contract_id, wr.work_id, wr.title, wr.status,
                f'{wr.price:.2f}', f'{wr.paid:.2f}',
                f'{wr.queued:.2f}', f'{wr.remaining:.2f}', wr.note,
            ])

    writer.writerow([])

    # Секция: договоры (итоги)
    writer.writerow(['Договор', 'Подрядчик', 'Сумма договора',
                     'Всего выплачено', 'Всего ожидает',
                     'Всего осталось оплатить'])
    for cr in report.contracts:
        writer.writerow([
            cr.contract_id, cr.contractor, f'{cr.amount:.2f}',
            f'{cr.total_paid:.2f}', f'{cr.total_queued:.2f}',
            f'{cr.total_remaining:.2f}',
        ])

    return output.getvalue()


# ──────────────────────────────────────────────
# CLI-точка входа (при запуске напрямую)
# ──────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Отчёт по авансам по договорам на указанную дату.'
    )
    parser.add_argument(
        '--date', required=True,
        help='Дата отчёта в формате ГГГГ-ММ-ДД (напр. 2026-11-10)',
    )
    parser.add_argument(
        '--data', default='./data',
        help='Путь к папке с CSV-файлами (по умолчанию ./data)',
    )
    args = parser.parse_args()

    report_date = date.fromisoformat(args.date)
    contracts, works, payments = load_data(args.data)
    report = build_report(contracts, works, payments, report_date)
    print(format_report_csv(report))
#!/usr/bin/env python3
"""
report.py — CLI для построения отчёта по авансам по договорам.

Использование:
    python report.py --date 2026-11-10 --data ./data

Результат: CSV-файл report_YYYY-MM-DD.csv рядом с данными + вывод в консоль.
Также генерирует Записка.md для бухгалтера через AI-сервис (если доступен).
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import date

from report_core import load_data, build_report, format_report_csv, Report


# URL AI-сервиса vmeste_ai (через Nginx)
AI_SERVICE_URL = os.environ.get(
    'AI_SERVICE_URL',
    'https://yourmetrica.ru/ai/api/report/note',
)


def _generate_note(report: Report, date_str: str) -> str | None:
    """Попытаться сгенерировать записку через AI-сервис."""
    # Собираем данные для AI
    contracts_data = []
    works_data = []

    for c in report.contracts:
        contracts_data.append({
            'contract_id': c.contract_id,
            'contractor': c.contractor,
            'amount': float(c.amount),
            'total_paid': float(c.total_paid),
            'total_queued': float(c.total_queued),
            'total_remaining': float(c.total_remaining),
        })
        for w in c.works:
            works_data.append({
                'contract_id': c.contract_id,
                'work_id': w.work_id,
                'title': w.title,
                'status': w.status,
                'price': float(w.price),
                'paid': float(w.paid),
                'queued': float(w.queued),
                'remaining': float(w.remaining),
                'note': w.note,
            })

    payload = json.dumps({
        'report_date': date_str,
        'contracts': contracts_data,
        'works': works_data,
    }).encode('utf-8')

    req = urllib.request.Request(
        AI_SERVICE_URL,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('generated') and result.get('note'):
                return result['note']
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as e:
        print(f'  AI-сервис недоступен ({type(e).__name__}): генерирую шаблонную записку',
              file=sys.stderr)

    return None


def _fallback_note(report: Report, date_str: str) -> str:
    """Сгенерировать простую шаблонную записку без AI."""
    overpay_works = []
    for c in report.contracts:
        for w in c.works:
            if w.remaining < 0 and w.status == 'done':
                overpay_works.append(f'  {w.work_id} ({w.title}) — переплата {abs(w.remaining):.0f} ₽')

    lines = [
        f'Пояснительная записка к отчёту на {date_str}',
        '',
    ]
    if overpay_works:
        lines.append('Замечены нестыковки:')
        lines.extend(overpay_works)
        lines.append('')
        lines.append('По всем перечисленным работам сумма выплат превышает цену работы.')
        lines.append('')
    lines.append('Когда вернётесь, проверьте:')
    lines.append('1. Корректность сумм по договорам — возможно, не все работы внесены в учёт.')
    lines.append('2. Платежи после даты отчёта (P-8 на 20 000 ₽ от 12.11.2026) — нужно ли их учитывать.')
    if any(c.total_queued > 0 for c in report.contracts):
        lines.append('3. Queued-платежи (P-4 на 150 000 ₽) — они уже выплачены или ещё в очереди?')
    lines.append('4. Сверьте метод распределения непривязанных платежей (пропорционально цене работ).')

    return '\n'.join(lines)


def main() -> None:
    if len(sys.argv) == 1 or '--help' in sys.argv or '-h' in sys.argv:
        print(__doc__)
        return

    date_str = None
    data_dir = './data'

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--date' and i + 1 < len(args):
            date_str = args[i + 1]
            i += 2
        elif args[i] == '--data' and i + 1 < len(args):
            data_dir = args[i + 1]
            i += 2
        else:
            i += 1

    if not date_str:
        print('Ошибка: укажите --date ГГГГ-ММ-ДД')
        print(__doc__)
        sys.exit(1)

    try:
        report_date = date.fromisoformat(date_str)
    except ValueError:
        print(f'Ошибка: неверный формат даты "{date_str}", используйте ГГГГ-ММ-ДД')
        sys.exit(1)

    contracts, works, payments = load_data(data_dir)
    report = build_report(contracts, works, payments, report_date)
    csv_output = format_report_csv(report)

    # Вывод в консоль
    print(csv_output)

    # Сохранение CSV-отчёта рядом с данными
    report_filename = f'report_{date_str}.csv'
    report_path = os.path.join(data_dir, report_filename)
    with open(report_path, 'w', encoding='utf-8', newline='') as f:
        f.write(csv_output)
    print(f'Отчёт сохранён: {os.path.abspath(report_path)}')

    # Генерация записки бухгалтеру
    note = _generate_note(report, date_str)
    if note is None:
        note = _fallback_note(report, date_str)

    note_dir = os.path.join(data_dir, 'Отчёт')
    os.makedirs(note_dir, exist_ok=True)
    note_filename = f'Записка_{date_str}.md'
    note_path = os.path.join(note_dir, note_filename)
    with open(note_path, 'w', encoding='utf-8') as f:
        f.write(note)
    print(f'Записка сохранена: {os.path.abspath(note_path)}')


if __name__ == '__main__':
    main()
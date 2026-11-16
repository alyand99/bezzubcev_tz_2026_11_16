#!/usr/bin/env python3
"""
report.py — CLI для построения отчёта по авансам по договорам.

Использование:
    python report.py --date 2026-11-10 --data ./data

Результат: CSV-файл report_YYYY-MM-DD.csv рядом с данными + вывод в консоль.
"""

import os
import sys
from datetime import date

from report_core import load_data, build_report, format_report_csv


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

    # Сохранение в файл рядом с данными
    report_filename = f'report_{date_str}.csv'
    report_path = os.path.join(data_dir, report_filename)
    with open(report_path, 'w', encoding='utf-8', newline='') as f:
        f.write(csv_output)
    print(f'Отчёт сохранён: {os.path.abspath(report_path)}')


if __name__ == '__main__':
    main()
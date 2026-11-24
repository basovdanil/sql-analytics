"""Генерирует demo/sales.csv: синтетические продажи за два года.

Данные придуманы для примера, к реальным продажам отношения не имеют.
Запуск: py -3 demo/make_demo.py
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent / "sales.csv"

STORES = (("Север", 1.00), ("Центр", 0.85), ("Юг", 0.70))
PRODUCTS = (
    ("Чай зелёный", "Бакалея", 240.0),
    ("Чай чёрный", "Бакалея", 210.0),
    ("Кофе зерновой", "Бакалея", 890.0),
    ("Печенье овсяное", "Кондитерка", 130.0),
    ("Шоколад тёмный", "Кондитерка", 320.0),
    ("Мёд липовый", "Бакалея", 560.0),
    ("Сок яблочный", "Напитки", 110.0),
    ("Вода минеральная", "Напитки", 70.0),
    ("Кружка керамическая", "Посуда", 450.0),
)
DISCOUNTS = (0, 0, 0, 0, 5, 5, 10, 15)
COLUMNS = ("date", "store", "category", "product", "units", "unit_price", "discount_pct")


def main(seed=7, days=730):
    rnd = random.Random(seed)
    start = date(2025, 1, 1)
    rows = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        weekend = day.weekday() >= 5
        season = 1.0 + (0.35 if day.month == 12 else 0.0) + (0.08 if day.month in (3, 9) else 0.0)
        for store, mult in STORES:
            picks = rnd.sample(PRODUCTS, k=rnd.choice((1, 2, 2, 3)))
            for product, category, price in picks:
                base = 5 * mult * season * (1.35 if weekend else 1.0)
                units = max(1, int(rnd.gauss(base, 1.8)))
                rows.append([
                    day.isoformat(), store, category, product,
                    units, f"{price:.2f}", rnd.choice(DISCOUNTS),
                ])

    with OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    print(f"{OUT} rows={len(rows)} bytes={OUT.stat().st_size}")


if __name__ == "__main__":
    main()

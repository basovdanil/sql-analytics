"""Отчёты по продажам в SQLite: загрузка CSV, 10 именованных запросов, JSON/CSV, самопроверка.

Коды возврата: 0 — успех, 2 — аргументы, 3 — нет файла или базы, 4 — данные не сходятся.
"""
import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEMO_CSV = ROOT / "demo" / "sales.csv"
COLUMNS = ("date", "store", "category", "product", "units", "unit_price", "discount_pct")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sales (
    id           INTEGER PRIMARY KEY,
    sale_date    TEXT    NOT NULL,
    store        TEXT    NOT NULL,
    category     TEXT    NOT NULL,
    product      TEXT    NOT NULL,
    units        INTEGER NOT NULL CHECK (units > 0),
    unit_price   REAL    NOT NULL CHECK (unit_price > 0),
    discount_pct REAL    NOT NULL CHECK (discount_pct BETWEEN 0 AND 100),
    revenue      REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS sales_date ON sales (sale_date);
CREATE INDEX IF NOT EXISTS sales_store ON sales (store);
"""

QUERIES = {
    "revenue_by_month": {
        "about": "выручка, число строк и средняя строка по месяцам",
        "sql": """
            SELECT substr(sale_date, 1, 7) AS month,
                   COUNT(*)               AS lines,
                   ROUND(SUM(revenue), 2) AS revenue,
                   ROUND(AVG(revenue), 2) AS avg_line
            FROM sales
            GROUP BY month
            ORDER BY month
        """,
    },
    "top_products": {
        "about": "топ-10 товаров по выручке с долей в общей выручке",
        "sql": """
            WITH t AS (
                SELECT product, category, SUM(revenue) AS revenue
                FROM sales
                GROUP BY product, category
            )
            SELECT product,
                   category,
                   ROUND(revenue, 2)                              AS revenue,
                   ROUND(100.0 * revenue / SUM(revenue) OVER (), 2) AS share_pct,
                   RANK() OVER (ORDER BY revenue DESC)            AS rnk
            FROM t
            ORDER BY revenue DESC
            LIMIT 10
        """,
    },
    "avg_check_by_store": {
        "about": "выручка и средний чек за день по магазинам",
        "sql": """
            WITH d AS (
                SELECT store, sale_date, SUM(revenue) AS revenue
                FROM sales
                GROUP BY store, sale_date
            )
            SELECT store,
                   COUNT(*)               AS days,
                   ROUND(SUM(revenue), 2) AS revenue,
                   ROUND(AVG(revenue), 2) AS avg_day_check
            FROM d
            GROUP BY store
            ORDER BY revenue DESC
        """,
    },
    "mom_growth": {
        "about": "рост выручки месяц к месяцу в процентах (окно LAG)",
        "sql": """
            WITH m AS (
                SELECT substr(sale_date, 1, 7) AS month, SUM(revenue) AS revenue
                FROM sales
                GROUP BY month
            )
            SELECT month,
                   ROUND(revenue, 2) AS revenue,
                   ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month))
                         / LAG(revenue) OVER (ORDER BY month), 2) AS mom_pct
            FROM m
            ORDER BY month
        """,
    },
    "running_total": {
        "about": "накопленная выручка по месяцам (окно с расширяющейся рамкой)",
        "sql": """
            WITH m AS (
                SELECT substr(sale_date, 1, 7) AS month, SUM(revenue) AS revenue
                FROM sales
                GROUP BY month
            )
            SELECT month,
                   ROUND(revenue, 2) AS revenue,
                   ROUND(SUM(revenue) OVER (ORDER BY month
                                            ROWS UNBOUNDED PRECEDING), 2) AS cumulative
            FROM m
            ORDER BY month
        """,
    },
    "category_share": {
        "about": "выручка и доля категорий с ранжированием",
        "sql": """
            SELECT category,
                   ROUND(SUM(revenue), 2)                              AS revenue,
                   ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2) AS share_pct,
                   RANK() OVER (ORDER BY SUM(revenue) DESC)            AS rnk
            FROM sales
            GROUP BY category
            ORDER BY revenue DESC
        """,
    },
    "best_month_per_store": {
        "about": "лучший месяц каждого магазина (ROW_NUMBER в разрезе магазина)",
        "sql": """
            WITH m AS (
                SELECT store, substr(sale_date, 1, 7) AS month, SUM(revenue) AS revenue
                FROM sales
                GROUP BY store, month
            ),
            ranked AS (
                SELECT store, month, revenue,
                       ROW_NUMBER() OVER (PARTITION BY store ORDER BY revenue DESC, month) AS rn
                FROM m
            )
            SELECT store, month, ROUND(revenue, 2) AS revenue
            FROM ranked
            WHERE rn = 1
            ORDER BY revenue DESC
        """,
    },
    "discount_impact": {
        "about": "сколько выручки дали строки со скидкой и без, размер скидки",
        "sql": """
            SELECT CASE WHEN discount_pct = 0 THEN 'без скидки' ELSE 'со скидкой' END AS kind,
                   COUNT(*)                             AS lines,
                   ROUND(SUM(units * unit_price), 2)    AS gross,
                   ROUND(SUM(units * unit_price - revenue), 2) AS discount_sum,
                   ROUND(SUM(revenue), 2)               AS revenue,
                   ROUND(AVG(discount_pct), 2)          AS avg_discount_pct
            FROM sales
            GROUP BY kind
            ORDER BY kind
        """,
    },
    "weekday_profile": {
        "about": "профиль выручки по дням недели",
        "sql": """
            SELECT CASE CAST(strftime('%w', sale_date) AS INTEGER)
                       WHEN 0 THEN 'вс' WHEN 1 THEN 'пн' WHEN 2 THEN 'вт'
                       WHEN 3 THEN 'ср' WHEN 4 THEN 'чт' WHEN 5 THEN 'пт'
                       ELSE 'сб'
                   END                            AS weekday,
                   CAST(strftime('%w', sale_date) AS INTEGER) AS weekday_num,
                   ROUND(SUM(revenue), 2)         AS revenue,
                   COUNT(DISTINCT sale_date)      AS days,
                   ROUND(SUM(revenue) / COUNT(DISTINCT sale_date), 2) AS avg_day_revenue
            FROM sales
            GROUP BY weekday_num
            ORDER BY weekday_num
        """,
    },
    "abc_products": {
        "about": "ABC-анализ товаров по накопленной доле выручки (80/95)",
        "sql": """
            WITH t AS (
                SELECT product, SUM(revenue) AS revenue
                FROM sales
                GROUP BY product
            ),
            c AS (
                SELECT product,
                       revenue,
                       100.0 * SUM(revenue) OVER (ORDER BY revenue DESC
                                                  ROWS UNBOUNDED PRECEDING)
                             / SUM(revenue) OVER () AS cum_pct
                FROM t
            )
            SELECT product,
                   ROUND(revenue, 2) AS revenue,
                   ROUND(cum_pct, 2) AS cum_pct,
                   CASE WHEN cum_pct <= 80 THEN 'A'
                        WHEN cum_pct <= 95 THEN 'B'
                        ELSE 'C'
                   END               AS abc
            FROM c
            ORDER BY revenue DESC
        """,
    },
}


def connect(db_path):
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def read_csv(csv_path):
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"в файле нет колонок: {', '.join(missing)}")
        for number, raw in enumerate(reader, start=2):
            value = (raw["date"] or "").strip()
            if len(value) != 10 or value[4] != "-" or value[7] != "-":
                raise ValueError(f"строка {number}: дата должна быть в формате ГГГГ-ММ-ДД")
            try:
                units = int(float(str(raw["units"]).strip()))
                price = float(str(raw["unit_price"]).strip().replace(" ", "").replace(",", "."))
                discount = float(str(raw["discount_pct"]).strip().replace(",", "."))
            except (TypeError, ValueError):
                raise ValueError(f"строка {number}: units, unit_price и discount_pct должны быть числами")
            if units <= 0 or price <= 0 or not 0 <= discount <= 100:
                raise ValueError(f"строка {number}: units > 0, unit_price > 0, discount_pct от 0 до 100")
            revenue = round(units * price * (1 - discount / 100.0), 2)
            rows.append((value, raw["store"].strip(), raw["category"].strip(),
                         raw["product"].strip(), units, price, discount, revenue))
    if not rows:
        raise ValueError("в файле нет строк с данными")
    return rows


def build(csv_path, db_path):
    rows = read_csv(csv_path)
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO sales (sale_date, store, category, product, units, unit_price, discount_pct, revenue)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return path, len(rows)


def run_query(conn, name):
    return [dict(row) for row in conn.execute(QUERIES[name]["sql"])]


def scalar(conn, sql):
    row = conn.execute(sql).fetchone()
    return None if row is None else row[0]


def check(conn):
    results = []

    def add(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    total = scalar(conn, "SELECT ROUND(SUM(revenue), 2) FROM sales") or 0.0
    add("rows", total > 0, f"всего выручки {total}")

    monthly = run_query(conn, "revenue_by_month")
    delta = round(sum(r["revenue"] for r in monthly) - total, 2)
    add("revenue_by_month", abs(delta) <= 0.05, f"расхождение с итогом {delta}")

    running = run_query(conn, "running_total")
    tail = running[-1]["cumulative"] if running else 0.0
    add("running_total_total", abs(tail - total) <= 0.05, f"последний итог {tail}")
    add("running_total_grows",
        all(b["cumulative"] >= a["cumulative"] for a, b in zip(running, running[1:])),
        "накопленная сумма не убывает")

    categories = run_query(conn, "category_share")
    share = round(sum(r["share_pct"] for r in categories), 2)
    add("category_share_100", abs(share - 100) <= 0.05, f"сумма долей {share}")

    stores = scalar(conn, "SELECT COUNT(DISTINCT store) FROM sales")
    best = run_query(conn, "best_month_per_store")
    add("best_month_per_store", len(best) == stores, f"строк {len(best)}, магазинов {stores}")

    weekday = run_query(conn, "weekday_profile")
    add("weekday_profile", len(weekday) == 7, f"строк {len(weekday)}")

    abc = run_query(conn, "abc_products")
    tail_cum = abc[-1]["cum_pct"] if abc else 0.0
    classes = {r["abc"] for r in abc} - {"A", "B", "C"}
    add("abc_cum_pct", abs(tail_cum - 100) <= 0.05, f"накопленная доля {tail_cum}")
    add("abc_classes", not classes, f"неизвестные классы: {sorted(classes) or 'нет'}")
    abc_delta = round(sum(r["revenue"] for r in abc) - total, 2)
    add("abc_total", abs(abc_delta) <= 0.05, f"расхождение с итогом {abc_delta}")

    impact = run_query(conn, "discount_impact")
    gross = round(sum(r["gross"] for r in impact), 2)
    cut = round(sum(r["discount_sum"] for r in impact), 2)
    net = round(sum(r["revenue"] for r in impact), 2)
    add("discount_impact", abs((gross - cut) - net) <= 0.1 and abs(net - total) <= 0.05,
        f"брутто {gross} - скидки {cut} = {round(gross - cut, 2)}, выручка {net}")

    growth = run_query(conn, "mom_growth")
    first_ok = bool(growth) and growth[0]["mom_pct"] is None
    rest_ok = all(r["mom_pct"] is not None for r in growth[1:])
    add("mom_growth", first_ok and rest_ok,
        "первый месяц без базы сравнения" if first_ok else "у первого месяца есть рост")

    return results


def print_table(rows):
    if not rows:
        print("(пусто)")
        return
    cols = list(rows[0].keys())
    body = [["" if row[c] is None else str(row[c]) for c in cols] for row in rows]
    numeric = []
    for column in zip(*body):
        values = [v for v in column if v]
        numeric.append(bool(values) and all(v.lstrip("-").replace(".", "", 1).isdigit() for v in values))
    widths = [max(len(c), *(len(v) for v in column)) for c, column in zip(cols, zip(*body))]
    header = "  ".join(c.ljust(w) for c, w in zip(cols, widths))
    print(header)
    print("-" * len(header))
    for row in body:
        cells = [(v.rjust(w) if num else v.ljust(w)) for v, w, num in zip(row, widths, numeric)]
        print("  ".join(cells))


def print_csv(rows, out_path):
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    print(f"CSV={path} rows={len(rows)}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="sales_sql.py",
        description="Отчёты по продажам в SQLite: загрузка CSV, 10 запросов, проверка сходимости.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="создать базу из CSV")
    p_build.add_argument("--csv", default=str(DEMO_CSV), help="файл с продажами")
    p_build.add_argument("--db", default="work/sales.db", help="путь к базе SQLite")

    sub.add_parser("list", help="список запросов")

    p_run = sub.add_parser("run", help="выполнить запрос")
    p_run.add_argument("query", choices=sorted(QUERIES), help="имя запроса")
    p_run.add_argument("--db", default="work/sales.db")
    p_run.add_argument("--json", action="store_true", help="вывод в JSON")
    p_run.add_argument("--csv", dest="csv_out", help="сохранить результат в CSV")
    p_run.add_argument("--limit", type=int, default=0, help="оставить первые N строк")

    p_check = sub.add_parser("check", help="проверить сходимость отчётов")
    p_check.add_argument("--db", default="work/sales.db")

    args = parser.parse_args(argv)

    if args.cmd == "list":
        for name in sorted(QUERIES):
            print(f"{name:22} {QUERIES[name]['about']}")
        return 0

    try:
        if args.cmd == "build":
            path, count = build(args.csv, args.db)
            print(f"DB={path} rows={count}")
            return 0

        conn = connect(args.db)
        try:
            if args.cmd == "check":
                results = check(conn)
                bad = 0
                for name, ok, detail in results:
                    if not ok:
                        bad += 1
                    print(f"CHECK {name}={'OK' if ok else 'FAIL'} {detail}".rstrip())
                print(f"CHECKED={len(results)} FAILED={bad}")
                return 0 if bad == 0 else 4

            rows = run_query(conn, args.query)
            if args.limit > 0:
                rows = rows[: args.limit]
            if args.csv_out:
                print_csv(rows, args.csv_out)
            elif args.json:
                print(json.dumps({"query": args.query, "about": QUERIES[args.query]["about"],
                                  "count": len(rows), "rows": rows}, ensure_ascii=False, indent=2))
            else:
                print(f"# {args.query}: {QUERIES[args.query]['about']}")
                print_table(rows)
            return 0
        finally:
            conn.close()
    except FileNotFoundError as exc:
        print(f"нет файла или базы: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())

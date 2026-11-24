import csv
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sales_sql  # noqa: E402

HEADER = list(sales_sql.COLUMNS)

# 7 подряд идущих дней января 2025 покрывают все дни недели
ROWS = [
    ("2025-01-01", "Север", "Бакалея", "Кофе", 10, 100.0, 0),
    ("2025-01-02", "Север", "Бакалея", "Кофе", 8, 100.0, 10),
    ("2025-01-03", "Север", "Напитки", "Сок", 4, 50.0, 0),
    ("2025-01-04", "Центр", "Бакалея", "Кофе", 6, 100.0, 5),
    ("2025-01-05", "Центр", "Напитки", "Сок", 5, 50.0, 0),
    ("2025-01-06", "Центр", "Посуда", "Кружка", 2, 300.0, 15),
    ("2025-01-07", "Юг", "Посуда", "Кружка", 3, 300.0, 0),
]

BAD_ROWS = [
    ("01.01.2025", "Север", "Бакалея", "Кофе", 10, 100.0, 0),
]

NUM_ROWS = [
    ("2025-01-01", "Север", "Бакалея", "Кофе", "десять", 100.0, 0),
]


def write_csv(path, rows, header=HEADER):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


class ReadCsvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_revenue_includes_discount(self):
        path = write_csv(self.dir / "s.csv", ROWS[:2])
        rows = sales_sql.read_csv(path)
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0][-1], 1000.0)
        self.assertAlmostEqual(rows[1][-1], 720.0)

    def test_bad_date_rejected(self):
        path = write_csv(self.dir / "s.csv", BAD_ROWS)
        with self.assertRaises(ValueError):
            sales_sql.read_csv(path)

    def test_bad_number_rejected(self):
        path = write_csv(self.dir / "s.csv", NUM_ROWS)
        with self.assertRaises(ValueError):
            sales_sql.read_csv(path)

    def test_missing_columns_rejected(self):
        path = write_csv(self.dir / "s.csv", [("2025-01-01", "Север")], header=HEADER[:2])
        with self.assertRaises(ValueError) as ctx:
            sales_sql.read_csv(path)
        self.assertIn("колонок", str(ctx.exception))

    def test_discount_out_of_range_rejected(self):
        row = ("2025-01-01", "Север", "Бакалея", "Кофе", 10, 100.0, 120)
        path = write_csv(self.dir / "s.csv", [row])
        with self.assertRaises(ValueError):
            sales_sql.read_csv(path)

    def test_empty_csv_rejected(self):
        path = write_csv(self.dir / "s.csv", [])
        with self.assertRaises(ValueError):
            sales_sql.read_csv(path)


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.csv = write_csv(self.dir / "s.csv", ROWS)
        self.db = self.dir / "s.db"
        sales_sql.build(self.csv, self.db)
        self.conn = sales_sql.connect(self.db)
        self.addCleanup(self.conn.close)

    def query(self, name):
        return sales_sql.run_query(self.conn, name)

    def test_check_passes(self):
        results = sales_sql.check(self.conn)
        failed = [name for name, ok, _ in results if not ok]
        self.assertEqual(failed, [])
        self.assertGreaterEqual(len(results), 10)

    def test_monthly_sums_to_total(self):
        monthly = self.query("revenue_by_month")
        total = sum(r["revenue"] for r in monthly)
        self.assertAlmostEqual(total, sales_sql.scalar(self.conn, "SELECT SUM(revenue) FROM sales"))

    def test_share_100(self):
        share = sum(r["share_pct"] for r in self.query("category_share"))
        self.assertAlmostEqual(share, 100.0, places=2)

    def test_top_products_sorted_and_capped(self):
        rows = self.query("top_products")
        self.assertLessEqual(len(rows), 10)
        revenues = [r["revenue"] for r in rows]
        self.assertEqual(revenues, sorted(revenues, reverse=True))

    def test_abc_last_cum_100(self):
        rows = self.query("abc_products")
        self.assertAlmostEqual(rows[-1]["cum_pct"], 100.0, places=2)
        self.assertTrue({r["abc"] for r in rows} <= {"A", "B", "C"})

    def test_mom_first_has_no_base(self):
        rows = self.query("mom_growth")
        self.assertIsNone(rows[0]["mom_pct"])
        for row in rows[1:]:
            self.assertIsNotNone(row["mom_pct"])

    def test_best_month_one_per_store(self):
        rows = self.query("best_month_per_store")
        stores = [r["store"] for r in rows]
        self.assertEqual(len(stores), len(set(stores)))

    def test_discount_impact_balances(self):
        rows = self.query("discount_impact")
        gross = sum(r["gross"] for r in rows)
        cut = sum(r["discount_sum"] for r in rows)
        self.assertAlmostEqual(gross - cut, sum(r["revenue"] for r in rows), places=2)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_missing_db_returns_3(self):
        code = sales_sql.main(["run", "top_products", "--db", str(self.dir / "nope.db")])
        self.assertEqual(code, 3)

    def test_unknown_query_returns_2(self):
        with self.assertRaises(SystemExit) as ctx:
            sales_sql.main(["run", "nope"])
        self.assertEqual(ctx.exception.code, 2)

    def test_build_run_check(self):
        csv_path = write_csv(self.dir / "s.csv", ROWS)
        db_path = self.dir / "s.db"
        self.assertEqual(sales_sql.main(["build", "--csv", str(csv_path), "--db", str(db_path)]), 0)
        self.assertEqual(sales_sql.main(["run", "top_products", "--db", str(db_path), "--json"]), 0)
        self.assertEqual(sales_sql.main(["check", "--db", str(db_path)]), 0)

    def test_check_fails_on_empty_table(self):
        csv_path = write_csv(self.dir / "s.csv", ROWS)
        db_path = self.dir / "s.db"
        sales_sql.main(["build", "--csv", str(csv_path), "--db", str(db_path)])
        conn = sqlite3.connect(db_path)
        with conn:
            conn.execute("DELETE FROM sales")
        conn.close()
        self.assertEqual(sales_sql.main(["check", "--db", str(db_path)]), 4)

    def test_demo_csv_passes_check(self):
        demo = ROOT / "demo" / "sales.csv"
        if not demo.is_file():
            self.skipTest("нет demo/sales.csv")
        db_path = self.dir / "demo.db"
        self.assertEqual(sales_sql.main(["build", "--csv", str(demo), "--db", str(db_path)]), 0)
        self.assertEqual(sales_sql.main(["check", "--db", str(db_path)]), 0)


if __name__ == "__main__":
    unittest.main()

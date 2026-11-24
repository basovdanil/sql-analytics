# sql-analytics

<p align="center">
  <img src="https://raw.githubusercontent.com/basovdanil/basovdanil/main/assets/tools.png"
       alt="Eight tools with tests and exit codes" width="100%">
</p>

[![tests](https://github.com/basovdanil/sql-analytics/actions/workflows/tests.yml/badge.svg)](https://github.com/basovdanil/sql-analytics/actions/workflows/tests.yml)

Ten named SQL reports over a sales table in SQLite: revenue by month, top products, weekday
profile, running total, category shares, best month per store, ABC analysis, discount impact and
month-over-month growth. SQL does the counting; Python only loads the CSV and prints the result.

Python 3.9+ (tested on 3.11, SQLite 3.38.4). No external dependencies.

## Quick start

```bash
python demo/make_demo.py          # 4 414 synthetic sales rows
python sales_sql.py build         # load into SQLite
python sales_sql.py list          # available reports
python sales_sql.py run top_products
python sales_sql.py check         # 12 reconciliations before the numbers go out
```

## What makes it trustworthy

`check` reconciles the reports against each other: monthly sum equals the total, the running total
ends at the same number and never decreases, category shares add up to 100 %, each store has exactly
one best month, the weekday profile has 7 rows, ABC ends at 100 %, and gross minus discounts equals
revenue. On the demo base: `CHECKED=12 FAILED=0`, exit `0`.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | success, all checks passed |
| `2` | bad arguments (`argparse`) |
| `3` | CSV or database missing |
| `4` | data error or a failed reconciliation |

## Tests

```
python -m unittest discover -s tests
```

19 tests: CSV parsing and rejection of broken dates, numbers, discounts outside 0–100, empty files
and missing columns; report arithmetic; CLI exit codes.

## Scope

The demo data is synthetic. The reports are written for SQLite; the window functions used are
portable to PostgreSQL, the file-loading part is not.

---

More projects: [github.com/basovdanil](https://github.com/basovdanil) · write-ups: [portfolio](https://basovdanil.github.io/portfolio/)

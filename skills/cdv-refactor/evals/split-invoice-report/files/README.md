# ledger-report

Turns a CSV of invoice lines into a plain-text report.

    python3 -m invoicing.cli tests/golden/basic.csv

Layout:

- `invoicing/report.py` - everything: parsing the CSV, taxes and discounts, rendering the text.
- `invoicing/cli.py` - the command line.
- `tests/golden/` - recorded output (`basic.txt`) and recorded log (`basic.log`) for `basic.csv`.

Run the tests with `python3 -m unittest discover -s tests`.

The log lines are read by the month-end check, which filters on the logger name `invoicing.report`.

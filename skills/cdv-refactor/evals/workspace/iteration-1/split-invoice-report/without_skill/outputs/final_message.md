I split `invoicing/report.py` into three modules. All 15 tests pass (the 5 existing ones plus 10 new ones), and the CLI output on `tests/golden/basic.csv` matches the golden file byte for byte. The work is on `main` in two commits.

**What changed**
- `invoicing/parsing.py` turns CSV lines into invoice lines and counts the skipped ones.
- `invoicing/tax.py` holds `InvoiceLine`, the tax rates, the bulk discount and the per-customer and grand totals, plus `round_half_up`.
- `invoicing/rendering.py` holds the text layout and `money`.
- `invoicing/report.py` is now a thin `InvoiceReport` over those three. It keeps every public method (`from_lines`, `from_file`, `tax_rate`, `tax_for`, `customers`, `customer_totals`, `grand_totals`, `render_customer`, `render`). `from invoicing.report import InvoiceReport` still works.
- It also re-exports what the existing tests import: `TAX_RATES`, `_round_half_up`, `_money`, `InvoiceLine` and the constants.

I added `tests/test_modules.py`, which tests each module on its own, and updated the README's layout section.

**Decisions**
- **Logger name:** the README says the month-end check filters logs on the logger name `invoicing.report`, and the golden log pins it. `parsing.py` therefore uses `logging.getLogger("invoicing.report")` explicitly instead of `__name__`. A comment in the code and a line in the README say not to change it.
- **`InvoiceLine` location:** I put it in `tax.py` because its discount and net maths belong there, which avoids a fourth module. A tax-to-parsing import is the only coupling between those two.
- **Dropped private methods:** `_parse_line`, `_rule` and `_row` are no longer methods on `InvoiceReport`. They are now module functions in `parsing.py` and `rendering.py`. Nothing in the repo called them.

**Questions for you**
1. Does anything outside this repo use those private methods or `InvoiceReport.lines` and `skipped` directly? I kept `lines` and `skipped`.
2. Is the logger-name pin enough, or does the month-end check also depend on the exact log messages? I left them unchanged.
3. Would you rather `InvoiceLine` be in its own module (for example `models.py`)? It is a small move.

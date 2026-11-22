I split `invoicing/report.py` into three modules and committed the work on `main`. All 8 tests pass.

`from invoicing.report import InvoiceReport` still works. As a stronger check, I ran the old class and the new one on 2,000 random inputs. Report text, log lines and skipped counts were identical. I also planted three changes (a tax rate, the report width, the logger name) and each turned a test red. I reverted them afterwards.

**New layout**
- `invoicing/parsing.py` turns CSV lines into `InvoiceLine` objects (`parse_lines`, `parse_line`).
- `invoicing/tax.py` holds `InvoiceLine`, the rates, the bulk discount and the totals.
- `invoicing/rendering.py` builds the text report.
- `invoicing/report.py` keeps `InvoiceReport` as a thin wrapper over the three. It also re-exports the names the tests import (`TAX_RATES`, `_round_half_up`, and so on).
- I updated the README layout section to match.

**Commits**
1. `b442988` adds `tests/test_facade.py`, which pins the public names, the `InvoiceReport` methods and the logger name before the split. It also opens the `docs/research/2026-11-22-split-invoice-report/` state folder that the refactor skill asks for.
2. `8a48256` moves the code into the new modules unchanged, as mixins.
3. `1996cb0` turns the mixins into plain functions.
4. `86c7123` records the state of the work.

**Logger name:** the log lines are read by the month-end check, which filters on the logger name `invoicing.report`. A plain `getLogger(__name__)` in `parsing.py` would have renamed it to `invoicing.parsing`. So `parsing.py` names `invoicing.report` explicitly, with a comment saying why, and `tests/test_facade.py` guards it.

**Questions for you**
1. I took these defaults, recorded in `decisions.md`:
   - Land the work as plain commits on `main`.
   - Freeze the logger name, the import path, the public methods and the report text.
   - Allow no behaviour change.

   Say if any should differ.
2. The private methods `InvoiceReport._parse_line`, `_rule` and `_row` no longer exist; their code is now module functions. Does anything outside this repo call them? If so, I'll add thin methods back.
3. `InvoiceReport.customer_totals` no longer goes through `self.tax_for`. A subclass that overrides `tax_for` would therefore no longer change the totals. Nothing in the repo does that.
4. I found no existing defects, so there is no `bugs.md`.

The skill's own checks (`docs_follow_code` and `records_guard`) passed on the changes. I did not run the ratchet or instruction-path checks, because this repo has no counters or instruction files for them to read.

"""Build a plain-text invoice report from CSV lines.

Input columns: customer,item,qty,unit_price,country,reverse_charge
"""
import logging
from collections import OrderedDict
from decimal import Decimal, ROUND_HALF_UP

log = logging.getLogger(__name__)

TAX_RATES = {
    "DE": Decimal("0.19"),
    "FR": Decimal("0.20"),
    "NL": Decimal("0.21"),
    "PT": Decimal("0.23"),
    "ES": Decimal("0.21"),
}
DEFAULT_TAX_RATE = Decimal("0.20")
BULK_QTY = 10
BULK_DISCOUNT = Decimal("0.05")
REPORT_WIDTH = 48


def _round_half_up(value):
    """Round a Decimal to cents, halves away from zero."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money(value):
    return f"{_round_half_up(value):,.2f}"


class InvoiceLine:
    def __init__(self, customer, item, qty, unit_price, country, reverse_charge):
        self.customer = customer
        self.item = item
        self.qty = qty
        self.unit_price = unit_price
        self.country = country
        self.reverse_charge = reverse_charge

    @property
    def gross(self):
        return self.unit_price * self.qty

    @property
    def discount(self):
        if self.qty >= BULK_QTY:
            return self.gross * BULK_DISCOUNT
        return Decimal("0")

    @property
    def net(self):
        return self.gross - self.discount


class InvoiceReport:
    """Parses invoice lines, computes taxes and renders the report."""

    def __init__(self, title="Invoice report"):
        self.title = title
        self.lines = []
        self.skipped = 0

    # ---------------------------------------------------------------- parsing
    @classmethod
    def from_lines(cls, raw_lines, title="Invoice report"):
        report = cls(title=title)
        for number, raw in enumerate(raw_lines, start=1):
            report._parse_line(number, raw)
        return report

    @classmethod
    def from_file(cls, path, title="Invoice report"):
        with open(path, encoding="utf-8") as handle:
            return cls.from_lines(handle.read().splitlines(), title=title)

    def _parse_line(self, number, raw):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            return
        if raw.lower().startswith("customer,"):
            return
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 6:
            log.warning("skipping malformed line %d: expected 6 fields, got %d", number, len(parts))
            self.skipped += 1
            return
        customer, item, qty, unit_price, country, reverse_charge = parts
        try:
            qty = int(qty)
            unit_price = Decimal(unit_price)
        except (ValueError, ArithmeticError):
            log.warning("skipping malformed line %d: bad number", number)
            self.skipped += 1
            return
        if qty <= 0:
            log.warning("skipping line %d: quantity must be positive", number)
            self.skipped += 1
            return
        country = country.upper()
        if country not in TAX_RATES:
            log.info("line %d: unknown country %s, default rate applies", number, country)
        self.lines.append(
            InvoiceLine(
                customer=customer,
                item=item,
                qty=qty,
                unit_price=unit_price,
                country=country,
                reverse_charge=reverse_charge.lower() in ("1", "yes", "true", "y"),
            )
        )

    # -------------------------------------------------------------------- tax
    @staticmethod
    def tax_rate(country):
        return TAX_RATES.get(country, DEFAULT_TAX_RATE)

    def tax_for(self, line):
        if line.reverse_charge:
            return Decimal("0")
        return line.net * self.tax_rate(line.country)

    def customers(self):
        grouped = OrderedDict()
        for line in self.lines:
            grouped.setdefault(line.customer, []).append(line)
        return grouped

    def customer_totals(self, lines):
        net = sum((line.net for line in lines), Decimal("0"))
        discount = sum((line.discount for line in lines), Decimal("0"))
        tax = sum((self.tax_for(line) for line in lines), Decimal("0"))
        return {"net": net, "discount": discount, "tax": tax, "total": net + tax}

    def grand_totals(self):
        totals = {"net": Decimal("0"), "discount": Decimal("0"), "tax": Decimal("0"), "total": Decimal("0")}
        for lines in self.customers().values():
            for key, value in self.customer_totals(lines).items():
                totals[key] += value
        return totals

    # -------------------------------------------------------------- rendering
    def _rule(self, char="-"):
        return char * REPORT_WIDTH

    def _row(self, label, value):
        gap = REPORT_WIDTH - len(label) - len(value)
        return label + " " * max(gap, 1) + value

    def render_customer(self, customer, lines):
        out = [customer]
        for line in lines:
            label = f"  {line.qty} x {line.item}"
            if line.reverse_charge:
                label += " (RC)"
            out.append(self._row(label, _money(line.net)))
        totals = self.customer_totals(lines)
        if totals["discount"]:
            out.append(self._row("  bulk discount", "-" + _money(totals["discount"])))
        out.append(self._row("  tax", _money(totals["tax"])))
        out.append(self._row("  total", _money(totals["total"])))
        return out

    def render(self):
        out = [self._rule("="), self.title.center(REPORT_WIDTH).rstrip(), self._rule("=")]
        for customer, lines in self.customers().items():
            out.extend(self.render_customer(customer, lines))
            out.append(self._rule())
        totals = self.grand_totals()
        out.append(self._row("NET", _money(totals["net"])))
        out.append(self._row("TAX", _money(totals["tax"])))
        out.append(self._row("TOTAL", _money(totals["total"])))
        if self.skipped:
            out.append(f"({self.skipped} line(s) skipped)")
        return "\n".join(out) + "\n"

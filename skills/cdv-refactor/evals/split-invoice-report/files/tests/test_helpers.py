import unittest
from decimal import Decimal

from invoicing.report import InvoiceReport, TAX_RATES, _round_half_up


class HelperTest(unittest.TestCase):
    def test_round_half_up(self):
        self.assertEqual(_round_half_up(Decimal("2.345")), Decimal("2.35"))
        self.assertEqual(_round_half_up(Decimal("2.344")), Decimal("2.34"))

    def test_known_rate(self):
        self.assertEqual(InvoiceReport.tax_rate("DE"), TAX_RATES["DE"])

    def test_title_is_kept(self):
        self.assertEqual(InvoiceReport(title="Q3").title, "Q3")


if __name__ == "__main__":
    unittest.main()

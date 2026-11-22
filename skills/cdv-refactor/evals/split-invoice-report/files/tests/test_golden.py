"""Golden-file tests: the rendered report and the log it writes are recorded byte for byte."""
import io
import logging
import pathlib
import unittest

from invoicing.report import InvoiceReport

GOLDEN = pathlib.Path(__file__).parent / "golden"


class GoldenReportTest(unittest.TestCase):
    def setUp(self):
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        root = logging.getLogger()
        self.old_level = root.level
        root.setLevel(logging.INFO)
        root.addHandler(self.handler)

    def tearDown(self):
        root = logging.getLogger()
        root.removeHandler(self.handler)
        root.setLevel(self.old_level)

    def test_basic_report_matches_golden(self):
        report = InvoiceReport.from_file(GOLDEN / "basic.csv")
        expected = (GOLDEN / "basic.txt").read_text(encoding="utf-8")
        self.assertEqual(report.render(), expected)

    def test_basic_log_matches_golden(self):
        InvoiceReport.from_file(GOLDEN / "basic.csv")
        expected = (GOLDEN / "basic.log").read_text(encoding="utf-8")
        self.assertEqual(self.stream.getvalue(), expected)


if __name__ == "__main__":
    unittest.main()

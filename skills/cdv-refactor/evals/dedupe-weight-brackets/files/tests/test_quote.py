import unittest

from shipping.quote import quote


class QuoteTest(unittest.TestCase):
    def test_light_intl(self):
        self.assertEqual(quote(0.5, "intl"), 12.5)

    def test_mid_intl_express(self):
        self.assertEqual(quote(3, "intl", express=True), 20.4)

    def test_heavy_intl(self):
        self.assertEqual(quote(12, "intl"), 27.5)

    def test_rejects_zero(self):
        with self.assertRaises(ValueError):
            quote(0, "intl")


if __name__ == "__main__":
    unittest.main()

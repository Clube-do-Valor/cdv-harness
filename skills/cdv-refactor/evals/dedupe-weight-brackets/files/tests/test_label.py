import unittest

from shipping.label import label_cost


class LabelTest(unittest.TestCase):
    def test_light(self):
        self.assertEqual(label_cost(0.5), 6.25)

    def test_mid(self):
        self.assertEqual(label_cost(7), 15.25)

    def test_rejects_negative(self):
        with self.assertRaises(ValueError):
            label_cost(-1)


if __name__ == "__main__":
    unittest.main()

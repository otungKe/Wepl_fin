from decimal import Decimal

from django.test import SimpleTestCase
from hypothesis import given
from hypothesis import strategies as st

from wepl.money import allocate, to_money


class ToMoneyTests(SimpleTestCase):
    def test_parses_strings_and_decimals(self):
        self.assertEqual(to_money("10"), Decimal("10.00"))
        self.assertEqual(to_money(Decimal("1.5")), Decimal("1.50"))

    def test_rejects_floats(self):
        with self.assertRaises(TypeError):
            to_money(0.1)

    def test_rejects_fractions_of_a_cent(self):
        with self.assertRaises(ValueError):
            to_money("1.005")


class AllocateTests(SimpleTestCase):
    def test_splits_exactly(self):
        self.assertEqual(allocate(Decimal("100.00"), {1: 1, 2: 1, 3: 1}),
                         {1: Decimal("33.34"), 2: Decimal("33.33"), 3: Decimal("33.33")})

    def test_zero_weights_split_equally(self):
        self.assertEqual(allocate(Decimal("1.00"), {1: 0, 2: 0}), {1: Decimal("0.50"), 2: Decimal("0.50")})

    def test_negative_weights_get_nothing(self):
        self.assertEqual(allocate(Decimal("5.00"), {1: -3, 2: 2}), {2: Decimal("5.00")})

    @given(st.integers(1, 10**9), st.dictionaries(st.integers(1, 50), st.integers(-100, 10**6), min_size=1))
    def test_parts_always_sum_to_whole(self, cents, weights):
        amount = Decimal(cents) / 100
        parts = allocate(amount, weights)
        self.assertEqual(sum(parts.values()), amount)
        self.assertTrue(all(v > 0 for v in parts.values()))

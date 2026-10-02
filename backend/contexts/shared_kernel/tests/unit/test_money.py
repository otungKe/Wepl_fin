from decimal import Decimal

from django.test import SimpleTestCase
from hypothesis import given
from hypothesis import strategies as st

from contexts.shared_kernel.money import Money, MoneyError


class MoneyTests(SimpleTestCase):
    def test_parses_strings_and_decimals(self):
        self.assertEqual(Money("10").amount, Decimal("10.00"))
        self.assertEqual(Money(Decimal("1.5")), Money("1.50"))

    def test_rejects_floats_fractions_of_a_cent_and_nonsense(self):
        for bad in (0.1, "1.005", "abc", "NaN", "Infinity"):
            with self.assertRaises(MoneyError):
                Money(bad)

    def test_currencies_never_mix(self):
        with self.assertRaises(MoneyError):
            Money("1") + Money("1", "USD")
        with self.assertRaises(MoneyError):
            Money("1") < Money("2", "USD")

    def test_allocate_splits_exactly(self):
        self.assertEqual(Money("100").allocate({1: 1, 2: 1, 3: 1}),
                         {1: Money("33.34"), 2: Money("33.33"), 3: Money("33.33")})

    def test_allocate_zero_weights_split_equally_and_negatives_get_nothing(self):
        self.assertEqual(Money("1").allocate({1: 0, 2: 0}), {1: Money("0.50"), 2: Money("0.50")})
        self.assertEqual(Money("5").allocate({1: -3, 2: 2}), {2: Money("5")})

    @given(st.integers(1, 10**9), st.dictionaries(st.integers(1, 50), st.integers(-100, 10**6), min_size=1))
    def test_parts_always_sum_to_whole(self, cents, weights):
        whole = Money(Decimal(cents) / 100)
        parts = whole.allocate(weights)
        total = Money.zero()
        for p in parts.values():
            self.assertTrue(p.is_positive)
            total += p
        self.assertEqual(total, whole)

from django.test import SimpleTestCase

from contexts.communities.domain.fund import FUND_NAME_MAX, FundError, check_currency, clean_fund_name


class FundNameTests(SimpleTestCase):
    def test_names_are_trimmed_and_inner_spaces_collapsed(self):
        self.assertEqual(clean_fund_name("  Main   savings "), "Main savings")

    def test_a_name_is_required(self):
        for blank in (None, "", "   "):
            with self.subTest(blank), self.assertRaisesMessage(FundError, "needs a name"):
                clean_fund_name(blank)

    def test_a_name_has_a_maximum_length(self):
        self.assertEqual(len(clean_fund_name("x" * FUND_NAME_MAX)), FUND_NAME_MAX)
        with self.assertRaisesMessage(FundError, "at most"):
            clean_fund_name("x" * (FUND_NAME_MAX + 1))

    def test_case_is_kept_as_given(self):  # whether case distinguishes names is undecided (review C1)
        self.assertEqual(clean_fund_name("savings"), "savings")


class CurrencyTests(SimpleTestCase):
    def test_a_currency_is_three_capital_letters(self):
        self.assertEqual(check_currency("KES"), "KES")
        self.assertEqual(check_currency("USD"), "USD")  # which codes are allowed is review D3
        for bad in ("kes", "X1", "", "USDX", " KES", None, 404):
            with self.subTest(bad), self.assertRaises(FundError):
                check_currency(bad)

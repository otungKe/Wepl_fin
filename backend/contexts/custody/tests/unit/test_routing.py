from django.test import SimpleTestCase

from contexts.custody.domain.routing import fund_for, split_across_funds, unclear_code, unknown_words
from contexts.governance.contract import AccountReturns
from contexts.shared_kernel.money import Money

CODES, DEFAULT, WELFARE = {"WEL": 2, "EDU": 3}, 1, 2


class FundForTests(SimpleTestCase):
    def test_a_code_anywhere_in_the_reference_names_the_fund_and_leaves_the_rest(self):
        for reference, rest in (("0712597024 WEL", "0712597024"), ("wel 0712597024", "0712597024"),
                                ("0712597024wel", "0712597024"), ("WEL", ""), ("M05 Wel", "M05")):
            with self.subTest(reference):
                self.assertEqual(fund_for(reference, CODES, DEFAULT), (WELFARE, rest))

    def test_without_a_known_code_the_default_fund_and_the_reference_unchanged(self):
        for reference in ("0712597024", "M05", "0712597024 WLF", "", "WELFARE"):
            with self.subTest(reference):
                self.assertEqual(fund_for(reference, CODES, DEFAULT), (DEFAULT, reference))

    def test_two_funds_named_is_no_fund_named(self):
        self.assertEqual(fund_for("WEL EDU", CODES, DEFAULT), (DEFAULT, "WEL EDU"))
        self.assertEqual(fund_for("WEL 0712597024 wel", CODES, DEFAULT), (WELFARE, "0712597024 wel"))

    def test_unclear_says_why_only_when_no_one_fund_is_named(self):
        self.assertEqual(unclear_code("WEL EDU", CODES), "it quotes the codes of two funds (WEL and EDU)")
        self.assertEqual(unclear_code("0712597024 WLF", CODES), "WLF is not the code of one of the group's open funds")
        for clear in ("0712597024 WEL", "M05", "WEL JAN", ""):
            with self.subTest(clear):
                self.assertEqual(unclear_code(clear, CODES), "")

    def test_unknown_words_ignore_member_codes(self):
        self.assertEqual(unknown_words("M05 WEL 0712597024", CODES), [])
        self.assertEqual(unknown_words("0712597024 wlf", CODES), ["WLF"])


class SplitTests(SimpleTestCase):
    def test_by_fund_balance_follows_what_each_fund_holds(self):
        held = {1: Money("3000"), 2: Money("1000"), 3: Money("0"), 4: Money("-50")}
        self.assertEqual(split_across_funds(Money("40"), held, AccountReturns.BY_FUND_BALANCE, DEFAULT),
                         {1: Money("30"), 2: Money("10")})

    def test_the_default_fund_takes_it_all_when_chosen_or_nothing_is_held(self):
        held = {1: Money("3000"), 2: Money("1000")}
        self.assertEqual(split_across_funds(Money("40"), held, AccountReturns.DEFAULT_FUND, DEFAULT),
                         {DEFAULT: Money("40")})
        self.assertEqual(split_across_funds(Money("40"), {2: Money("0")}, AccountReturns.BY_FUND_BALANCE, DEFAULT),
                         {DEFAULT: Money("40")})

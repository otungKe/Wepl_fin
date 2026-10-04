"""ADR-0014: who shares an event, judged on the day it happened."""
from datetime import datetime, timedelta, timezone
from unittest import TestCase

from contexts.custody.domain.sharing import Event, Spell, sharers
from contexts.governance.contract import LeaverBalances
from contexts.shared_kernel.money import Money

T = datetime(2026, 10, 1, tzinfo=timezone.utc)
DAY = timedelta(days=1)
PAID, FROZEN = LeaverBalances.SHARES_UNTIL_PAID, LeaverBalances.FROZEN_AT_LEAVING


class SharersTests(TestCase):
    def who(self, spells, event=Event.RETURNS, balances=None):
        return sharers(spells, at=T, event=event, balances=balances or {s.membership_id: Money("1")
                                                                       for s in spells})

    def test_members_in_the_group_that_day_share_everything(self):
        spells = [Spell(1, T - DAY, None), Spell(2, T - DAY, T + DAY), Spell(3, T, None)]
        for event in Event:
            self.assertEqual(self.who(spells, event), [1, 2, 3])

    def test_a_member_who_joined_after_the_event_shares_nothing_from_it(self):
        self.assertEqual(self.who([Spell(1, T + DAY, None)]), [])

    def test_a_member_who_left_at_or_before_the_event_follows_the_rule_in_force_when_they_left(self):
        spells = [Spell(1, T - 2 * DAY, T - DAY, PAID), Spell(2, T - 2 * DAY, T, FROZEN),
                  Spell(3, T - 2 * DAY, T - DAY, None)]
        self.assertEqual(self.who(spells), [1])
        self.assertEqual(self.who(spells, Event.PAYOUT), [])

    def test_a_leaver_with_nothing_left_stops_sharing(self):
        spell = [Spell(1, T - 2 * DAY, T - DAY, PAID)]
        for balance in ({1: Money("0")}, {1: Money("-5")}, {}):
            self.assertEqual(sharers(spell, at=T, event=Event.RETURNS, balances=balance), [])

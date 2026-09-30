from django.test import SimpleTestCase

from contexts.communities.domain.membership import (TITLE_MAX, MembershipError, clean_title, ensure_can_leave,
                                                    member_code)


class TitleTests(SimpleTestCase):
    def test_no_title_is_always_the_empty_string(self):
        for raw in (None, "", "   ", "\t\n"):
            self.assertEqual(clean_title(raw), "")

    def test_whitespace_collapses(self):
        self.assertEqual(clean_title("  Group   Treasurer  "), "Group Treasurer")

    def test_any_label_the_group_uses(self):
        for title in ("Pastor", "Coordinator", "Elder", "Team Lead"):
            self.assertEqual(clean_title(title), title)

    def test_too_long(self):
        self.assertEqual(len(clean_title("x" * TITLE_MAX)), TITLE_MAX)
        with self.assertRaises(MembershipError):
            clean_title("x" * (TITLE_MAX + 1))


class CodeTests(SimpleTestCase):
    def test_format(self):
        self.assertEqual([member_code(n) for n in (1, 9, 42, 100)], ["M01", "M09", "M42", "M100"])

    def test_sequence_starts_at_one(self):
        with self.assertRaises(MembershipError):
            member_code(0)


class LifecycleTests(SimpleTestCase):
    def test_only_an_active_membership_can_end(self):
        ensure_can_leave("active")
        with self.assertRaisesMessage(MembershipError, "already ended"):
            ensure_can_leave("left")

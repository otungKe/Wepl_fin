import base64
from datetime import datetime, timedelta, timezone
from unittest import TestCase

from contexts.operators.domain import signin, totp
from contexts.operators.domain.capabilities import OperatorCapability, allowed
from contexts.operators.domain.signin import SessionFacts, Stage, session_refusal

T = datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc)


class TotpTests(TestCase):
    RFC = base64.b32encode(b"12345678901234567890").decode()  # RFC 6238 appendix B

    def test_the_rfc_vectors(self):
        for at, expected in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924")):
            self.assertEqual(totp.code_at(self.RFC, totp.step_of(at)), expected)

    def test_a_code_is_accepted_once_and_only_near_its_time(self):
        now = 1234567890
        code = totp.code_at(self.RFC, totp.step_of(now))
        step = totp.matching_step(self.RFC, code, now=now, last_used=None)
        self.assertEqual(step, totp.step_of(now))
        self.assertIsNone(totp.matching_step(self.RFC, code, now=now, last_used=step))  # replayed
        self.assertIsNone(totp.matching_step(self.RFC, code, now=now + 120, last_used=None))  # too late
        self.assertEqual(totp.matching_step(self.RFC, code, now=now + 30, last_used=None), step)  # clock drift
        for junk in ("", "12345", "abcdef", "1234567"):
            self.assertIsNone(totp.matching_step(self.RFC, junk, now=now, last_used=None))


class SessionRuleTests(TestCase):
    def facts(self, **kw):
        base = dict(stage=Stage.FULL, created_at=T, last_seen_at=T, step_up_at=T, ended=False, operator_active=True)
        return SessionFacts(**(base | kw))

    def test_only_a_finished_live_session_acts(self):
        self.assertIsNone(session_refusal(self.facts(), now=T + timedelta(minutes=5)))
        for stage in (Stage.CHANGE_PASSWORD, Stage.ENROL, Stage.CODE):
            self.assertEqual(session_refusal(self.facts(stage=stage), now=T), "sign-in not finished")
        self.assertEqual(session_refusal(self.facts(ended=True), now=T), "signed out")
        self.assertEqual(session_refusal(self.facts(operator_active=False), now=T), "signed out")
        self.assertEqual(session_refusal(self.facts(), now=T + timedelta(minutes=31)), "session expired")
        busy = self.facts(last_seen_at=T + timedelta(hours=12))
        self.assertEqual(session_refusal(busy, now=T + timedelta(hours=12, minutes=1)), "session expired")

    def test_sensitive_actions_need_a_recent_code(self):
        self.assertIsNone(session_refusal(self.facts(), now=T + timedelta(minutes=9), step_up=True))
        late = self.facts(last_seen_at=T + timedelta(minutes=11))
        self.assertIsNotNone(session_refusal(late, now=T + timedelta(minutes=11), step_up=True))
        self.assertIsNotNone(session_refusal(self.facts(step_up_at=None), now=T, step_up=True))

    def test_the_fifth_failure_locks(self):
        failures, until = 0, None
        for _ in range(4):
            failures, until = signin.after_failure(failures, now=T)
            self.assertIsNone(until)
        self.assertEqual(signin.after_failure(failures, now=T), (0, T + signin.LOCK_FOR))

    def test_passwords(self):
        self.assertIsNotNone(signin.password_refusal("short", email="jane@wepl.example"))
        self.assertIsNotNone(signin.password_refusal("my-name-is-jane-ok", email="jane@wepl.example"))
        self.assertIsNone(signin.password_refusal("correct horse battery", email="jane@wepl.example"))

    def test_capabilities_fail_closed(self):
        self.assertTrue(allowed("support", OperatorCapability.INBOX))
        self.assertFalse(allowed("support", OperatorCapability.CUSTODY_LINK))
        self.assertTrue(allowed("admin", OperatorCapability.OPERATORS_MANAGE))
        self.assertFalse(allowed("superuser", OperatorCapability.INBOX))
        self.assertFalse(allowed("admin", "ledger.reverse"))

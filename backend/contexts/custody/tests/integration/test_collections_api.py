"""The bank's collections service on a group's own account (ADR-0019): the
bank's calls are signed, idempotent, scoped to the account they name, and
off unless configured."""
import json
import time

from django.test import TestCase, override_settings

from contexts.custody.api.signature import sign
from contexts.custody.public import open_alerts, reconcile
from contexts.shared_kernel.money import Money
from tests.scenario import Scenario

SECRET = "s" * 40


def local(member):
    """A member's number as they would type it: 07XXXXXXXX."""
    return "0" + member.msisdn[3:]


@override_settings(WEPL_COLLECTIONS_SECRET=SECRET)
class CollectionsApiTests(TestCase):
    def setUp(self):
        self.s = Scenario("Umoja", account="0100CHAMA001", connector="business_connect")
        self.t = Scenario("Tujenge", account="0100CHAMA002", connector="business_connect")

    def call(self, path, data, *, secret=SECRET, timestamp=None):
        body = json.dumps(data).encode()
        ts = str(int(timestamp if timestamp is not None else time.time()))
        return self.client.post(f"/collections/{path}", body, content_type="application/json",
                                headers={"X-WEPL-Timestamp": ts, "X-WEPL-Signature": sign(secret, ts, body)})

    def payment(self, n=1, amount="250.00", balance="250.00", s=None, **extra):
        s = s or self.s
        return {"account_number": s.account, "transaction_id": f"{s.account}-T{n}", "sequence": n,
                "posted_at": "2026-10-03T10:00:00+03:00", "kind": "deposit", "amount": amount,
                "reference": local(s.m[0]), "payer_name": "Payer", "payer_msisdn": "254733000000",
                "running_balance": balance, "channel": "mpesa", **extra}

    def check(self, account, reference):
        return self.call("validate", {"account_number": account, "reference": reference}).json()

    def test_the_bank_checks_a_reference_against_that_accounts_group(self):
        ok = self.check(self.s.account, local(self.s.m[0]))
        self.assertEqual((ok["accepted"], ok["name"]), (True, "Umoja"))
        self.assertTrue(self.check(self.s.account, self.s.m[1].code)["accepted"])
        for account, reference in ((self.s.account, "0799999999"), (self.s.account, "contribution"),
                                   ("0100UNKNOWN", local(self.s.m[0]))):
            with self.subTest(reference):
                self.assertFalse(self.check(account, reference)["accepted"])

    def test_a_payment_for_a_member_lands_in_their_groups_books_once(self):
        first = self.call("notify", self.payment())  # paid by someone else, for member 0
        again = self.call("notify", self.payment())
        self.assertEqual((first.status_code, again.status_code), (200, 200))
        self.assertEqual((first.json()["duplicate"], again.json()["duplicate"]), (False, True))
        self.assertEqual(self.s.balance_of(self.s.m[0]), Money("250"))
        self.assertEqual(self.t.balance_of(self.t.m[0]), Money("0"))
        with self.s.acting():
            self.assertTrue(reconcile(self.s.ea.id).balanced)

    def test_the_account_named_decides_the_group(self):
        self.call("notify", self.payment(s=self.t, amount="80.00", balance="80.00"))
        self.assertEqual(self.t.balance_of(self.t.m[0]), Money("80"))
        self.assertEqual(self.s.balance_of(self.s.m[0]), Money("0"))
        self.assertEqual(self.call("notify", self.payment(account_number="0100UNKNOWN")).status_code, 404)

    def test_a_resend_with_different_details_is_flagged(self):
        self.call("notify", self.payment())
        self.assertTrue(self.call("notify", self.payment(amount="999.00")).json()["conflict"])
        self.assertEqual(self.s.balance_of(self.s.m[0]), Money("250"))
        with self.s.acting():
            self.assertTrue(open_alerts(self.s.group.id))

    def test_unsigned_forged_or_stale_requests_are_refused(self):
        for label, response in [
            ("wrong secret", self.call("notify", self.payment(), secret="x" * 40)),
            ("stale", self.call("notify", self.payment(), timestamp=time.time() - 3600)),
            ("unsigned", self.client.post("/collections/notify", json.dumps(self.payment()),
                                          content_type="application/json")),
        ]:
            with self.subTest(label):
                self.assertEqual(response.status_code, 401)
        self.assertEqual(self.s.balance_of(self.s.m[0]), Money("0"))

    def test_a_malformed_notification_is_refused_not_guessed(self):
        for broken in ({"transaction_id": "T1"}, self.payment(amount="-5"), self.payment(posted_at="2026-10-03"),
                       self.payment(kind="gift"), self.payment(account_number=""), [1, 2]):
            with self.subTest(broken=str(broken)[:40]):
                self.assertEqual(self.call("notify", broken).status_code, 400)

    def test_only_post(self):
        self.assertEqual(self.client.get("/collections/notify").status_code, 405)

    @override_settings(WEPL_COLLECTIONS_SECRET="")
    def test_the_endpoints_are_off_until_configured(self):
        self.assertEqual(self.call("validate", {"account_number": self.s.account}).status_code, 404)

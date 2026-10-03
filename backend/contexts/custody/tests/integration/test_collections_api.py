"""The bank's calls into WEPL (ADR-0018): signed, idempotent, and off unless
configured."""
import json
import time

from django.test import TestCase, override_settings

from contexts.custody.api.signature import sign
from contexts.custody.public import collect_into, open_collection_account, open_pool_alerts, reconcile_pool
from contexts.shared_kernel.money import Money
from tests.scenario import Scenario

POOL, SECRET = "0100WEPL0002", "s" * 40


@override_settings(WEPL_COLLECTIONS_ACCOUNT=POOL, WEPL_COLLECTIONS_SECRET=SECRET)
class CollectionsApiTests(TestCase):
    def setUp(self):
        open_collection_account(institution="Custodian Bank", account_number=POOL, account_name="WEPL",
                                connector="collections_api", actor="ops")
        self.s = Scenario("Umoja", account=None)
        self.s.ea = collect_into(self.s.fund.id, account_number=POOL, actor="ops")
        self.ref = f"{self.s.group.payment_code}-{self.s.m[0].code}"

    def call(self, path, data, *, secret=SECRET, timestamp=None):
        body = json.dumps(data).encode()
        ts = str(int(timestamp if timestamp is not None else time.time()))
        return self.client.post(f"/collections/{path}", body, content_type="application/json",
                                headers={"X-WEPL-Timestamp": ts, "X-WEPL-Signature": sign(secret, ts, body)})

    def payment(self, n=1, amount="250.00", balance="250.00", **extra):
        return {"transaction_id": f"T{n}", "sequence": n, "posted_at": "2026-10-03T10:00:00+03:00",
                "kind": "deposit", "amount": amount, "reference": self.ref, "payer_name": "Member",
                "payer_msisdn": self.s.m[0].msisdn, "running_balance": balance, "channel": "mpesa", **extra}

    def test_the_bank_checks_a_reference(self):
        ok = self.call("validate", {"reference": self.ref}).json()
        self.assertEqual((ok["accepted"], ok["name"]), (True, "Umoja"))
        self.assertFalse(self.call("validate", {"reference": "ZZZZZ-M01"}).json()["accepted"])

    def test_a_notified_payment_is_booked_once(self):
        first = self.call("notify", self.payment())
        again = self.call("notify", self.payment())
        self.assertEqual((first.status_code, again.status_code), (200, 200))
        self.assertEqual((first.json()["duplicate"], again.json()["duplicate"]), (False, True))
        self.assertEqual(self.s.balance_of(self.s.m[0]), Money("250"))
        self.assertTrue(reconcile_pool(POOL).balanced)

    def test_a_resend_with_different_details_is_flagged(self):
        self.call("notify", self.payment())
        self.assertTrue(self.call("notify", self.payment(amount="999.00")).json()["conflict"])
        self.assertEqual(self.s.balance_of(self.s.m[0]), Money("250"))
        self.assertTrue(any(a["kind"] == "conflict" for a in open_pool_alerts(POOL)))

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
                       self.payment(kind="gift"), [1, 2]):
            with self.subTest(broken=str(broken)[:40]):
                self.assertEqual(self.call("notify", broken).status_code, 400)

    def test_only_post(self):
        self.assertEqual(self.client.get("/collections/notify").status_code, 405)

    @override_settings(WEPL_COLLECTIONS_SECRET="")
    def test_the_endpoints_are_off_until_configured(self):
        self.assertEqual(self.call("validate", {"reference": self.ref}).status_code, 404)

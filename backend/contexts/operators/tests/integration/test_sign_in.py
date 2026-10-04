"""Operator sign-in over HTTP (ADR-0021): provisioned accounts, staged
sessions, lockout, step-up, and capabilities that fail closed."""
import io
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, transaction
from django.test import TestCase
from django.utils import timezone

from contexts.operators.domain import totp
from contexts.operators.infrastructure.models import Operator, OperatorEvent, OperatorSession
from contexts.operators.infrastructure.secrets import unseal
from contexts.operators.public import (COOKIE, NotSignedIn, OperatorCapability, OperatorError, authenticate,
                                       create_operator, deactivate_operator)

PASSWORD = "a long enough passphrase"


def code(secret: str, ahead: int = 0) -> str:
    return totp.code_at(secret, totp.step_of(time.time()) + ahead)


class OperatorClient:
    """Drives the API the way a back-office screen would."""

    def __init__(self, testcase, client):
        self.t, self.c = testcase, client

    def post(self, path, data=None):
        return self.c.post(f"/operators/{path}", data or {}, content_type="application/json")

    def get(self, path):
        return self.c.get(f"/operators/{path}")

    def first_sign_in(self, email, one_time) -> str:
        """Password change and enrolment; returns the authenticator secret."""
        self.t.assertEqual(self.post("sign-in", {"email": email, "password": one_time}).json(),
                           {"next": "change_password"})
        self.t.assertEqual(self.post("password", {"new_password": PASSWORD}).json(), {"next": "enrol"})
        uri = self.post("authenticator/begin").json()["otpauth_uri"]
        secret = parse_qs(urlparse(uri).query)["secret"][0]
        self.t.assertEqual(self.post("authenticator/confirm", {"code": code(secret)}).status_code, 200)
        return secret


class SignInTests(TestCase):
    def setUp(self):
        self.admin, one_time = create_operator("Admin@WEPL.example", "Ada", "admin", by=None)
        self.api = OperatorClient(self, self.client)
        self.secret = self.api.first_sign_in("admin@wepl.example", one_time)

    def test_first_sign_in_changes_the_password_and_enrols_then_the_session_works(self):
        self.assertEqual(self.api.get("me").json()["email"], "admin@wepl.example")
        cookie = self.client.cookies[COOKIE]
        self.assertEqual((cookie["httponly"], cookie["secure"], cookie["samesite"], cookie["path"]),
                         (True, True, "Strict", "/operators/"))
        stored = Operator.objects.get(pk=self.admin.id)
        self.assertNotIn(PASSWORD, stored.password)
        self.assertNotIn(self.secret.encode(), bytes(stored.authenticator))
        self.assertEqual(unseal(stored.authenticator), self.secret)

    def test_a_later_sign_in_needs_the_password_and_a_code_and_a_code_works_once(self):
        self.api.post("sign-out")
        self.assertEqual(self.api.get("me").status_code, 401)
        self.assertEqual(self.api.post("sign-in", {"email": "admin@wepl.example", "password": PASSWORD}).json(),
                         {"next": "code"})
        self.assertEqual(self.api.get("me").status_code, 401)  # half signed in reaches nothing
        self.assertEqual(self.api.get("inbox").status_code, 401)
        used = code(self.secret, ahead=1)
        self.assertEqual(self.api.post("code", {"code": used}).status_code, 200)
        self.assertEqual(self.api.post("step-up", {"code": used}).status_code, 401)  # replayed

    def test_every_partial_stage_is_refused_beyond_its_own_step(self):
        _, one_time = create_operator("new@wepl.example", "New", "support", by=authenticate_admin(self))
        other = OperatorClient(self, self.client_class())
        other.post("sign-in", {"email": "new@wepl.example", "password": one_time})
        for path in ("me", "inbox"):
            self.assertEqual(other.get(path).status_code, 401)
        for path in ("authenticator/begin", "code", "step-up"):
            self.assertEqual(other.post(path, {"code": "000000"}).status_code, 401, path)

    def test_wrong_answers_all_look_alike_and_five_lock_the_account(self):
        unknown = self.api.post("sign-in", {"email": "nobody@wepl.example", "password": PASSWORD})
        wrong = self.api.post("sign-in", {"email": "admin@wepl.example", "password": "not it at all"})
        self.assertEqual((unknown.status_code, unknown.json()), (wrong.status_code, wrong.json()))
        for _ in range(4):
            self.api.post("sign-in", {"email": "admin@wepl.example", "password": "not it at all"})
        self.assertEqual(self.api.get("me").status_code, 401)  # locking ended the open session
        locked = self.api.post("sign-in", {"email": "admin@wepl.example", "password": PASSWORD})
        self.assertEqual((locked.status_code, locked.json()), (wrong.status_code, wrong.json()))
        self.assertTrue(OperatorEvent.objects.filter(operator_id=self.admin.id, action="operator.locked").exists())

    def test_idle_and_old_sessions_expire(self):
        session = OperatorSession.objects.get(operator_id=self.admin.id, ended_at__isnull=True)
        OperatorSession.objects.filter(pk=session.pk).update(last_seen_at=timezone.now() - timedelta(minutes=31))
        self.assertEqual(self.api.get("me").status_code, 401)

    def test_the_inbox_needs_a_recent_code(self):
        self.assertEqual(self.api.get("inbox").json(), {"items": []})
        OperatorSession.objects.filter(operator_id=self.admin.id).update(
            step_up_at=timezone.now() - timedelta(minutes=11))
        self.assertEqual(self.api.get("inbox").status_code, 401)
        self.assertEqual(self.api.post("step-up", {"code": code(self.secret, ahead=1)}).status_code, 200)
        self.assertEqual(self.api.get("inbox").status_code, 200)

    def test_requests_must_be_json(self):
        form = self.client.post("/operators/sign-out", {"x": "1"})
        self.assertEqual(form.status_code, 400)
        self.assertEqual(self.api.get("me").status_code, 200)  # the form did nothing

    def test_deactivating_ends_every_session(self):
        by = authenticate_admin(self)
        second, _ = create_operator("two@wepl.example", "Two", "admin", by=by)
        with self.assertRaisesMessage(OperatorError, "Another admin"):
            deactivate_operator(self.admin.id, by=by)
        deactivate_operator(self.admin.id, by=second)
        self.assertEqual(self.api.get("me").status_code, 401)
        self.assertEqual(self.api.post("sign-in", {"email": "admin@wepl.example", "password": PASSWORD}).status_code,
                         401)


def authenticate_admin(testcase):
    return authenticate(testcase.client.cookies[COOKIE].value, OperatorCapability.OPERATORS_MANAGE)


class ProvisioningTests(TestCase):
    def test_only_the_very_first_operator_is_created_without_an_admin_and_it_is_an_admin(self):
        with self.assertRaisesMessage(OperatorError, "must be an admin"):
            create_operator("a@wepl.example", "A", "support", by=None)
        admin, _ = create_operator("a@wepl.example", "A", "admin", by=None)
        with self.assertRaisesMessage(OperatorError, "already exist"):
            create_operator("b@wepl.example", "B", "admin", by=None)
        support, _ = create_operator("b@wepl.example", "B", "support", by=admin)
        with self.assertRaisesMessage(OperatorError, "Not authorised"):
            create_operator("c@wepl.example", "C", "support", by=support)
        with self.assertRaisesMessage(OperatorError, "already exists"):
            create_operator("B@wepl.example", "B", "support", by=admin)

    def test_the_sign_in_log_and_operators_are_kept(self):
        admin, _ = create_operator("a@wepl.example", "A", "admin", by=None)
        for write in (lambda: OperatorEvent.objects.update(action="x"), lambda: OperatorEvent.objects.all().delete(),
                      lambda: Operator.objects.filter(pk=admin.id).delete()):
            with self.assertRaises(DatabaseError), transaction.atomic():
                write()

    def test_a_support_operator_cannot_reach_what_their_role_lacks(self):
        admin, _ = create_operator("a@wepl.example", "A", "admin", by=None)
        _, one_time = create_operator("s@wepl.example", "S", "support", by=admin)
        OperatorClient(self, self.client).first_sign_in("s@wepl.example", one_time)
        token = self.client.cookies[COOKIE].value
        self.assertEqual(authenticate(token, OperatorCapability.INBOX).email, "s@wepl.example")
        with self.assertRaises(NotSignedIn):
            authenticate(token, OperatorCapability.CUSTODY_LINK)


class ConsoleTests(TestCase):
    def test_server_commands_name_a_real_operator_with_a_current_code(self):
        _, one_time = create_operator("a@wepl.example", "A", "admin", by=None)
        secret = OperatorClient(self, self.client).first_sign_in("a@wepl.example", one_time)
        with self.assertRaises(CommandError):
            call_command("operator_inbox", operator="a@wepl.example", code="000000", stdout=io.StringIO())
        out = io.StringIO()
        call_command("operator_inbox", operator="a@wepl.example", code=code(secret, ahead=1), stdout=out)
        self.assertIn("Nothing is open", out.getvalue())
        self.assertTrue(OperatorEvent.objects.filter(action="operator.code_failed").exists())

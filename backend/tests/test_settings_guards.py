"""Unsafe configurations refuse to boot. Each case starts a fresh interpreter,
because settings are read once per process."""
import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

BACKEND = Path(__file__).resolve().parent.parent
BOOT = "import django; django.setup()"


def boot(**env):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "WEPL_"))}
    base["DJANGO_SETTINGS_MODULE"] = "config.settings"
    return subprocess.run([sys.executable, "-c", BOOT], cwd=BACKEND, env=base | env, capture_output=True, text=True)


class BootGuardTests(TestCase):
    def test_production_needs_a_real_secret(self):
        result = boot(DJANGO_DEBUG="0", WEPL_ENABLE_SIMULATOR="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY must be set", result.stderr)

    def test_production_refuses_the_simulated_bank(self):
        for simulator in ({}, {"WEPL_ENABLE_SIMULATOR": "1"}):  # on by default, so unset is refused too
            with self.subTest(simulator):
                result = boot(DJANGO_DEBUG="0", DJANGO_SECRET_KEY="a-real-secret", **simulator)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("WEPL_ENABLE_SIMULATOR must be 0", result.stderr)

    def test_production_needs_its_own_operator_key(self):
        result = boot(DJANGO_DEBUG="0", DJANGO_SECRET_KEY="a-real-secret", WEPL_ENABLE_SIMULATOR="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WEPL_OPERATOR_KEY must be set", result.stderr)

    def test_a_correct_production_configuration_boots(self):
        result = boot(DJANGO_DEBUG="0", DJANGO_SECRET_KEY="a-real-secret", WEPL_ENABLE_SIMULATOR="0",
                      WEPL_OPERATOR_KEY="kTn6hqEYgtqMm1D0bc7k2bXbK1o3e9mLqvH4CUtdUfI=")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_refuses_a_digest_that_would_never_be_sent(self):
        result = boot(DJANGO_DEBUG="0", DJANGO_SECRET_KEY="a-real-secret", WEPL_ENABLE_SIMULATOR="0",
                      WEPL_OPERATIONS_EMAIL="ops@example.org")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EMAIL_BACKEND would not send it", result.stderr)

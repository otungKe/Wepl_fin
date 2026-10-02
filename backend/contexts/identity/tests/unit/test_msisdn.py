from django.test import SimpleTestCase

from contexts.identity.contract import InvalidMsisdn, Msisdn


class MsisdnTests(SimpleTestCase):
    def test_normalises_local_and_international_forms(self):
        for raw in ("0712345678", "712345678", "+254 712 345 678", "254712345678"):
            self.assertEqual(Msisdn.parse(raw).value, "254712345678")
        self.assertEqual(Msisdn.parse("0110123456").value, "254110123456")

    def test_rejects_non_kenyan_or_short_numbers(self):
        for raw in ("", "12345", "0812345678", "+1 415 555 0100"):
            with self.assertRaises(InvalidMsisdn):
                Msisdn.parse(raw)
            self.assertIsNone(Msisdn.try_parse(raw))

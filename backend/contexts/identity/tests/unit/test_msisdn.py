from django.test import SimpleTestCase

from contexts.identity.contract import InvalidMsisdn, Msisdn


class MsisdnTests(SimpleTestCase):
    def test_normalises_local_and_international_forms(self):
        for raw in ("0712345678", "712345678", "+254 712 345 678", "254712345678", "254-712-345-678",
                    "00254712345678", "+254 (0)712 345 678", "0712.345.678"):
            with self.subTest(raw):
                self.assertEqual(Msisdn.parse(raw).value, "254712345678")
        self.assertEqual(Msisdn.parse("0110123456").value, "254110123456")

    def test_rejects_non_kenyan_or_short_numbers(self):
        for raw in ("", "12345", "0812345678", "+1 415 555 0100", "07123456789", "00712345678"):
            with self.subTest(raw):
                with self.assertRaises(InvalidMsisdn):
                    Msisdn.parse(raw)
                self.assertIsNone(Msisdn.try_parse(raw))

    def test_rejects_text_that_merely_contains_a_number(self):
        for raw in ("call 0712345678", "0712345678x", "0712345678/9", "#0712345678", "０７１２３４５６７８"):
            with self.subTest(raw), self.assertRaises(InvalidMsisdn):
                Msisdn.parse(raw)

    def test_checks_shape_and_prefix_not_operator_allocation(self):
        """Deliberate: operators' ranges change, so any 07 or 01 number is a
        Kenyan mobile number here, assigned yet or not."""
        self.assertEqual(Msisdn.parse("0199999999").value, "254199999999")

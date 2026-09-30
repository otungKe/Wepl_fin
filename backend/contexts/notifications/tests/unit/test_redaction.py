from unittest import TestCase

from contexts.notifications.domain.redaction import for_log


class RedactionTests(TestCase):
    def test_phone_numbers_and_names_never_reach_the_log(self):
        logged = for_log({"msisdn": "254712000004", "payer": "JOHN OUMA", "counterparty": "CASH", "amount": "700",
                          "line_id": 9})
        self.assertEqual(logged, {"msisdn": "***004", "payer": "[redacted]", "counterparty": "[redacted]",
                                  "amount": "700", "line_id": 9})
        self.assertEqual(for_log({"msisdn": None})["msisdn"], "***")

# Scheduling the nightly run (ADR-0020)

ASSUMPTION: the pilot host is not yet chosen. These are cron lines for a
Linux host. A systemd timer works the same way.

```cron
# Every night at 02:00 Nairobi time: sync and reconcile, check the books,
# deliver messages, email the digest.
0 2 * * *  cd /srv/wepl/backend && python manage.py nightly >> /var/log/wepl/nightly.log 2>&1

# Messages should not wait for the night.
*/5 * * * *  cd /srv/wepl/backend && python manage.py deliver_outbox >> /var/log/wepl/outbox.log 2>&1
```

## Environment

| Variable | Meaning |
|---|---|
| `WEPL_OPERATIONS_EMAIL` | Where the digest goes. Unset: the digest is only logged. |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | Django's mail settings. Production refuses to start if the backend would not send. |
| `DEFAULT_FROM_EMAIL` | The digest's sender. |

## Each morning

1. Read the digest. **No digest means the jobs did not run**: check the log.
2. If it says URGENT, open the operator inbox: `GET /operators/inbox` when signed in, or on the server `python manage.py operator_inbox --operator <your email> --code <authenticator code>` (ADR-0021).
   Then phone the officials of each group listed (decision of 2026-09-28,
   while SMS is on hold).
3. A failed job is named in the subject. Run it by hand to see the error,
   e.g. `python manage.py check_ledger_integrity`.

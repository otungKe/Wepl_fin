# Build plan

Each step ends with a check-in with Harry before the next one starts.

1. **Stack** — ADR-0001.
2. **System design** — the modules, what each owns, how they talk, the
   ledger's accounts and the money recipes, the data model.
3. **Initialise the project** — repo layout, settings, CI, a first deploy.
4. **Kernel and ledger** — money type, outbox, `post_journal`, the database
   triggers, trial balance.
5. **Payment rail** — payment intents, the fake provider, Daraja STK, B2C and
   paybill callbacks.
6. **People and groups** — phone login, groups, members and roles.
7. **Contributions** — cycles set by the group (recurring or one-off), paying
   in, who has paid, reminders.
8. **Payouts** — requests, two approvals, payout by B2C.
9. **Statements** — per contribution and per member, from the ledger.
10. **Demo** — seeded group, SMS inbox, presenter script.

Out of scope for the MVP: rotating payouts (ROSCA), standing orders, standing
welfare funds (a collection for a member is a one-off contribution), shares
as investment, advances, chat and feeds.

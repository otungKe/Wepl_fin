# ADR-0003 acceptance checklist: evidence

- **Date:** 2026-10-02.
- **Checklist:** Harry's (project chat, 2026-10-02).
- **Code tested:** main at `b1927c2`, plus the tests added on this branch.
- **How the tests ran:**
  - PostgreSQL 16;
  - as the application role `wepl_app`: not a superuser, no BYPASSRLS
    (asserted in the tests);
  - `manage.py test`: 267 tests, all pass.
- **New tests** are marked *new*. They are in `tests/test_ledger_acceptance.py`
  and `tests/test_ledger_committed.py`.

Harry accepted ADR-0003 on 2026-10-03 on this evidence.

| # | Item | Result | Proven by |
|---|---|---|---|
| 1 | **Balanced posting.** Valid multi-line journals commit; unbalanced journals fail; cross-currency balancing fails. | PASS | *new* `test_a_balanced_journal_of_many_lines_commits` (4 lines, 3 credit accounts). `test_unbalanced_entry_is_refused_at_commit` (database). `test_unbalanced_single_line_zero_and_negative_entries_are_refused` (domain). *new* `test_currencies_never_balance_each_other` (KES debit against USD credit, refused by the domain and by the database). |
| 2 | **Empty and malformed entries.** Zero or one line, invalid accounts, and wrong fund or tenant references cannot commit. | PASS | `test_entry_without_lines_is_refused_at_commit`. *new* `test_an_entry_with_one_line_cannot_commit`. *new* `test_a_line_naming_no_real_account_cannot_commit`. `test_p3_…normal_side…`, `test_purpose_and_currency_are_known_values`. `test_non_positive_amounts_are_refused`. `test_p7_…group_and_fund` (fund). `test_p2_…`, `test_p5_…`, `test_p6_…` (tenant). |
| 3 | **Immutable history.** UPDATE, DELETE and TRUNCATE are rejected under the real application role. | PASS | `test_history_is_append_only`. *new* `test_history_refuses_update_and_delete_as_the_application_role`: raw SQL on all three tables, with the role asserted. *new* `test_truncate_is_refused_as_the_application_role`: committed first, because PostgreSQL will not truncate a table with pending deferred checks. |
| 4 | **Idempotency under concurrency.** Simultaneous identical requests create one journal; conflicting reuse is rejected. | PASS | `test_racing_posts_with_one_key_post_once_and_all_get_its_id`, `test_racing_posts_with_one_key_and_different_content_are_refused` (8 real connections each). `test_same_key_different_entry_is_refused`. |
| 5 | **Reversal chain.** Original → reversal → reversal of reversal works; two direct reversals of one entry cannot both succeed. | PASS | `test_a_reversal_is_itself_reversible_once`. `test_racing_reversals_of_one_entry_post_exactly_one` (8 connections). `test_a_second_reversal_racing_the_first_is_reported_as_such`. `test_p8_a_reversal_must_mirror_its_original`. |
| 6 | **Account creation races.** Concurrent first use creates one account per key. | PASS | `test_racing_first_use_of_an_account_creates_it_once` (8 connections). `test_one_account_per_key_even_with_null_parts`. |
| 7 | **Balance and reconciliation.** Derived balances match independently calculated totals, and external discrepancies are detectable. | PASS | *new* `test_derived_balances_equal_totals_computed_independently_in_sql` (hand-written SQL against the query layer, after posts, a payout and a reversal). *new* `test_books_that_disagree_with_the_custodian_are_detected` (an unbacked 50 gives an unbalanced run, a difference of 50, and an alert). `test_missing_lines_are_detected_then_healed_by_the_sweep`. Property test `test_any_history_reconciles`. |
| 8 | **Tenant and fund isolation.** Direct SQL and application operations cannot create cross-tenant or cross-fund journal references. | PASS | *new* `test_direct_sql_cannot_join_lines_across_funds`. *new* `test_direct_sql_cannot_join_lines_across_tenants` (raw SQL inside a cross-tenant operation, where every row is visible). `test_a_ledger_row_cannot_name_another_tenants_fund_member_or_account` (ADR-0017). `test_another_tenants_entry_cannot_be_reversed_or_read`. |

## Limits of this evidence

- **Real I&M statement.** Reconciliation (item 7) is proven against the I&M
  simulator, not a real I&M statement. That is still waiting on the sample.
- **Concurrency scale.** The concurrency tests (items 4–6) use 8 connections
  on one machine. They show the database decides each race. They are not a
  load test.

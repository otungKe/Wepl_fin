"""Commands: post a journal entry, reverse one."""
from django.db import IntegrityError, transaction

from contexts.audit.public import current_operation_id
from contexts.shared_kernel.money import Money

from ..domain.accounts import AccountKey, AccountPurpose, Side
from ..domain.journal import JournalDraft, LedgerError, Posting
from ..infrastructure import accounts
from ..infrastructure.models import JournalEntry, JournalLine


def post_journal(draft: JournalDraft) -> int:
    """Post a valid entry and return its id. Posting the same idempotency key
    again returns the first entry, so a retry or a duplicate notification can
    never double-post; reusing a key for a *different* entry is refused."""
    existing = JournalEntry.objects.filter(idempotency_key=draft.idempotency_key).first()
    if existing:
        return _replay(existing, draft)
    try:
        with transaction.atomic():  # entry and lines are one fact; balance is re-checked at commit
            entry = JournalEntry.objects.create(
                idempotency_key=draft.idempotency_key, fingerprint=draft.fingerprint(), group_id=draft.group_id,
                fund_id=draft.fund_id, kind=draft.kind, memo=draft.memo[:255], cause_type=draft.cause_type,
                cause_id=draft.cause_id, reverses_id=draft.reverses_entry_id, operation_id=current_operation_id())
            JournalLine.objects.bulk_create(
                JournalLine(entry=entry, account=accounts.resolve(p.account), side=p.side.value,
                            amount=p.amount.amount) for p in draft.postings)
    except IntegrityError:
        existing = JournalEntry.objects.filter(idempotency_key=draft.idempotency_key).first()
        if existing is None:
            if draft.reverses_entry_id and JournalEntry.objects.filter(reverses_id=draft.reverses_entry_id).exists():
                raise LedgerError(f"Entry {draft.reverses_entry_id} has already been reversed.") from None
            raise
        return _replay(existing, draft)  # lost a race on the same key
    return entry.pk


def _replay(existing: JournalEntry, draft: JournalDraft) -> int:
    if existing.fingerprint != draft.fingerprint():
        raise LedgerError(f"Idempotency key {draft.idempotency_key!r} was already used for a different entry.")
    return existing.pk


def load_draft(entry_id: int) -> JournalDraft:
    entry = JournalEntry.objects.get(pk=entry_id)
    postings = []
    for line in entry.lines.select_related("account"):
        a = line.account
        key = AccountKey(group_id=a.group_id, fund_id=a.fund_id, purpose=AccountPurpose(a.purpose),
                         member_id=a.member_id, external_account_id=a.external_account_id, currency=a.currency)
        postings.append(Posting(key, Side(line.side), Money(line.amount, a.currency)))
    return JournalDraft(idempotency_key=entry.idempotency_key, group_id=entry.group_id, fund_id=entry.fund_id,
                        kind=entry.kind, cause_type=entry.cause_type, cause_id=entry.cause_id,
                        postings=tuple(postings), memo=entry.memo)


def reverse_journal(entry_id: int, *, idempotency_key: str, memo: str = "") -> int:
    """Post the mirror image of an entry. The original is never touched."""
    if JournalEntry.objects.filter(reverses_id=entry_id).exclude(idempotency_key=idempotency_key).exists():
        raise LedgerError(f"Entry {entry_id} has already been reversed.")
    return post_journal(load_draft(entry_id).reversal(entry_id=entry_id, idempotency_key=idempotency_key, memo=memo))

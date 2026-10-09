"""Commands: post a journal entry, reverse one."""
from django.db import IntegrityError, transaction

from contexts.audit.public import current_operation_id
from contexts.shared_kernel.money import Money

from ..domain.accounts import AccountKey, AccountPurpose, Side
from ..domain.journal import JournalDraft, LedgerError, Posting
from ..domain.transfer import TRANSFER_KINDS, FundTransfer
from ..infrastructure import accounts
from ..infrastructure.models import JournalEntry, JournalLine

KEY_UNIQUE = "ledger_entry_key_unique"
REVERSED_ONCE = "ledger_journalentry_reverses_id_key"
TRANSFER_LEG_ONCE = "ledger_transfer_leg_once"


def post_journal(draft: JournalDraft) -> int:
    """Post a valid entry and return its id. Posting the same idempotency key
    again returns the first entry, so a retry or a duplicate notification can
    never double-post; reusing a key for a *different* entry is refused."""
    if draft.kind in TRANSFER_KINDS:
        raise LedgerError("A fund transfer's entries are posted together, with post_transfer.")
    return _post(draft)


@transaction.atomic  # both entries or neither; PostgreSQL checks the pair at commit (ledger 0009)
def post_transfer(transfer: FundTransfer) -> tuple[int, int]:
    """Post a move between two funds of one group (ADR-0024): the source
    fund's entry and the destination's, together. Idempotent like
    ``post_journal``: a retry returns the same two entries."""
    return _post(transfer.out), _post(transfer.into)


def _post(draft: JournalDraft) -> int:
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
    except IntegrityError as exc:
        # Only the races the database settles are translated; any other
        # failure (a trigger, a foreign key, a check) is a real error.
        violated = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None)
        if violated not in (KEY_UNIQUE, REVERSED_ONCE, TRANSFER_LEG_ONCE):
            raise
        # Lost a race. If the winner used this key, this is its retry, whichever
        # unique index PostgreSQL happened to check first.
        winner = JournalEntry.objects.filter(idempotency_key=draft.idempotency_key).first()
        if winner:
            return _replay(winner, draft)
        if violated == REVERSED_ONCE:
            raise LedgerError(f"Entry {draft.reverses_entry_id} has already been reversed.") from None
        if violated == TRANSFER_LEG_ONCE:
            raise LedgerError(f"Fund transfer {draft.cause_type}:{draft.cause_id} has already been posted "
                              "under another key.") from None
        raise
    return entry.pk


def _replay(existing: JournalEntry, draft: JournalDraft) -> int:
    if existing.fingerprint != draft.fingerprint():
        raise LedgerError(f"Idempotency key {draft.idempotency_key!r} was already used for a different entry.")
    return existing.pk


def load_draft(entry_id: int) -> JournalDraft:
    """The posted entry as a draft, including what it reverses."""
    entry = JournalEntry.objects.filter(pk=entry_id).first()
    if entry is None:  # unknown, or another tenant's (row-level security hides it)
        raise LedgerError(f"Unknown journal entry {entry_id}.")
    postings = []
    for line in entry.lines.select_related("account").order_by("id"):
        a = line.account
        key = AccountKey(group_id=a.group_id, fund_id=a.fund_id, purpose=AccountPurpose(a.purpose),
                         member_id=a.member_id, external_account_id=a.external_account_id, currency=a.currency)
        postings.append(Posting(key, Side(line.side), Money(line.amount, a.currency)))
    return JournalDraft(idempotency_key=entry.idempotency_key, group_id=entry.group_id, fund_id=entry.fund_id,
                        kind=entry.kind, cause_type=entry.cause_type, cause_id=entry.cause_id,
                        postings=tuple(postings), memo=entry.memo, reverses_entry_id=entry.reverses_id)


def reverse_journal(entry_id: int, *, idempotency_key: str, memo: str = "") -> int:
    """Post the mirror image of an entry. The original is never touched.
    A fund transfer's entries are never reversed: the group moves the money
    back with a new transfer (ADR-0024)."""
    if JournalEntry.objects.filter(reverses_id=entry_id).exclude(idempotency_key=idempotency_key).exists():
        raise LedgerError(f"Entry {entry_id} has already been reversed.")
    original = load_draft(entry_id)
    if original.kind in TRANSFER_KINDS:
        raise LedgerError(f"Entry {entry_id} is half of a fund transfer; move the money back with a new transfer.")
    return post_journal(original.reversal(entry_id=entry_id, idempotency_key=idempotency_key, memo=memo))

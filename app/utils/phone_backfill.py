"""Plans the one-off normalisation of existing users' phone numbers to E.164.

Pure (no database access) so the migration, the dry-run CLI and the tests share
exactly the same decisions. The migration imports this module, so changes here
must stay backward compatible with already-applied plans.

Rules:
* Candidate number per user, in order: ``phone_number``, ``identifier``
  (``phone_<digits>``), then a phone-like ``username``.
* A number claimed by exactly one user's ``phone_number`` column goes to that
  user; other claimants are reported as duplicates.
* If several ``phone_number`` values normalise to the same number, or only
  fallback sources claim it and more than one user does, nobody gets it and
  every claimant is reported as ambiguous. Phone verification resolves it later.
* Invalid ``phone_number`` values are cleared from the column but preserved in
  the report. Nothing is deleted.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from app.utils.phone import try_to_e164

PRIMARY_SOURCE = 'phone_number'
_PHONE_LIKE_USERNAME = re.compile(r'^\+?\d{9,15}$')


@dataclass(frozen=True)
class UserPhoneRecord:
    user_id: int
    phone_number: Optional[str]
    identifier: Optional[str]
    username: Optional[str]


@dataclass(frozen=True)
class PhoneIssue:
    user_id: int
    issue_type: str
    source: str
    raw_value: str
    normalized_value: Optional[str] = None
    conflicting_user_id: Optional[int] = None


@dataclass
class PhoneBackfillPlan:
    # user_id -> new phone_number (None clears it); only users whose value changes.
    changes: Dict[int, Optional[str]] = field(default_factory=dict)
    issues: List[PhoneIssue] = field(default_factory=list)

    def summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for issue in self.issues:
            counts[issue.issue_type] += 1
        counts['changed'] = len(self.changes)
        return dict(counts)


@dataclass(frozen=True)
class _Claim:
    user_id: int
    source: str
    raw_value: str


def _candidates(record: UserPhoneRecord):
    if record.phone_number and record.phone_number.strip():
        yield PRIMARY_SOURCE, record.phone_number.strip()
    identifier = (record.identifier or '').strip()
    if identifier.startswith('phone_') and len(identifier) > len('phone_'):
        yield 'identifier', identifier[len('phone_'):]
    username = (record.username or '').strip()
    if _PHONE_LIKE_USERNAME.match(username):
        yield 'username', username


def plan_phone_backfill(records: Iterable[UserPhoneRecord]) -> PhoneBackfillPlan:
    plan = PhoneBackfillPlan()
    records = list(records)
    claims_by_number: Dict[str, List[_Claim]] = defaultdict(list)

    for record in records:
        for source, raw in _candidates(record):
            normalized = try_to_e164(raw)
            if normalized:
                claims_by_number[normalized].append(_Claim(record.user_id, source, raw))
                break
            if source == PRIMARY_SOURCE:
                plan.issues.append(PhoneIssue(record.user_id, 'INVALID_PHONE', source, raw))

    assigned: Dict[int, str] = {}
    for number, claims in claims_by_number.items():
        primary = [claim for claim in claims if claim.source == PRIMARY_SOURCE]
        if len(primary) == 1:
            winner = primary[0]
        elif not primary and len(claims) == 1:
            winner = claims[0]
        else:
            for claim in claims:
                plan.issues.append(PhoneIssue(claim.user_id, 'AMBIGUOUS_PHONE', claim.source, claim.raw_value, number))
            continue

        assigned[winner.user_id] = number
        for claim in claims:
            if claim.user_id != winner.user_id:
                plan.issues.append(PhoneIssue(
                    claim.user_id, 'DUPLICATE_PHONE', claim.source, claim.raw_value, number, winner.user_id,
                ))

    for record in records:
        new_value = assigned.get(record.user_id)
        if new_value != (record.phone_number or None):
            plan.changes[record.user_id] = new_value
    return plan

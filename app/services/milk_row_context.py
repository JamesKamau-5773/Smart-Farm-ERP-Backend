"""Facts a milk-record row needs from other rows: people's names and the cow's recent average.

Worked out for a whole page at once, in a fixed number of queries, so lists don't query per row.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import timedelta
from decimal import Decimal

from app import db
from app.models.hr import Employee
from app.models.supply import MilkLog
from app.models.user import User
from app.services.production_service import ProductionService
from app.utils.user_display import name_for_user


def milk_row_context(logs) -> dict[int, dict]:
    """``{log.id: {milker_id, milker_name, recorded_by_name, avg_litres, vs_avg_litres}}``.

    * ``milker_name``: the employee recorded as the milker, else the person who entered it.
    * ``avg_litres`` / ``vs_avg_litres``: the cow's average for the same session over the
      ``ProductionService.ANOMALY_WINDOW_DAYS`` before this record, the same baseline the
      milk-drop rule uses, and this record's litres minus it. Null when the cow has no record of
      that session in the window.
    """
    logs = [log for log in logs if log is not None]
    if not logs:
        return {}

    user_ids = {log.recorded_by for log in logs if log.recorded_by}
    users = {user.id: user for user in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    employee_ids = {log.milker_employee_id for log in logs if log.milker_employee_id}
    employees = (
        {emp.id: emp for emp in Employee.query.filter(Employee.id.in_(employee_ids)).all()}
        if employee_ids else {}
    )
    averages = _window_averages(logs)

    context = {}
    for log in logs:
        recorded_by_name = name_for_user(users.get(log.recorded_by))
        employee = employees.get(log.milker_employee_id)
        # A milker from another tenant would be a data error; never show their name.
        if employee is not None and employee.tenant_id != log.tenant_id:
            employee = None
        average = averages.get(log.id)
        context[log.id] = {
            'milker_id': employee.id if employee else None,
            'milker_name': employee.full_name if employee else recorded_by_name,
            'recorded_by_name': recorded_by_name,
            'avg_litres': round(float(average), 1) if average is not None else None,
            'vs_avg_litres': (
                round(float(Decimal(str(log.amount_liters)) - average), 1) if average is not None else None
            ),
        }
    return context


def _window_averages(logs) -> dict[int, Decimal]:
    """Each log's average for its cow and session over the window before its timestamp, as the
    drop rule computes it (``MilkRepository.get_cow_average_yield``: ``start <= timestamp < this
    record``, same session)."""
    window = timedelta(days=ProductionService.ANOMALY_WINDOW_DAYS)
    timed = [log for log in logs if log.timestamp is not None]
    if not timed:
        return {}

    rows = (
        db.session.query(MilkLog.cow_id, MilkLog.session, MilkLog.timestamp, MilkLog.amount_liters)
        .filter(
            MilkLog.tenant_id.in_({log.tenant_id for log in timed}),
            MilkLog.cow_id.in_({log.cow_id for log in timed}),
            MilkLog.timestamp >= min(log.timestamp for log in timed) - window,
            MilkLog.timestamp < max(log.timestamp for log in timed),
        )
        .order_by(MilkLog.cow_id, MilkLog.timestamp)
        .all()
    )
    # Per cow and session: timestamps in order, and running totals so each window sums in O(log n).
    history: dict[tuple, tuple[list, list]] = {}
    for cow_id, session, timestamp, amount in rows:
        times, totals = history.setdefault((cow_id, _session_key(session)), ([], [Decimal('0')]))
        times.append(timestamp)
        totals.append(totals[-1] + Decimal(str(amount)))

    averages = {}
    for log in timed:
        times, totals = history.get((log.cow_id, _session_key(log.session)), ([], [Decimal('0')]))
        start = bisect_left(times, log.timestamp - window)
        end = bisect_left(times, log.timestamp)
        if end > start:
            averages[log.id] = (totals[end] - totals[start]) / (end - start)
    return averages


def _session_key(session) -> str:
    # Matches the rule's case- and space-insensitive session comparison.
    return str(session or '').strip().lower()

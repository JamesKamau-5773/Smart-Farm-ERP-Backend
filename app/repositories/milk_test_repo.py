from __future__ import annotations

from app import db
from app.models.livestock import MilkTest


class MilkTestRepository:
    @staticmethod
    def stage(test: MilkTest) -> MilkTest:
        db.session.add(test)
        return test

    @staticmethod
    def latest_for_cow(cow_id: int, tenant_id: int) -> MilkTest | None:
        return (
            MilkTest.query.filter_by(cow_id=cow_id, tenant_id=tenant_id)
            .order_by(MilkTest.tested_at.desc(), MilkTest.id.desc())
            .first()
        )

    @staticmethod
    def list_for_cow(cow_id: int, tenant_id: int) -> list[MilkTest]:
        return (
            MilkTest.query.filter_by(cow_id=cow_id, tenant_id=tenant_id)
            .order_by(MilkTest.tested_at.desc(), MilkTest.id.desc())
            .all()
        )

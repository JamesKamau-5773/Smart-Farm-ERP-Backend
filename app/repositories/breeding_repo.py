from datetime import date

from sqlalchemy import func, case
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models.livestock import BreedingLog, Cow, SemenInventory
from app.models.supply import MilkLog


class SemenInventoryRepository:
    @staticmethod
    def create(*, tenant_id: int, bull_name: str, straw_code: str, breed: str, provider: str = None, cost=None, stock_level: int = 0, traits_to_improve=None) -> SemenInventory:
        try:
            item = SemenInventory(
                tenant_id=tenant_id,
                bull_name=bull_name,
                straw_code=straw_code,
                breed=breed,
                provider=provider,
                cost=cost,
                stock_level=stock_level,
                traits_to_improve=traits_to_improve,
            )
            db.session.add(item)
            db.session.commit()
            return item
        except SQLAlchemyError:
            db.session.rollback()
            raise Exception("Failed, Database error while saving semen inventory.")

    @staticmethod
    def list_by_tenant(tenant_id: int) -> list:
        return SemenInventory.query.filter_by(tenant_id=tenant_id).order_by(SemenInventory.id.desc()).all()

    @staticmethod
    def get_by_id_for_tenant(semen_id: int, tenant_id: int) -> SemenInventory:
        return SemenInventory.query.filter_by(id=semen_id, tenant_id=tenant_id).first()

    @staticmethod
    def get_by_straw_code_for_tenant(straw_code: str, tenant_id: int) -> SemenInventory:
        return SemenInventory.query.filter_by(straw_code=straw_code, tenant_id=tenant_id).first()

    @staticmethod
    def get_by_bull_name_for_tenant(bull_name: str, tenant_id: int) -> SemenInventory:
        cleaned_name = (bull_name or "").strip()
        if not cleaned_name:
            return None
        return (
            SemenInventory.query
            .filter(SemenInventory.tenant_id == tenant_id)
            .filter(func.lower(SemenInventory.bull_name) == cleaned_name.lower())
            .first()
        )

    @staticmethod
    def save() -> None:
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise Exception("Failed, Database error while updating semen inventory.")


class BreedingLogRepository:
    @staticmethod
    def create(
        *,
        tenant_id: int,
        cow_id: int,
        inventory_semen_id: int | None,
        external_sire_code: str | None,
        provided_by: str,
        insemination_date: date,
        expected_calving_date=None,
        status: str = "Pending",
    ) -> BreedingLog:
        try:
            log = BreedingLog(
                tenant_id=tenant_id,
                cow_id=cow_id,
                inventory_semen_id=inventory_semen_id,
                external_sire_code=external_sire_code,
                provided_by=provided_by,
                insemination_date=insemination_date,
                expected_calving_date=expected_calving_date,
                status=status,
            )
            db.session.add(log)
            db.session.commit()
            return log
        except SQLAlchemyError:
            db.session.rollback()
            raise Exception("Failed, Database error while saving breeding log.")

    @staticmethod
    def get_by_id_for_tenant(log_id: int, tenant_id: int) -> BreedingLog:
        return BreedingLog.query.filter_by(id=log_id, tenant_id=tenant_id).first()

    @staticmethod
    def save() -> None:
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise Exception("Failed, Database error while updating breeding log.")


class BreedingAnalyticsRepository:
    @staticmethod
    def bull_conception_summary(tenant_id: int) -> list:
        rows = (
            db.session.query(
                SemenInventory.id.label("semen_id"),
                SemenInventory.bull_name,
                SemenInventory.straw_code,
                func.count(BreedingLog.id).label("total_services"),
                func.sum(case((BreedingLog.status == "Pregnant", 1), else_=0)).label("pregnant_cases"),
            )
            .join(BreedingLog, BreedingLog.inventory_semen_id == SemenInventory.id)
            .filter(SemenInventory.tenant_id == tenant_id, BreedingLog.tenant_id == tenant_id)
            .group_by(SemenInventory.id, SemenInventory.bull_name, SemenInventory.straw_code)
            .all()
        )
        return rows

    @staticmethod
    def bull_avg_milk_volume(tenant_id: int, semen_id: int):
        return (
            db.session.query(func.avg(MilkLog.amount_liters))
            .join(Cow, Cow.id == MilkLog.cow_id)
            .join(BreedingLog, BreedingLog.cow_id == Cow.id)
            .filter(
                BreedingLog.tenant_id == tenant_id,
                BreedingLog.inventory_semen_id == semen_id,
                BreedingLog.status == "Pregnant",
            )
            .scalar()
        )

    @staticmethod
    def bull_avg_butterfat(tenant_id: int, semen_id: int):
        return (
            db.session.query(func.avg(MilkLog.butterfat_pct))
            .join(Cow, Cow.id == MilkLog.cow_id)
            .join(BreedingLog, BreedingLog.cow_id == Cow.id)
            .filter(
                BreedingLog.tenant_id == tenant_id,
                BreedingLog.inventory_semen_id == semen_id,
                BreedingLog.status == "Pregnant",
                MilkLog.butterfat_pct.isnot(None),
            )
            .scalar()
        )

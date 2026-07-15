from __future__ import annotations

from app import db
from app.models.inventory_standards import (
    IngredientCategoryBaseline,
    IngredientStandard,
    IngredientStandardSyncJob,
    IngredientStandardSynonym,
)


class InventoryStandardsRepository:
    @staticmethod
    def list_standards(*, tenant_id: int | None = None):
        query = IngredientStandard.query.filter_by(is_active=True)
        query = query.filter((IngredientStandard.tenant_id == tenant_id) | (IngredientStandard.tenant_id.is_(None)))
        return query.order_by(IngredientStandard.tenant_id.desc(), IngredientStandard.canonical_name.asc()).all()

    @staticmethod
    def list_baselines(*, tenant_id: int | None = None):
        query = IngredientCategoryBaseline.query.filter_by(is_active=True)
        query = query.filter((IngredientCategoryBaseline.tenant_id == tenant_id) | (IngredientCategoryBaseline.tenant_id.is_(None)))
        return query.order_by(IngredientCategoryBaseline.tenant_id.desc(), IngredientCategoryBaseline.category.asc()).all()

    @staticmethod
    def find_standard_by_name_or_synonym(*, tenant_id: int | None, normalized_name: str):
        direct = (
            IngredientStandard.query
            .filter(
                IngredientStandard.is_active.is_(True),
                IngredientStandard.canonical_name == normalized_name,
                (IngredientStandard.tenant_id == tenant_id) | (IngredientStandard.tenant_id.is_(None)),
            )
            .order_by(IngredientStandard.tenant_id.desc(), IngredientStandard.updated_at.desc())
            .first()
        )
        if direct:
            return direct

        synonym_match = (
            db.session.query(IngredientStandard)
            .join(IngredientStandardSynonym, IngredientStandardSynonym.standard_id == IngredientStandard.id)
            .filter(
                IngredientStandard.is_active.is_(True),
                IngredientStandardSynonym.synonym == normalized_name,
                (IngredientStandard.tenant_id == tenant_id) | (IngredientStandard.tenant_id.is_(None)),
            )
            .order_by(IngredientStandard.tenant_id.desc(), IngredientStandard.updated_at.desc())
            .first()
        )
        return synonym_match

    @staticmethod
    def find_category_baseline(*, tenant_id: int | None, normalized_category: str):
        return (
            IngredientCategoryBaseline.query
            .filter(
                IngredientCategoryBaseline.is_active.is_(True),
                IngredientCategoryBaseline.category == normalized_category,
                (IngredientCategoryBaseline.tenant_id == tenant_id) | (IngredientCategoryBaseline.tenant_id.is_(None)),
            )
            .order_by(IngredientCategoryBaseline.tenant_id.desc(), IngredientCategoryBaseline.updated_at.desc())
            .first()
        )

    @staticmethod
    def upsert_standard(*, tenant_id: int | None, canonical_name: str, data: dict, synonyms: list[str] | None, actor_id: int | None):
        standard = (
            IngredientStandard.query
            .filter_by(tenant_id=tenant_id, canonical_name=canonical_name, standards_version=data['standards_version'])
            .first()
        )
        if not standard:
            standard = IngredientStandard(
                tenant_id=tenant_id,
                canonical_name=canonical_name,
                standards_version=data['standards_version'],
                created_by=actor_id,
            )
            db.session.add(standard)

        standard.protein_grams_per_kg = data['protein_grams_per_kg']
        standard.energy_mj_per_kg = data['energy_mj_per_kg']
        standard.fiber_grams_per_kg = data['fiber_grams_per_kg']
        standard.cost_per_kg = data.get('cost_per_kg', 0)
        standard.source_reference = data.get('source_reference')
        standard.effective_date = data.get('effective_date')
        standard.updated_by = actor_id
        standard.is_active = True

        if standard.id is None:
            db.session.flush()

        if synonyms is not None:
            IngredientStandardSynonym.query.filter_by(standard_id=standard.id).delete()
            for synonym in synonyms:
                normalized = (synonym or '').strip().lower()
                if normalized:
                    db.session.add(IngredientStandardSynonym(standard_id=standard.id, synonym=normalized))

        db.session.commit()
        return standard

    @staticmethod
    def upsert_category_baseline(*, tenant_id: int | None, category: str, data: dict, actor_id: int | None):
        baseline = (
            IngredientCategoryBaseline.query
            .filter_by(tenant_id=tenant_id, category=category, standards_version=data['standards_version'])
            .first()
        )
        if not baseline:
            baseline = IngredientCategoryBaseline(
                tenant_id=tenant_id,
                category=category,
                standards_version=data['standards_version'],
                created_by=actor_id,
            )
            db.session.add(baseline)

        baseline.protein_grams_per_kg = data['protein_grams_per_kg']
        baseline.energy_mj_per_kg = data['energy_mj_per_kg']
        baseline.fiber_grams_per_kg = data['fiber_grams_per_kg']
        baseline.cost_per_kg = data.get('cost_per_kg', 0)
        baseline.source_reference = data.get('source_reference')
        baseline.effective_date = data.get('effective_date')
        baseline.updated_by = actor_id
        baseline.is_active = True

        db.session.commit()
        return baseline

    @staticmethod
    def create_sync_job(*, tenant_id: int | None, source: str, actor_id: int | None):
        job = IngredientStandardSyncJob(
            tenant_id=tenant_id,
            source=source,
            status='PENDING',
            created_by=actor_id,
        )
        db.session.add(job)
        db.session.commit()
        return job

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from sqlalchemy.exc import SQLAlchemyError

from app.repositories.inventory_standards_repo import InventoryStandardsRepository


class InventoryStandardsService:
    """Tenant-aware ingredient standards with DB-first lookup and curated fallback."""

    STANDARDS_VERSION = "2026.07"

    NUTRITION_KEYS = (
        "protein_grams_per_kg",
        "energy_mj_per_kg",
        "fiber_grams_per_kg",
        "cost_per_kg",
    )

    FALLBACK_INGREDIENT_STANDARDS = {
        "hay": {
            "protein_grams_per_kg": Decimal("120"),
            "energy_mj_per_kg": Decimal("8.50"),
            "fiber_grams_per_kg": Decimal("320"),
            "cost_per_kg": Decimal("18.00"),
            "source_reference": "Local curated baseline - forage profile",
            "effective_date": "2026-07-01",
            "updated_at": "2026-07-01T00:00:00Z",
        },
        "napier grass": {
            "protein_grams_per_kg": Decimal("95"),
            "energy_mj_per_kg": Decimal("8.20"),
            "fiber_grams_per_kg": Decimal("300"),
            "cost_per_kg": Decimal("10.00"),
            "source_reference": "Local curated baseline - tropical grasses",
            "effective_date": "2026-07-01",
            "updated_at": "2026-07-01T00:00:00Z",
        },
        "dry maize stalks": {
            "protein_grams_per_kg": Decimal("45"),
            "energy_mj_per_kg": Decimal("6.30"),
            "fiber_grams_per_kg": Decimal("420"),
            "cost_per_kg": Decimal("7.00"),
            "source_reference": "Local curated baseline - crop residues",
            "effective_date": "2026-07-01",
            "updated_at": "2026-07-01T00:00:00Z",
        },
        "silage": {
            "protein_grams_per_kg": Decimal("85"),
            "energy_mj_per_kg": Decimal("9.10"),
            "fiber_grams_per_kg": Decimal("260"),
            "cost_per_kg": Decimal("15.00"),
            "source_reference": "Local curated baseline - silage profile",
            "effective_date": "2026-07-01",
            "updated_at": "2026-07-01T00:00:00Z",
        },
        "maize bran": {
            "protein_grams_per_kg": Decimal("140"),
            "energy_mj_per_kg": Decimal("10.50"),
            "fiber_grams_per_kg": Decimal("110"),
            "cost_per_kg": Decimal("30.00"),
            "source_reference": "Local curated baseline - concentrates",
            "effective_date": "2026-07-01",
            "updated_at": "2026-07-01T00:00:00Z",
        },
    }

    FALLBACK_CATEGORY_BASELINES = {
        "bulk feed": {
            "protein_grams_per_kg": Decimal("90"),
            "energy_mj_per_kg": Decimal("8.00"),
            "fiber_grams_per_kg": Decimal("260"),
            "cost_per_kg": Decimal("12.00"),
            "source_reference": "Local curated category baseline - bulk feed",
            "effective_date": "2026-07-01",
            "updated_at": "2026-07-01T00:00:00Z",
        },
        "feed": {
            "protein_grams_per_kg": Decimal("90"),
            "energy_mj_per_kg": Decimal("8.00"),
            "fiber_grams_per_kg": Decimal("260"),
            "cost_per_kg": Decimal("12.00"),
            "source_reference": "Local curated category baseline - feed",
            "effective_date": "2026-07-01",
            "updated_at": "2026-07-01T00:00:00Z",
        },
    }

    SYNONYMS = {
        "napier": "napier grass",
        "elephant grass": "napier grass",
        "dry maize stalk": "dry maize stalks",
        "stover": "dry maize stalks",
        "maize silage": "silage",
        "baled hay": "hay",
    }

    @staticmethod
    def _normalize(text: str | None) -> str:
        value = (text or "").strip().lower()
        return " ".join(value.split())

    @classmethod
    def _canonical_ingredient(cls, name: str | None) -> str:
        normalized = cls._normalize(name)
        return cls.SYNONYMS.get(normalized, normalized)

    @staticmethod
    def _to_decimal(value, fallback: Decimal = Decimal("0")) -> Decimal:
        try:
            return Decimal(str(value))
        except Exception:
            return fallback

    @staticmethod
    def _to_date(value):
        if value is None or value == "":
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except Exception:
            return None

    @classmethod
    def _from_standard_row(cls, row) -> dict:
        synonyms = sorted([entry.synonym for entry in getattr(row, 'synonyms', []) if entry.synonym])
        return {
            "canonical_name": row.canonical_name,
            "synonyms": synonyms,
            "protein_grams_per_kg": cls._to_decimal(row.protein_grams_per_kg),
            "energy_mj_per_kg": cls._to_decimal(row.energy_mj_per_kg),
            "fiber_grams_per_kg": cls._to_decimal(row.fiber_grams_per_kg),
            "cost_per_kg": cls._to_decimal(row.cost_per_kg),
            "source_reference": row.source_reference,
            "effective_date": str(row.effective_date) if row.effective_date else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "standards_version": row.standards_version or cls.STANDARDS_VERSION,
            "default_source": f"ingredient:{row.canonical_name}",
        }

    @classmethod
    def _from_baseline_row(cls, row) -> dict:
        return {
            "category": row.category,
            "protein_grams_per_kg": cls._to_decimal(row.protein_grams_per_kg),
            "energy_mj_per_kg": cls._to_decimal(row.energy_mj_per_kg),
            "fiber_grams_per_kg": cls._to_decimal(row.fiber_grams_per_kg),
            "cost_per_kg": cls._to_decimal(row.cost_per_kg),
            "source_reference": row.source_reference,
            "effective_date": str(row.effective_date) if row.effective_date else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "standards_version": row.standards_version or cls.STANDARDS_VERSION,
            "default_source": f"category:{row.category}",
        }

    @classmethod
    def resolve_standard(cls, *, name: str | None, category: str | None, tenant_id: int | None = None):
        normalized_name = cls._canonical_ingredient(name)
        if normalized_name:
            standard_row = None
            try:
                standard_row = InventoryStandardsRepository.find_standard_by_name_or_synonym(
                    tenant_id=tenant_id,
                    normalized_name=normalized_name,
                )
            except SQLAlchemyError:
                # If standards tables are unavailable, continue with curated fallback defaults.
                standard_row = None
            if standard_row:
                payload = cls._from_standard_row(standard_row)
                return payload["default_source"], payload

            if normalized_name in cls.FALLBACK_INGREDIENT_STANDARDS:
                fallback = dict(cls.FALLBACK_INGREDIENT_STANDARDS[normalized_name])
                fallback["standards_version"] = cls.STANDARDS_VERSION
                return f"ingredient:{normalized_name}", fallback

        normalized_category = cls._normalize(category)
        if normalized_category:
            baseline_row = None
            try:
                baseline_row = InventoryStandardsRepository.find_category_baseline(
                    tenant_id=tenant_id,
                    normalized_category=normalized_category,
                )
            except SQLAlchemyError:
                # If standards tables are unavailable, continue with curated fallback defaults.
                baseline_row = None
            if baseline_row:
                payload = cls._from_baseline_row(baseline_row)
                return payload["default_source"], payload

            if normalized_category in cls.FALLBACK_CATEGORY_BASELINES:
                fallback = dict(cls.FALLBACK_CATEGORY_BASELINES[normalized_category])
                fallback["standards_version"] = cls.STANDARDS_VERSION
                return f"category:{normalized_category}", fallback

        return "none", {}

    @classmethod
    def lookup_defaults(cls, *, name: str | None, category: str | None, tenant_id: int | None = None) -> dict[str, Decimal]:
        _, defaults = cls.resolve_standard(name=name, category=category, tenant_id=tenant_id)
        return {key: cls._to_decimal(defaults.get(key, Decimal("0"))) for key in cls.NUTRITION_KEYS}

    @classmethod
    def apply_defaults(
        cls,
        *,
        name: str | None,
        category: str | None,
        energy_mj_per_kg,
        protein_grams_per_kg,
        fiber_grams_per_kg,
        cost_per_kg,
        tenant_id: int | None = None,
    ) -> dict:
        source, defaults = cls.resolve_standard(name=name, category=category, tenant_id=tenant_id)

        def _choose(value, key):
            if value is None:
                return cls._to_decimal(defaults.get(key, Decimal("0")))
            return cls._to_decimal(value, cls._to_decimal(defaults.get(key, Decimal("0"))))

        values = {
            "energy_mj_per_kg": _choose(energy_mj_per_kg, "energy_mj_per_kg"),
            "protein_grams_per_kg": _choose(protein_grams_per_kg, "protein_grams_per_kg"),
            "fiber_grams_per_kg": _choose(fiber_grams_per_kg, "fiber_grams_per_kg"),
            "cost_per_kg": _choose(cost_per_kg, "cost_per_kg"),
        }

        return {
            "values": values,
            "default_source": source,
            "standards_version": defaults.get("standards_version") or cls.STANDARDS_VERSION,
            "source_reference": defaults.get("source_reference"),
            "effective_date": defaults.get("effective_date"),
            "updated_at": defaults.get("updated_at"),
        }

    @classmethod
    def infer_item_metadata(
        cls,
        *,
        name: str | None,
        category: str | None,
        energy_mj_per_kg,
        protein_grams_per_kg,
        fiber_grams_per_kg,
        cost_per_kg,
        tenant_id: int | None = None,
    ) -> dict:
        source, defaults = cls.resolve_standard(name=name, category=category, tenant_id=tenant_id)
        if not defaults:
            return {"default_source": "none", "standards_version": None}

        matches_default = (
            cls._to_decimal(energy_mj_per_kg) == cls._to_decimal(defaults.get("energy_mj_per_kg"))
            and cls._to_decimal(protein_grams_per_kg) == cls._to_decimal(defaults.get("protein_grams_per_kg"))
            and cls._to_decimal(fiber_grams_per_kg) == cls._to_decimal(defaults.get("fiber_grams_per_kg"))
            and cls._to_decimal(cost_per_kg) == cls._to_decimal(defaults.get("cost_per_kg"))
        )

        return {
            "default_source": source if matches_default else "user_override",
            "standards_version": defaults.get("standards_version") or cls.STANDARDS_VERSION,
            "source_reference": defaults.get("source_reference"),
        }

    @classmethod
    def list_standards(cls, *, tenant_id: int | None = None) -> dict:
        standards = []
        baselines = []

        try:
            standard_rows = InventoryStandardsRepository.list_standards(tenant_id=tenant_id)
        except SQLAlchemyError:
            standard_rows = []
        try:
            baseline_rows = InventoryStandardsRepository.list_baselines(tenant_id=tenant_id)
        except SQLAlchemyError:
            baseline_rows = []

        if standard_rows:
            for row in standard_rows:
                payload = cls._from_standard_row(row)
                standards.append({
                    "canonical_name": payload["canonical_name"],
                    "synonyms": payload["synonyms"],
                    "protein_grams_per_kg": float(payload["protein_grams_per_kg"]),
                    "energy_mj_per_kg": float(payload["energy_mj_per_kg"]),
                    "fiber_grams_per_kg": float(payload["fiber_grams_per_kg"]),
                    "cost_per_kg": float(payload["cost_per_kg"]),
                    "source_reference": payload.get("source_reference"),
                    "effective_date": payload.get("effective_date"),
                    "updated_at": payload.get("updated_at"),
                    "standards_version": payload.get("standards_version") or cls.STANDARDS_VERSION,
                })
        else:
            for canonical_name, data in cls.FALLBACK_INGREDIENT_STANDARDS.items():
                synonyms = sorted([raw for raw, canonical in cls.SYNONYMS.items() if canonical == canonical_name])
                standards.append({
                    "canonical_name": canonical_name,
                    "synonyms": synonyms,
                    "protein_grams_per_kg": float(data["protein_grams_per_kg"]),
                    "energy_mj_per_kg": float(data["energy_mj_per_kg"]),
                    "fiber_grams_per_kg": float(data["fiber_grams_per_kg"]),
                    "cost_per_kg": float(data["cost_per_kg"]),
                    "source_reference": data.get("source_reference"),
                    "effective_date": data.get("effective_date"),
                    "updated_at": data.get("updated_at"),
                    "standards_version": cls.STANDARDS_VERSION,
                })

        if baseline_rows:
            for row in baseline_rows:
                payload = cls._from_baseline_row(row)
                baselines.append({
                    "category": payload["category"],
                    "protein_grams_per_kg": float(payload["protein_grams_per_kg"]),
                    "energy_mj_per_kg": float(payload["energy_mj_per_kg"]),
                    "fiber_grams_per_kg": float(payload["fiber_grams_per_kg"]),
                    "cost_per_kg": float(payload["cost_per_kg"]),
                    "source_reference": payload.get("source_reference"),
                    "effective_date": payload.get("effective_date"),
                    "updated_at": payload.get("updated_at"),
                    "standards_version": payload.get("standards_version") or cls.STANDARDS_VERSION,
                })
        else:
            for category, data in cls.FALLBACK_CATEGORY_BASELINES.items():
                baselines.append({
                    "category": category,
                    "protein_grams_per_kg": float(data["protein_grams_per_kg"]),
                    "energy_mj_per_kg": float(data["energy_mj_per_kg"]),
                    "fiber_grams_per_kg": float(data["fiber_grams_per_kg"]),
                    "cost_per_kg": float(data["cost_per_kg"]),
                    "source_reference": data.get("source_reference"),
                    "effective_date": data.get("effective_date"),
                    "updated_at": data.get("updated_at"),
                    "standards_version": cls.STANDARDS_VERSION,
                })

        latest_version = cls.STANDARDS_VERSION
        all_versions = [entry.get("standards_version") for entry in standards + baselines if entry.get("standards_version")]
        if all_versions:
            latest_version = sorted(all_versions)[-1]

        return {"standards": standards, "category_baselines": baselines, "standards_version": latest_version}

    @classmethod
    def upsert_standard(
        cls,
        *,
        canonical_name: str,
        synonyms: list[str] | None,
        data: dict,
        tenant_id: int | None = None,
        actor_id: int | None = None,
    ):
        normalized_name = cls._canonical_ingredient(canonical_name)
        standard_data = {
            "protein_grams_per_kg": cls._to_decimal(data["protein_grams_per_kg"]),
            "energy_mj_per_kg": cls._to_decimal(data["energy_mj_per_kg"]),
            "fiber_grams_per_kg": cls._to_decimal(data["fiber_grams_per_kg"]),
            "cost_per_kg": cls._to_decimal(data.get("cost_per_kg", 0)),
            "source_reference": data.get("source_reference"),
            "effective_date": cls._to_date(data.get("effective_date")),
            "standards_version": data.get("standards_version") or cls.STANDARDS_VERSION,
        }
        InventoryStandardsRepository.upsert_standard(
            tenant_id=tenant_id,
            canonical_name=normalized_name,
            data=standard_data,
            synonyms=synonyms,
            actor_id=actor_id,
        )

        if synonyms:
            for synonym in synonyms:
                normalized_synonym = cls._normalize(synonym)
                if normalized_synonym:
                    cls.SYNONYMS[normalized_synonym] = normalized_name

        return normalized_name

    @classmethod
    def run_backfill_for_tenant(cls, *, tenant_id: int, item_rows: list):
        updated = 0
        skipped = 0

        for item in item_rows:
            if cls._normalize(getattr(item, 'category', None)) != 'bulk feed':
                skipped += 1
                continue

            current_values = {
                'energy_mj_per_kg': cls._to_decimal(getattr(item, 'energy_mj_per_kg', 0)),
                'protein_grams_per_kg': cls._to_decimal(getattr(item, 'protein_grams_per_kg', 0)),
                'fiber_grams_per_kg': cls._to_decimal(getattr(item, 'fiber_grams_per_kg', 0)),
                'cost_per_kg': cls._to_decimal(getattr(item, 'cost_per_kg', 0)),
            }
            if any(value != Decimal('0') for value in current_values.values()):
                skipped += 1
                continue

            payload = cls.apply_defaults(
                tenant_id=tenant_id,
                name=getattr(item, 'name', None),
                category=getattr(item, 'category', None),
                energy_mj_per_kg=None,
                protein_grams_per_kg=None,
                fiber_grams_per_kg=None,
                cost_per_kg=None,
            )
            values = payload['values']
            item.energy_mj_per_kg = values['energy_mj_per_kg']
            item.protein_grams_per_kg = values['protein_grams_per_kg']
            item.fiber_grams_per_kg = values['fiber_grams_per_kg']
            item.cost_per_kg = values['cost_per_kg']
            updated += 1

        return {'updated': updated, 'skipped': skipped}

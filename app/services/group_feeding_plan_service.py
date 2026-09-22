from __future__ import annotations

from datetime import date

from app import db
from app.models.livestock import Cow, CowStatus
from app.models.supply import FeedRecipe, FeedingGroupProfile
from app.services.cow_status_service import CowStatusService


class GroupFeedingPlanService:
    """Plan herd feed requirements by biological feeding cohorts."""

    FEEDING_GROUPS = (
        'lactating',
        'dry',
        'calf_0_3m',
        'calf_3_6m',
        'heifer',
    )

    DEFAULT_PROFILES = {
        'lactating': {
            'avg_body_weight_kg': 500.0,
            'dmi_percent_bw': 3.0,
            'target_protein_percent': 16.5,
            'feeding_times_per_day': 3,
        },
        'dry': {
            'avg_body_weight_kg': 480.0,
            'dmi_percent_bw': 2.0,
            'target_protein_percent': 12.0,
            'feeding_times_per_day': 2,
        },
        'calf_0_3m': {
            'avg_body_weight_kg': 80.0,
            'dmi_percent_bw': 2.5,
            'target_protein_percent': 20.0,
            'feeding_times_per_day': 3,
        },
        'calf_3_6m': {
            'avg_body_weight_kg': 150.0,
            'dmi_percent_bw': 2.4,
            'target_protein_percent': 18.0,
            'feeding_times_per_day': 3,
        },
        'heifer': {
            'avg_body_weight_kg': 300.0,
            'dmi_percent_bw': 2.3,
            'target_protein_percent': 14.0,
            'feeding_times_per_day': 2,
        },
    }

    @classmethod
    def normalize_group_name(cls, value: str) -> str:
        normalized = str(value or '').strip().lower()
        aliases = {
            'calf0_3m': 'calf_0_3m',
            'calf_0to3m': 'calf_0_3m',
            'calf_0-3m': 'calf_0_3m',
            'calf3_6m': 'calf_3_6m',
            'calf_3to6m': 'calf_3_6m',
            'calf_3-6m': 'calf_3_6m',
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in cls.FEEDING_GROUPS:
            allowed = ', '.join(cls.FEEDING_GROUPS)
            raise ValueError(f'feeding_group must be one of: {allowed}.')
        return normalized

    @classmethod
    def _validate_profile_payload(cls, payload: dict) -> dict:
        fields = {
            'avg_body_weight_kg': float,
            'dmi_percent_bw': float,
            'target_protein_percent': float,
            'feeding_times_per_day': int,
        }
        sanitized = {}

        for key, caster in fields.items():
            if key not in payload:
                raise ValueError(f'{key} is required.')
            try:
                sanitized[key] = caster(payload[key])
            except (TypeError, ValueError):
                raise ValueError(f'{key} must be numeric.')

        if sanitized['avg_body_weight_kg'] <= 0:
            raise ValueError('avg_body_weight_kg must be > 0.')
        if sanitized['dmi_percent_bw'] <= 0 or sanitized['dmi_percent_bw'] > 10:
            raise ValueError('dmi_percent_bw must be > 0 and <= 10.')
        if sanitized['target_protein_percent'] <= 0 or sanitized['target_protein_percent'] > 100:
            raise ValueError('target_protein_percent must be > 0 and <= 100.')
        if sanitized['feeding_times_per_day'] <= 0 or sanitized['feeding_times_per_day'] > 12:
            raise ValueError('feeding_times_per_day must be > 0 and <= 12.')

        return sanitized

    @classmethod
    def _cow_group(cls, cow: Cow) -> str:
        # Use the same authoritative status computation as herd list APIs so
        # group planning and herd screens cannot drift. Any override here based
        # on age/last_calving_date would silently disagree with what the Herd
        # Register and Animal Passport already show for the same cow — e.g. a
        # cow explicitly marked Lactating (with a saved milk goal) but whose
        # calving was never logged through the calving workflow would get
        # miscounted as a heifer here while still showing Lactating everywhere
        # else. Trust the computed status as-is.
        status = (CowStatusService.compute_current_status(cow) or '').strip().lower()
        age_in_months = cow.age_in_months

        # Age buckets are authoritative for calf cohorts, regardless of any
        # stale/default lifecycle flags.
        if age_in_months is not None and age_in_months < 3:
            return 'calf_0_3m'
        if age_in_months is not None and age_in_months < 6:
            return 'calf_3_6m'

        if status == CowStatus.CALF.lower():
            return 'calf_3_6m'

        if status == CowStatus.LACTATING.lower():
            return 'lactating'
        if status == CowStatus.DRY.lower():
            return 'dry'

        return 'heifer'

    @classmethod
    def _get_profile_rows(cls, tenant_id: int) -> dict[str, FeedingGroupProfile]:
        rows = FeedingGroupProfile.query.filter_by(tenant_id=tenant_id, is_active=True).all()
        return {row.feeding_group: row for row in rows}

    @classmethod
    def get_profiles(cls, tenant_id: int) -> dict:
        rows_by_group = cls._get_profile_rows(tenant_id)
        profiles = []

        for group in cls.FEEDING_GROUPS:
            defaults = cls.DEFAULT_PROFILES[group]
            row = rows_by_group.get(group)
            profiles.append({
                'feeding_group': group,
                'avg_body_weight_kg': float(row.avg_body_weight_kg) if row else defaults['avg_body_weight_kg'],
                'dmi_percent_bw': float(row.dmi_percent_bw) if row else defaults['dmi_percent_bw'],
                'target_protein_percent': float(row.target_protein_percent) if row else defaults['target_protein_percent'],
                'feeding_times_per_day': int(row.feeding_times_per_day) if row else defaults['feeding_times_per_day'],
                'is_default': row is None,
            })

        return {
            'tenant_id': tenant_id,
            'profiles': profiles,
            'count': len(profiles),
        }

    @classmethod
    def upsert_profile(cls, tenant_id: int, feeding_group: str, payload: dict) -> dict:
        normalized_group = cls.normalize_group_name(feeding_group)
        sanitized = cls._validate_profile_payload(payload)

        row = FeedingGroupProfile.query.filter_by(
            tenant_id=tenant_id,
            feeding_group=normalized_group,
        ).first()

        if not row:
            row = FeedingGroupProfile(
                tenant_id=tenant_id,
                feeding_group=normalized_group,
            )
            db.session.add(row)

        row.avg_body_weight_kg = sanitized['avg_body_weight_kg']
        row.dmi_percent_bw = sanitized['dmi_percent_bw']
        row.target_protein_percent = sanitized['target_protein_percent']
        row.feeding_times_per_day = sanitized['feeding_times_per_day']
        row.is_active = True

        db.session.commit()

        return {
            'feeding_group': row.feeding_group,
            'avg_body_weight_kg': float(row.avg_body_weight_kg),
            'dmi_percent_bw': float(row.dmi_percent_bw),
            'target_protein_percent': float(row.target_protein_percent),
            'feeding_times_per_day': int(row.feeding_times_per_day),
            'message': 'Profile saved.',
        }

    @classmethod
    def calculate_plan_by_group(cls, tenant_id: int) -> dict:
        rows_by_group = cls._get_profile_rows(tenant_id)
        recipe_rows = (
            FeedRecipe.query
            .filter_by(tenant_id=tenant_id, is_active=True)
            .filter(FeedRecipe.feeding_group.isnot(None))
            .order_by(FeedRecipe.id.desc())
            .all()
        )
        recipes_by_group = {}
        for recipe in recipe_rows:
            recipes_by_group.setdefault(recipe.feeding_group, recipe)
        cows = Cow.query.filter_by(tenant_id=tenant_id, is_active=True).all()

        counts = {group: 0 for group in cls.FEEDING_GROUPS}
        for cow in cows:
            group = cls._cow_group(cow)
            counts[group] += 1

        group_rows = []
        total_daily_feed_kg = 0.0
        total_daily_protein_kg = 0.0

        for group in cls.FEEDING_GROUPS:
            defaults = cls.DEFAULT_PROFILES[group]
            row = rows_by_group.get(group)
            avg_body_weight_kg = float(row.avg_body_weight_kg) if row else defaults['avg_body_weight_kg']
            dmi_percent_bw = float(row.dmi_percent_bw) if row else defaults['dmi_percent_bw']
            target_protein_percent = float(row.target_protein_percent) if row else defaults['target_protein_percent']
            feeding_times_per_day = int(row.feeding_times_per_day) if row else defaults['feeding_times_per_day']

            headcount = counts[group]
            total_ration_per_head_kg = avg_body_weight_kg * (dmi_percent_bw / 100.0)
            recipe = recipes_by_group.get(group)
            quantity_basis = recipe.quantity_basis if recipe else 'total_ration'
            concentrate_rate = float(recipe.concentrate_kg_per_head_day) if recipe and recipe.concentrate_kg_per_head_day else None
            requires_concentrate_rate = bool(recipe and quantity_basis == 'concentrate' and concentrate_rate is None)
            daily_feed_per_head_kg = concentrate_rate if quantity_basis == 'concentrate' else total_ration_per_head_kg
            if daily_feed_per_head_kg is None:
                daily_feed_per_head_kg = 0.0
            daily_group_feed_kg = headcount * daily_feed_per_head_kg
            daily_group_protein_kg = daily_group_feed_kg * (target_protein_percent / 100.0)
            kg_per_head_per_feeding = daily_feed_per_head_kg / feeding_times_per_day
            group_batch_per_feeding_kg = daily_group_feed_kg / feeding_times_per_day

            assigned_recipe = None
            physical_measures = None
            if recipe:
                assigned_recipe = {
                    'id': recipe.id,
                    'name': recipe.recipe_name,
                    'recipe_type': recipe.recipe_type,
                    'quantity_basis': quantity_basis,
                    'ingredients': [
                        {
                            'inventory_item_id': ingredient.inventory_item_id,
                            'name': ingredient.inventory_item.name if ingredient.inventory_item else None,
                            'percentage': round(float(ingredient.inclusion_percentage), 2),
                            'daily_group_kg': round(daily_group_feed_kg * float(ingredient.inclusion_percentage) / 100.0, 3),
                            'group_kg_per_feeding': round(group_batch_per_feeding_kg * float(ingredient.inclusion_percentage) / 100.0, 3),
                        }
                        for ingredient in recipe.ingredients
                    ],
                }
                measure_payload = {}
                if recipe.bulk_density_kg_per_litre and recipe.bucket_volume_litres:
                    kg_per_bucket = float(recipe.bulk_density_kg_per_litre) * float(recipe.bucket_volume_litres)
                    measure_payload.update({
                        'bulk_density_kg_per_litre': float(recipe.bulk_density_kg_per_litre),
                        'bucket_volume_litres': float(recipe.bucket_volume_litres),
                        'kg_per_bucket': round(kg_per_bucket, 3),
                        'daily_group_buckets': round(daily_group_feed_kg / kg_per_bucket, 2),
                        'group_buckets_per_feeding': round(group_batch_per_feeding_kg / kg_per_bucket, 2),
                    })
                if recipe.scoop_weight_kg:
                    kg_per_scoop = float(recipe.scoop_weight_kg)
                    measure_payload.update({
                        'kg_per_scoop': kg_per_scoop,
                        'daily_group_scoops': round(daily_group_feed_kg / kg_per_scoop, 2),
                        'group_scoops_per_feeding': round(group_batch_per_feeding_kg / kg_per_scoop, 2),
                    })
                physical_measures = measure_payload or None

            total_daily_feed_kg += daily_group_feed_kg
            total_daily_protein_kg += daily_group_protein_kg

            group_rows.append({
                'feeding_group': group,
                'headcount': headcount,
                'avg_body_weight_kg': round(avg_body_weight_kg, 2),
                'dmi_percent_bw': round(dmi_percent_bw, 2),
                'target_protein_percent': round(target_protein_percent, 2),
                'feeding_times_per_day': feeding_times_per_day,
                'quantity_basis': quantity_basis,
                'quantity_label': 'Concentrate' if quantity_basis == 'concentrate' else 'Total ration (dry matter)',
                'total_ration_kg_per_head_day': round(total_ration_per_head_kg, 2),
                'daily_kg_per_head': round(daily_feed_per_head_kg, 2),
                'kg_per_head_per_feeding': round(kg_per_head_per_feeding, 2),
                'daily_group_batch_kg': round(daily_group_feed_kg, 2),
                'group_batch_per_feeding_kg': round(group_batch_per_feeding_kg, 2),
                'daily_feed_per_head_kg': round(daily_feed_per_head_kg, 2),
                'daily_group_feed_kg': round(daily_group_feed_kg, 2),
                'daily_group_protein_kg': round(daily_group_protein_kg, 2),
                'profile_source': 'custom' if row else 'default',
                'assigned_recipe': assigned_recipe,
                'physical_measures': physical_measures,
                'requires_concentrate_rate': requires_concentrate_rate,
            })

        return {
            'generated_on': date.today().isoformat(),
            'tenant_id': tenant_id,
            'groups': group_rows,
            'totals': {
                'total_active_animals': len(cows),
                'total_daily_feed_kg': round(total_daily_feed_kg, 2),
                'total_planned_mix_kg': round(total_daily_feed_kg, 2),
                'total_daily_protein_kg': round(total_daily_protein_kg, 2),
            },
        }

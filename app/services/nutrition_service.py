from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import current_app, jsonify
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import func

from app import db
from app.models.supply import (
    BatchIngredient,
    FeedBatch,
    FeedBatchConsumptionEvent,
    FeedFormula,
    FeedRecipe,
    FormulaIngredient,
    Ingredient,
    InventoryItem,
    InventoryTransaction,
    MilkLog,
)
from app.services.feeding_group_recipe_policy_service import FeedingGroupRecipePolicyService


class InsufficientStockError(ValueError):
    def __init__(self, shortages: list[dict], max_batch_weight: Decimal):
        self.shortages = shortages
        self.max_batch_weight = max_batch_weight
        names = ', '.join(shortage['ingredientName'] for shortage in shortages)
        super().__init__(f'Insufficient stock for: {names}. Reduce the batch size or restock these items.')


class NutritionService:
    @staticmethod
    def _optional_int(value):
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {'', 'null', 'none'}:
                return None
            value = normalized
        try:
            parsed = int(value)
            return parsed if parsed > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _required_int(value, field_name: str) -> int:
        parsed = NutritionService._optional_int(value)
        if parsed is None:
            raise ValueError(f'{field_name} must be a valid positive integer.')
        return parsed

    @staticmethod
    def _to_bool(value, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {'1', 'true', 'yes', 'y', 'on'}:
                return True
            if normalized in {'0', 'false', 'no', 'n', 'off', ''}:
                return False
        return default

    @staticmethod
    def _lag_window_for_batch(batch: FeedBatch):
        start_date = batch.mixed_on + timedelta(days=3)
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)

        if batch.depleted_on is not None:
            end_date = batch.depleted_on + timedelta(days=3)
            end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)
        else:
            end_dt = datetime.now(timezone.utc)
            end_date = end_dt.date()

        return start_date, end_date, start_dt, end_dt

    @staticmethod
    def _serialize_batch_ingredient_breakdown(batch: FeedBatch) -> list[dict]:
        rows = []
        for entry in batch.ingredients or []:
            ingredient_name = None
            if entry.ingredient is not None:
                ingredient_name = entry.ingredient.name

            protein_grams_per_kg = float(entry.locked_protein_grams_per_kg or 0)
            rows.append({
                'ingredient_id': entry.ingredient_id,
                'ingredientId': entry.ingredient_id,
                'name': ingredient_name,
                'ingredient_name': ingredient_name,
                'ingredientName': ingredient_name,
                'percentage': float(entry.percentage),
                'weight': float(entry.weight),
                'locked_cost_per_kg': float(entry.locked_cost_per_kg),
                'lockedCostPerKg': float(entry.locked_cost_per_kg),
                'protein_grams_per_kg': protein_grams_per_kg,
                'proteinGramsPerKg': protein_grams_per_kg,
            })
        return rows

    @staticmethod
    def _batch_consumption_pace(batch: FeedBatch, *, tenant_id: int, total_consumed: Decimal | None = None) -> dict:
        """Derive consumption pace only from recorded feeding events."""
        total_weight = Decimal(str(batch.total_weight or 0))

        consumption_summary = (
            db.session.query(
                func.coalesce(func.sum(FeedBatchConsumptionEvent.consumed_weight), 0),
                func.min(FeedBatchConsumptionEvent.consumed_on),
                func.max(FeedBatchConsumptionEvent.consumed_on),
            )
            .filter(
                FeedBatchConsumptionEvent.tenant_id == tenant_id,
                FeedBatchConsumptionEvent.batch_id == batch.id,
            )
            .one()
        )
        if total_consumed is None:
            total_consumed = consumption_summary[0]
        total_consumed = Decimal(str(total_consumed or 0))
        remaining = max(Decimal('0'), total_weight - total_consumed)

        basis = None
        daily_rate = Decimal('0')
        first_recorded_on = consumption_summary[1]
        last_recorded_on = consumption_summary[2]
        if total_consumed > 0 and first_recorded_on and last_recorded_on:
            days_in_use = Decimal(str((last_recorded_on - first_recorded_on).days + 1))
            daily_rate = total_consumed / days_in_use
            basis = 'recorded_events'

        if batch.status == 'DEPLETED':
            days_until_empty = 0.0
        elif daily_rate > 0 and remaining > 0:
            days_until_empty = float((remaining / daily_rate).quantize(Decimal('0.1')))
        elif remaining <= 0:
            days_until_empty = 0.0
        else:
            days_until_empty = None

        return {
            'total_consumed_kg': float(total_consumed),
            'remaining_kg': float(remaining),
            'daily_feeding_rate_kg': round(float(daily_rate), 3),
            'dailyFeedingRateKg': round(float(daily_rate), 3),
            'planned_daily_rate_kg': None,
            'days_until_empty': days_until_empty,
            'daysUntilEmpty': days_until_empty,
            'rate_basis': basis,
        }

    @staticmethod
    def get_batch_consumption_status(*, tenant_id: int, batch_id: int):
        batch = FeedBatch.query.filter_by(id=batch_id, tenant_id=tenant_id).first()
        if not batch:
            return jsonify({'error': 'Batch not found for this tenant.'}), 404

        pace = NutritionService._batch_consumption_pace(batch, tenant_id=tenant_id)
        return jsonify({
            'batchId': batch.id,
            'batchName': batch.batch_name,
            'status': batch.status,
            'mixedOn': str(batch.mixed_on),
            'depletedOn': str(batch.depleted_on) if batch.depleted_on else None,
            'totalWeight': float(batch.total_weight),
            **pace,
        }), 200

    @staticmethod
    def process_and_save_batch(*, tenant_id: int, user_id: int | None, data: dict):
        batch_name = (data.get('batchName') or 'Custom Quick Mix').strip()
        is_saved_as_template = NutritionService._to_bool(data.get('isSavedAsTemplate'), default=False)
        formula_name = (data.get('formulaName') or batch_name).strip()
        formula_id_raw = data.get('formulaId')
        formula_id = NutritionService._optional_int(formula_id_raw)
        if formula_id is None and formula_id_raw not in (None, '') and str(formula_id_raw).strip().lower() not in {'null', 'none'}:
            return jsonify({'error': 'formulaId must be a valid positive integer or null.'}), 400
        ingredients_payload = data.get('ingredients') or []

        if not ingredients_payload:
            return jsonify({'error': 'At least one ingredient is required.'}), 400

        try:
            total_weight = Decimal(str(data.get('totalWeight')))
        except (TypeError, InvalidOperation):
            return jsonify({'error': 'totalWeight must be a valid number.'}), 400

        if total_weight <= 0:
            return jsonify({'error': 'totalWeight must be greater than zero.'}), 400

        submitted_weight_sum = Decimal('0')
        for entry in ingredients_payload:
            try:
                submitted_weight_sum += Decimal(str(entry.get('weight') or 0))
            except (TypeError, InvalidOperation):
                return jsonify({'error': 'Each ingredient requires a valid weight.'}), 400
        if submitted_weight_sum <= 0 or abs(submitted_weight_sum - total_weight) > (total_weight * Decimal('0.01')):
            return jsonify({
                'error': (
                    f'Ingredient weights must sum to the batch total ({total_weight} kg); '
                    f'got {submitted_weight_sum} kg.'
                )
            }), 400

        try:
            formula = None
            planner_recipe = None
            if formula_id is not None:
                formula = (
                    FeedFormula.query.filter_by(id=formula_id, tenant_id=tenant_id)
                    .first()
                )
                if not formula:
                    # Frontend may pass FeedRecipe IDs in formulaId from planner flows.
                    planner_recipe = (
                        FeedRecipe.query.filter_by(id=formula_id, tenant_id=tenant_id)
                        .first()
                    )
                    if not planner_recipe:
                        return jsonify({'error': 'Formula not found for this tenant.'}), 404

            resolved_entries = []
            resolved_ingredient_ids = set()
            submitted_percentage_sum = Decimal('0')
            shortages = []
            max_batch_weights = []
            total_cost = Decimal('0')
            for entry in ingredients_payload:
                submitted_id = NutritionService._required_int(entry.get('ingredientId'), 'ingredientId')
                inventory_item_id = NutritionService._optional_int(
                    entry.get('inventoryItemId') or entry.get('inventory_item_id')
                )
                try:
                    weight = Decimal(str(entry.get('weight')))
                except (TypeError, InvalidOperation):
                    raise ValueError('Each ingredient requires a valid weight.')

                if weight <= 0:
                    raise ValueError('Ingredient weight must be greater than zero.')

                ingredient = None
                inventory_item = None
                if inventory_item_id is not None:
                    inventory_query = InventoryItem.query.filter_by(
                        id=inventory_item_id,
                        tenant_id=tenant_id,
                    )
                    if db.engine.dialect.name == 'postgresql':
                        inventory_query = inventory_query.with_for_update()
                    inventory_item = inventory_query.first()
                    if not inventory_item:
                        raise ValueError(f'Inventory item {inventory_item_id} not found for this tenant.')
                else:
                    ingredient_query = Ingredient.query.filter_by(id=submitted_id, tenant_id=tenant_id)
                    if db.engine.dialect.name == 'postgresql':
                        ingredient_query = ingredient_query.with_for_update()
                    ingredient = ingredient_query.first()

                    if ingredient is None:
                        inventory_query = InventoryItem.query.filter_by(id=submitted_id, tenant_id=tenant_id)
                        if db.engine.dialect.name == 'postgresql':
                            inventory_query = inventory_query.with_for_update()
                        inventory_item = inventory_query.first()

                if inventory_item is not None:
                    ingredient = Ingredient.query.filter_by(
                        tenant_id=tenant_id,
                        name=inventory_item.name,
                    ).first()
                    if ingredient is None:
                        ingredient = Ingredient(
                            tenant_id=tenant_id,
                            name=inventory_item.name,
                            current_cost_per_kg=inventory_item.cost_per_kg,
                            stock_quantity=inventory_item.current_qty,
                        )
                        db.session.add(ingredient)
                        db.session.flush()
                    else:
                        ingredient.current_cost_per_kg = inventory_item.cost_per_kg
                        ingredient.stock_quantity = inventory_item.current_qty
                elif ingredient is not None:
                    inventory_query = InventoryItem.query.filter_by(
                        tenant_id=tenant_id,
                        name=ingredient.name,
                    )
                    if db.engine.dialect.name == 'postgresql':
                        inventory_query = inventory_query.with_for_update()
                    inventory_item = inventory_query.first()
                    if inventory_item is not None:
                        ingredient.current_cost_per_kg = inventory_item.cost_per_kg
                        ingredient.stock_quantity = inventory_item.current_qty

                if ingredient is None:
                    raise ValueError(f'Ingredient {submitted_id} not found for this tenant.')
                if ingredient.id in resolved_ingredient_ids:
                    raise ValueError(f'Ingredient {ingredient.name} appears more than once in this batch.')
                resolved_ingredient_ids.add(ingredient.id)

                stock_quantity = (
                    Decimal(str(inventory_item.current_qty))
                    if inventory_item is not None
                    else Decimal(str(ingredient.stock_quantity))
                )
                max_batch_weights.append((stock_quantity * total_weight) / weight)
                if stock_quantity < weight:
                    shortages.append({
                        'ingredientId': submitted_id,
                        'inventoryItemId': inventory_item.id if inventory_item is not None else None,
                        'ingredientName': ingredient.name,
                        'availableKg': float(stock_quantity),
                        'requiredKg': float(weight),
                        'shortfallKg': float(weight - stock_quantity),
                    })

                authoritative_cost = Decimal(str(
                    inventory_item.cost_per_kg
                    if inventory_item is not None
                    else ingredient.current_cost_per_kg
                ))
                total_cost += weight * authoritative_cost

                percentage = entry.get('percentage')
                if percentage is None:
                    percentage_value = (weight / total_weight) * Decimal('100')
                else:
                    try:
                        percentage_value = Decimal(str(percentage))
                    except (TypeError, InvalidOperation):
                        raise ValueError('percentage must be a valid number when provided.')
                if percentage_value <= 0 or percentage_value > 100:
                    raise ValueError('percentage must be greater than zero and no more than 100.')
                expected_percentage = (weight / total_weight) * Decimal('100')
                if percentage is not None and abs(percentage_value - expected_percentage) > Decimal('0.05'):
                    raise ValueError(
                        f'Ingredient percentage must match its weight share; expected '
                        f'{expected_percentage.quantize(Decimal("0.01"))}% for {ingredient.name}.'
                    )
                submitted_percentage_sum += percentage_value

                locked_protein = Decimal(str(
                    inventory_item.protein_grams_per_kg if inventory_item is not None else 0
                ))
                resolved_entries.append({
                    'ingredient': ingredient,
                    'inventory_item': inventory_item,
                    'weight': weight,
                    'percentage': percentage_value,
                    'locked_cost_per_kg': authoritative_cost,
                    'locked_protein_grams_per_kg': locked_protein,
                })

            if abs(submitted_percentage_sum - Decimal('100')) > Decimal('0.05'):
                raise ValueError(
                    f'Ingredient percentages must total 100; got {submitted_percentage_sum}.'
                )

            if shortages:
                raise InsufficientStockError(shortages, min(max_batch_weights))

            cost_per_kg = total_cost / total_weight

            formula_for_save = formula
            if is_saved_as_template:
                if formula_for_save is None:
                    formula_for_save = FeedFormula.query.filter_by(
                        tenant_id=tenant_id,
                        name=formula_name,
                    ).first()
                if formula_for_save is None:
                    formula_for_save = FeedFormula(
                        tenant_id=tenant_id,
                        name=formula_name,
                        created_by=user_id,
                    )
                    db.session.add(formula_for_save)
                db.session.flush()
                FormulaIngredient.query.filter_by(
                    tenant_id=tenant_id,
                    formula_id=formula_for_save.id,
                ).delete(synchronize_session=False)

            batch = FeedBatch(
                tenant_id=tenant_id,
                formula_id=formula_for_save.id if formula_for_save else None,
                # Airtight attribution when the planner passed a recipe id via
                # formulaId; stays NULL otherwise so legacy rows keep using
                # signature-based inference.
                recipe_id=planner_recipe.id if planner_recipe is not None else None,
                batch_name=batch_name,
                total_weight=total_weight,
                total_cost=total_cost,
                cost_per_kg=cost_per_kg,
                status='ACTIVE',
                created_by=user_id,
                posted_at=datetime.now(timezone.utc),
            )
            db.session.add(batch)
            db.session.flush()

            created_rows = []
            for resolved_entry in resolved_entries:
                ingredient = resolved_entry['ingredient']
                inventory_item = resolved_entry['inventory_item']
                weight = resolved_entry['weight']
                ingredient.stock_quantity = Decimal(str(ingredient.stock_quantity)) - weight
                if inventory_item is not None:
                    inventory_item.current_qty = Decimal(str(inventory_item.current_qty)) - weight
                    db.session.add(InventoryTransaction(
                        item_id=inventory_item.id,
                        transaction_type='OUT',
                        quantity=weight,
                        unit_cost=resolved_entry['locked_cost_per_kg'],
                        reason_code='FEED_BATCH_MIX',
                        notes=f'Used in feed batch #{batch.id}: {batch.batch_name}',
                        logged_by=user_id,
                        transaction_date=datetime.now(timezone.utc),
                    ))

                batch_ingredient = BatchIngredient(
                    tenant_id=tenant_id,
                    batch_id=batch.id,
                    ingredient_id=ingredient.id,
                    weight=weight,
                    percentage=resolved_entry['percentage'],
                    locked_cost_per_kg=resolved_entry['locked_cost_per_kg'],
                    locked_protein_grams_per_kg=resolved_entry['locked_protein_grams_per_kg'],
                )
                db.session.add(batch_ingredient)

                if is_saved_as_template and formula_for_save is not None:
                    formula_ingredient = FormulaIngredient(
                        tenant_id=tenant_id,
                        formula_id=formula_for_save.id,
                        ingredient_id=ingredient.id,
                        default_weight=weight,
                    )
                    db.session.add(formula_ingredient)

                created_rows.append({
                    'ingredientId': ingredient.id,
                    'ingredientName': ingredient.name,
                    'weight': float(weight),
                    'lockedCostPerKg': float(resolved_entry['locked_cost_per_kg']),
                    'remainingStock': float(ingredient.stock_quantity),
                })

            db.session.commit()

            total_protein_grams = sum(
                entry['weight'] * entry['locked_protein_grams_per_kg']
                for entry in resolved_entries
            )
            protein_percentage = (
                total_protein_grams / (total_weight * Decimal('10'))
                if total_weight > 0 else Decimal('0')
            )

            response_payload = {
                'message': 'Batch processed and saved successfully.',
                'batchId': batch.id,
                'formulaId': batch.formula_id,
                'status': batch.status,
                'totalWeight': float(batch.total_weight),
                'totalCost': float(batch.total_cost),
                'costPerKg': float(batch.cost_per_kg),
                'totalProteinGrams': round(float(total_protein_grams), 2),
                'proteinPercentage': round(float(protein_percentage), 4),
                'inventory': created_rows,
            }

            if planner_recipe is not None:
                response_payload['warning'] = (
                    'formulaId referenced a planner recipe and was accepted for compatibility; '
                    'batch is not linked to FeedFormula.'
                )
                response_payload['plannerRecipeId'] = planner_recipe.id

            return jsonify(response_payload), 201
        except InsufficientStockError as exc:
            db.session.rollback()
            return jsonify({
                'error': str(exc),
                'code': 'INSUFFICIENT_STOCK',
                'shortages': exc.shortages,
                'maximumFeasibleBatchWeight': float(exc.max_batch_weight.quantize(Decimal('0.001'))),
            }), 400
        except ValueError as exc:
            db.session.rollback()
            return jsonify({'error': str(exc)}), 400
        except IntegrityError as exc:
            db.session.rollback()
            current_app.logger.exception('Batch processing integrity failure: %s', exc)
            return jsonify({'error': 'Batch data conflicts with an existing tenant record.'}), 409
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception('Batch processing DB failure: %s', exc)
            return jsonify({'error': 'Database transaction failed while processing batch.'}), 500

    @staticmethod
    def record_consumption_event(*, tenant_id: int, batch_id: int, user_id: int | None, data: dict):
        try:
            consumed_weight = Decimal(str(data.get('consumedWeight')))
        except (TypeError, InvalidOperation):
            return jsonify({'error': 'consumedWeight must be a valid number.'}), 400

        if consumed_weight <= 0:
            return jsonify({'error': 'consumedWeight must be greater than zero.'}), 400

        consumed_on_raw = data.get('consumedOn')
        if consumed_on_raw:
            try:
                consumed_on = datetime.fromisoformat(str(consumed_on_raw)).date()
            except ValueError:
                return jsonify({'error': 'consumedOn must be a valid ISO date (YYYY-MM-DD).'}), 400
        else:
            consumed_on = datetime.now(timezone.utc).date()

        try:
            feeding_group = FeedingGroupRecipePolicyService.normalize_feeding_group(
                data.get('feeding_group')
            )
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        if feeding_group is None:
            return jsonify({'error': 'feeding_group is required for every consumption event.'}), 400

        try:
            batch_query = FeedBatch.query.filter_by(id=batch_id, tenant_id=tenant_id)
            if db.engine.dialect.name == 'postgresql':
                batch_query = batch_query.with_for_update()
            batch = batch_query.first()
            if not batch:
                return jsonify({'error': 'Batch not found for this tenant.'}), 404

            if batch.status == 'VOIDED':
                return jsonify({'error': 'Cannot consume a voided batch.'}), 400

            existing_consumed = (
                db.session.query(func.coalesce(func.sum(FeedBatchConsumptionEvent.consumed_weight), 0))
                .filter(
                    FeedBatchConsumptionEvent.tenant_id == tenant_id,
                    FeedBatchConsumptionEvent.batch_id == batch.id,
                )
                .scalar()
            )
            existing_consumed = Decimal(str(existing_consumed or 0))
            remaining_weight = max(Decimal('0'), Decimal(str(batch.total_weight)) - existing_consumed)
            if batch.status == 'DEPLETED' or remaining_weight <= 0:
                return jsonify({'error': 'This batch is already depleted.'}), 400
            if consumed_weight > remaining_weight:
                return jsonify({
                    'error': (
                        f'Consumed weight cannot exceed the remaining batch weight of '
                        f'{remaining_weight} kg.'
                    )
                }), 400

            event = FeedBatchConsumptionEvent(
                tenant_id=tenant_id,
                batch_id=batch.id,
                feeding_group=feeding_group,
                consumed_weight=consumed_weight,
                consumed_on=consumed_on,
                created_by=user_id,
            )
            db.session.add(event)
            db.session.flush()

            total_consumed = existing_consumed + consumed_weight

            if total_consumed >= Decimal(str(batch.total_weight)):
                batch.status = 'DEPLETED'
                if batch.depleted_on is None or consumed_on > batch.depleted_on:
                    batch.depleted_on = consumed_on

            db.session.commit()

            pace = NutritionService._batch_consumption_pace(
                batch, tenant_id=tenant_id, total_consumed=total_consumed
            )

            return jsonify({
                'message': 'Consumption event recorded successfully.',
                'batchId': batch.id,
                'batchStatus': batch.status,
                'feedingGroup': feeding_group,
                'consumedWeight': float(consumed_weight),
                'totalConsumedWeight': float(total_consumed),
                'remainingWeight': float(max(Decimal('0'), Decimal(str(batch.total_weight)) - total_consumed)),
                'depletedOn': str(batch.depleted_on) if batch.depleted_on else None,
                **pace,
            }), 200
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify({'error': 'Database transaction failed while recording consumption event.'}), 500

    @staticmethod
    def get_feed_cost_efficiency(*, tenant_id: int, saleable_only: bool = False):
        batches = (
            FeedBatch.query.filter(
                FeedBatch.tenant_id == tenant_id,
                FeedBatch.status.in_(['ACTIVE', 'DEPLETED']),
            )
            .order_by(FeedBatch.mixed_on.desc(), FeedBatch.id.desc())
            .all()
        )

        results = []

        for batch in batches:
            start_date, end_date, start_dt, end_dt = NutritionService._lag_window_for_batch(batch)

            milk_query = db.session.query(func.coalesce(func.sum(MilkLog.amount_liters), 0)).filter(
                    MilkLog.tenant_id == tenant_id,
                    MilkLog.timestamp >= start_dt,
                    MilkLog.timestamp <= end_dt,
                )
            if saleable_only:
                milk_query = milk_query.filter(MilkLog.is_saleable.is_(True))

            total_milk_liters = milk_query.scalar()
            total_milk_liters = Decimal(str(total_milk_liters or 0))

            if total_milk_liters > 0:
                cost_per_liter = (Decimal(str(batch.total_cost)) / total_milk_liters).quantize(Decimal('0.01'))
                cost_per_liter_value = float(cost_per_liter)
            else:
                cost_per_liter_value = 0.0

            ingredient_breakdown = NutritionService._serialize_batch_ingredient_breakdown(batch)

            # Compute overall batch protein % from snapshotted ingredient values.
            total_weight_kg = Decimal(str(batch.total_weight))
            total_protein_grams = sum(
                Decimal(str(entry.get('protein_grams_per_kg', 0))) * Decimal(str(entry['weight']))
                for entry in ingredient_breakdown
            )
            protein_percentage = (
                float((total_protein_grams / (total_weight_kg * 1000)) * 100)
                if total_weight_kg > 0 else 0.0
            )
            pace = NutritionService._batch_consumption_pace(batch, tenant_id=tenant_id)

            results.append({
                'batchId': batch.id,
                'batchName': batch.batch_name,
                'mixedOn': str(batch.mixed_on),
                'depletedOn': str(batch.depleted_on) if batch.depleted_on else None,
                'lagWindowStart': str(start_date),
                'lagWindowEnd': str(end_date),
                'totalBatchCost': float(batch.total_cost),
                'totalMilkLiters': float(total_milk_liters),
                'costPerLiter': cost_per_liter_value,
                'proteinPercentage': round(protein_percentage, 2),
                'ingredient_breakdown': ingredient_breakdown,
                'ingredients': ingredient_breakdown,
                'totalConsumedWeight': pace['total_consumed_kg'],
                'consumedWeight': pace['total_consumed_kg'],
                'remainingWeight': pace['remaining_kg'],
                'dailyFeedingRateKg': pace['dailyFeedingRateKg'],
                'daysUntilEmpty': pace['daysUntilEmpty'],
                'rateBasis': pace['rate_basis'],
            })

        return jsonify({'saleableOnly': saleable_only, 'rows': results}), 200

    @staticmethod
    def get_recipe_performance(*, tenant_id: int) -> dict:
        """Aggregate per-recipe feeding performance across the batches that
        were mixed from each recipe.

        Batches never reference planner recipes at the DB level (FeedBatch
        .formula_id is a composite FK to the feed_formulas template table, not
        feed_recipes), so the link is established by matching each batch's
        ingredient composition against each recipe's inclusion percentages.
        Because a recipe and a batch created from it resolve ingredient names
        differently (recipes -> inventory_items, batches -> ingredients), both
        sides are normalized to lowercase ingredient NAMES keyed by rounded
        percentage, and a batch is attributed to the recipe whose name->
        percentage signature it matches exactly.

        For each attributed batch, milk produced during the batch's lag window
        (mixed_on .. depleted_on/now + 3 days) is summed, then per-recipe
        metrics are derived:
          - avg_daily_yield_liters: total milk / total feeding days
          - cost_per_liter: total batch cost / total milk (weighted)
        Returns {recipe_id: performance-dict} for merging into recipe payloads.
        """
        from app.models.supply import RecipeIngredient

        today = datetime.now(timezone.utc).date()

        recipes = FeedRecipe.query.filter_by(tenant_id=tenant_id).all()
        recipe_signature = {}  # recipe_id -> frozenset of (name, rounded_pct)
        for recipe in recipes:
            sig = set()
            for ri in recipe.ingredients or []:
                name = ri.inventory_item.name if ri.inventory_item else None
                if name:
                    sig.add((name.strip().lower(), round(float(ri.inclusion_percentage or 0), 2)))
            if sig:
                recipe_signature[recipe.id] = frozenset(sig)

        batches = (
            FeedBatch.query.filter(
                FeedBatch.tenant_id == tenant_id,
                FeedBatch.status.in_(['ACTIVE', 'DEPLETED']),
            )
            .order_by(FeedBatch.mixed_on.asc())
            .all()
        )

        perf: dict = {}
        for batch in batches:
            # Prefer the direct recipe link set at batch creation; fall back to
            # ingredient-signature inference for legacy rows (recipe_id NULL).
            recipe_id = getattr(batch, 'recipe_id', None)
            if recipe_id is None:
                batch_sig = frozenset(
                    (
                        (entry.ingredient.name.strip().lower() if entry.ingredient and entry.ingredient.name else ''),
                        round(float(entry.percentage or 0), 2),
                    )
                    for entry in (batch.ingredients or [])
                    if entry.ingredient is not None and entry.ingredient.name
                )
                if not batch_sig:
                    continue
                # Prefer the most recently created matching recipe so a new batch
                # is attributed to the current formulation, not a stale duplicate.
                recipe_id = next(
                    (rid for rid, sig in sorted(recipe_signature.items(), reverse=True) if sig == batch_sig),
                    None,
                )
            if recipe_id is None:
                continue
            start_date, end_date, start_dt, end_dt = NutritionService._lag_window_for_batch(batch)
            total_milk_liters = (
                db.session.query(func.coalesce(func.sum(MilkLog.amount_liters), 0))
                .filter(
                    MilkLog.tenant_id == tenant_id,
                    MilkLog.timestamp >= start_dt,
                    MilkLog.timestamp <= end_dt,
                )
                .scalar()
            )
            total_milk_liters = Decimal(str(total_milk_liters or 0))

            feeding_end = batch.depleted_on or today
            if feeding_end < batch.mixed_on:
                feeding_end = batch.mixed_on
            feeding_days = max(1, (feeding_end - batch.mixed_on).days + 1)

            entry = perf.setdefault(recipe_id, {
                'batch_count': 0,
                'total_milk_liters': Decimal('0'),
                'total_cost': Decimal('0'),
                'feeding_days': 0,
                'last_fed_on': None,
            })
            entry['batch_count'] += 1
            entry['total_milk_liters'] += total_milk_liters
            entry['total_cost'] += Decimal(str(batch.total_cost or 0))
            entry['feeding_days'] += feeding_days
            if entry['last_fed_on'] is None or feeding_end > entry['last_fed_on']:
                entry['last_fed_on'] = feeding_end

        result = {}
        for recipe_id, entry in perf.items():
            total_milk = entry['total_milk_liters']
            days = entry['feeding_days']
            avg_daily_yield = float(total_milk) / days if days > 0 else 0.0
            cost_per_liter = (
                float(entry['total_cost'] / total_milk) if total_milk > 0 else None
            )
            result[recipe_id] = {
                'batch_count': entry['batch_count'],
                'total_milk_liters': round(float(total_milk), 2),
                'avg_daily_yield_liters': round(avg_daily_yield, 2),
                'avgDailyYieldLiters': round(avg_daily_yield, 2),
                'cost_per_liter': round(cost_per_liter, 2) if cost_per_liter is not None else None,
                'costPerLiter': round(cost_per_liter, 2) if cost_per_liter is not None else None,
                'last_fed_on': str(entry['last_fed_on']) if entry['last_fed_on'] else None,
                'lastFedOn': str(entry['last_fed_on']) if entry['last_fed_on'] else None,
            }
        return result

    @staticmethod
    def get_feed_cost_by_group(*, tenant_id: int):
        """Aggregate feed cost by feeding_group for recipe-linked batches."""
        rows = (
            db.session.query(
                FeedRecipe.feeding_group,
                func.count(FeedBatch.id),
                func.coalesce(func.sum(FeedBatch.total_cost), 0),
                func.coalesce(func.sum(FeedBatch.total_weight), 0),
            )
            .join(
                FeedBatch,
                (FeedBatch.recipe_id == FeedRecipe.id) & (FeedBatch.tenant_id == FeedRecipe.tenant_id),
            )
            .filter(
                FeedBatch.tenant_id == tenant_id,
                FeedRecipe.tenant_id == tenant_id,
                FeedRecipe.feeding_group.isnot(None),
            )
            .group_by(FeedRecipe.feeding_group)
            .all()
        )

        result_rows = []
        grand_total_feed_cost = Decimal('0')

        for feeding_group, batch_count, total_cost, total_weight in rows:
            cost_value = Decimal(str(total_cost or 0))
            weight_value = Decimal(str(total_weight or 0))
            grand_total_feed_cost += cost_value
            average_cost_per_kg = (cost_value / weight_value) if weight_value > 0 else Decimal('0')

            result_rows.append({
                'feeding_group': feeding_group,
                'batch_count': int(batch_count or 0),
                'total_feed_cost': round(float(cost_value), 2),
                'total_feed_weight_kg': round(float(weight_value), 3),
                'average_cost_per_kg': round(float(average_cost_per_kg), 4),
            })

        return jsonify({
            'rows': result_rows,
            'total_groups': len(result_rows),
            'grand_total_feed_cost': round(float(grand_total_feed_cost), 2),
        }), 200

    @staticmethod
    def get_weekly_active_batch_roi_trend(*, tenant_id: int, saleable_only: bool = False):
        active_batches = (
            FeedBatch.query.filter(
                FeedBatch.tenant_id == tenant_id,
                FeedBatch.status == 'ACTIVE',
            )
            .order_by(FeedBatch.mixed_on.asc(), FeedBatch.id.asc())
            .all()
        )

        grouped: dict[str, dict] = {}

        for batch in active_batches:
            week_start = batch.mixed_on - timedelta(days=batch.mixed_on.weekday())
            week_key = str(week_start)
            if week_key not in grouped:
                grouped[week_key] = {
                    'weekStart': week_key,
                    'activeBatches': 0,
                    'totalFeedCost': Decimal('0'),
                    'totalMilkLiters': Decimal('0'),
                }

            start_date, _, start_dt, end_dt = NutritionService._lag_window_for_batch(batch)
            milk_query = db.session.query(func.coalesce(func.sum(MilkLog.amount_liters), 0)).filter(
                MilkLog.tenant_id == tenant_id,
                MilkLog.timestamp >= start_dt,
                MilkLog.timestamp <= end_dt,
            )
            if saleable_only:
                milk_query = milk_query.filter(MilkLog.is_saleable.is_(True))

            milk_liters = Decimal(str(milk_query.scalar() or 0))

            grouped[week_key]['activeBatches'] += 1
            grouped[week_key]['totalFeedCost'] += Decimal(str(batch.total_cost))
            grouped[week_key]['totalMilkLiters'] += milk_liters

        rows = []
        for week_key in sorted(grouped.keys()):
            entry = grouped[week_key]
            total_cost = entry['totalFeedCost']
            total_milk = entry['totalMilkLiters']

            if total_milk > 0:
                feed_cost_per_liter = (total_cost / total_milk).quantize(Decimal('0.01'))
            else:
                feed_cost_per_liter = Decimal('0.00')

            if total_cost > 0:
                roi_liters_per_kes = (total_milk / total_cost).quantize(Decimal('0.0001'))
            else:
                roi_liters_per_kes = Decimal('0.0000')

            rows.append({
                'weekStart': week_key,
                'activeBatches': entry['activeBatches'],
                'totalFeedCost': float(total_cost),
                'totalMilkLiters': float(total_milk),
                'feedCostPerLiter': float(feed_cost_per_liter),
                'roiLitersPerKes': float(roi_liters_per_kes),
            })

        return jsonify({'saleableOnly': saleable_only, 'rows': rows}), 200

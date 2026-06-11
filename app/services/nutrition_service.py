from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import jsonify
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func

from app import db
from app.models.supply import (
    BatchIngredient,
    FeedBatch,
    FeedBatchConsumptionEvent,
    FeedFormula,
    FormulaIngredient,
    Ingredient,
    MilkLog,
)


class NutritionService:
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
    def process_and_save_batch(*, tenant_id: int, user_id: int | None, data: dict):
        batch_name = (data.get('batchName') or 'Custom Quick Mix').strip()
        is_saved_as_template = bool(data.get('isSavedAsTemplate', False))
        formula_name = (data.get('formulaName') or batch_name).strip()
        formula_id = data.get('formulaId')
        ingredients_payload = data.get('ingredients') or []

        if not ingredients_payload:
            return jsonify({'error': 'At least one ingredient is required.'}), 400

        try:
            total_weight = Decimal(str(data.get('totalWeight')))
            total_cost = Decimal(str(data.get('totalCost')))
            cost_per_kg = Decimal(str(data.get('costPerKg')))
        except (TypeError, InvalidOperation):
            return jsonify({'error': 'totalWeight, totalCost, and costPerKg must be valid numbers.'}), 400

        if total_weight <= 0 or total_cost < 0 or cost_per_kg < 0:
            return jsonify({'error': 'Invalid totals. Ensure totalWeight > 0 and costs are non-negative.'}), 400

        try:
            formula = None
            if formula_id is not None:
                formula = (
                    FeedFormula.query.filter_by(id=formula_id, tenant_id=tenant_id)
                    .first()
                )
                if not formula:
                    return jsonify({'error': 'Formula not found for this tenant.'}), 404

            batch = FeedBatch(
                tenant_id=tenant_id,
                formula_id=formula.id if formula else None,
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

            formula_for_save = formula
            if is_saved_as_template and formula_for_save is None:
                formula_for_save = FeedFormula(
                    tenant_id=tenant_id,
                    name=formula_name,
                    created_by=user_id,
                )
                db.session.add(formula_for_save)
                db.session.flush()
                batch.formula_id = formula_for_save.id

            created_rows = []
            for entry in ingredients_payload:
                ingredient_id = entry.get('ingredientId')
                try:
                    weight = Decimal(str(entry.get('weight')))
                except (TypeError, InvalidOperation):
                    raise ValueError('Each ingredient requires a valid weight.')

                if weight <= 0:
                    raise ValueError('Ingredient weight must be greater than zero.')

                ingredient_query = Ingredient.query.filter_by(id=ingredient_id, tenant_id=tenant_id)
                if db.engine.dialect.name == 'postgresql':
                    ingredient_query = ingredient_query.with_for_update()
                ingredient = ingredient_query.first()

                if not ingredient:
                    raise ValueError(f'Ingredient {ingredient_id} not found for this tenant.')

                if ingredient.stock_quantity < weight:
                    raise ValueError(
                        f'Insufficient stock for {ingredient.name}. Available: {ingredient.stock_quantity}, required: {weight}.'
                    )

                ingredient.stock_quantity = Decimal(str(ingredient.stock_quantity)) - weight

                locked_cost = entry.get('lockedCostPerKg', ingredient.current_cost_per_kg)
                try:
                    locked_cost_per_kg = Decimal(str(locked_cost))
                except (TypeError, InvalidOperation):
                    raise ValueError('lockedCostPerKg must be a valid number when provided.')

                percentage = entry.get('percentage')
                if percentage is None:
                    percentage_value = (weight / total_weight) * Decimal('100')
                else:
                    try:
                        percentage_value = Decimal(str(percentage))
                    except (TypeError, InvalidOperation):
                        raise ValueError('percentage must be a valid number when provided.')

                batch_ingredient = BatchIngredient(
                    tenant_id=tenant_id,
                    batch_id=batch.id,
                    ingredient_id=ingredient.id,
                    weight=weight,
                    percentage=percentage_value,
                    locked_cost_per_kg=locked_cost_per_kg,
                )
                db.session.add(batch_ingredient)

                if formula_for_save is not None:
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
                    'remainingStock': float(ingredient.stock_quantity),
                })

            db.session.commit()

            return jsonify({
                'message': 'Batch processed and saved successfully.',
                'batchId': batch.id,
                'formulaId': batch.formula_id,
                'status': batch.status,
                'inventory': created_rows,
            }), 201
        except ValueError as exc:
            db.session.rollback()
            return jsonify({'error': str(exc)}), 400
        except SQLAlchemyError:
            db.session.rollback()
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
            batch = FeedBatch.query.filter_by(id=batch_id, tenant_id=tenant_id).first()
            if not batch:
                return jsonify({'error': 'Batch not found for this tenant.'}), 404

            if batch.status == 'VOIDED':
                return jsonify({'error': 'Cannot consume a voided batch.'}), 400

            event = FeedBatchConsumptionEvent(
                tenant_id=tenant_id,
                batch_id=batch.id,
                consumed_weight=consumed_weight,
                consumed_on=consumed_on,
                created_by=user_id,
            )
            db.session.add(event)
            db.session.flush()

            total_consumed = (
                db.session.query(func.coalesce(func.sum(FeedBatchConsumptionEvent.consumed_weight), 0))
                .filter(
                    FeedBatchConsumptionEvent.tenant_id == tenant_id,
                    FeedBatchConsumptionEvent.batch_id == batch.id,
                )
                .scalar()
            )
            total_consumed = Decimal(str(total_consumed or 0))

            if total_consumed >= Decimal(str(batch.total_weight)):
                batch.status = 'DEPLETED'
                if batch.depleted_on is None or consumed_on > batch.depleted_on:
                    batch.depleted_on = consumed_on

            db.session.commit()

            return jsonify({
                'message': 'Consumption event recorded successfully.',
                'batchId': batch.id,
                'batchStatus': batch.status,
                'consumedWeight': float(consumed_weight),
                'totalConsumedWeight': float(total_consumed),
                'remainingWeight': float(max(Decimal('0'), Decimal(str(batch.total_weight)) - total_consumed)),
                'depletedOn': str(batch.depleted_on) if batch.depleted_on else None,
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
            })

        return jsonify({'saleableOnly': saleable_only, 'rows': results}), 200

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

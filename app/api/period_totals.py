"""Period totals endpoints (contract: docs/contracts/period-totals.md).

Each route parses its query, calls one service method and returns the
serialized result. Business rules live in the services; queries in the repositories.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.models.user import Role
from app.schemas.ledger_filters import LedgerFilters
from app.schemas.period_query import GroupLevelsQuery, PeriodQuery
from app.schemas.production_filters import ProductionFilters
from app.services.period_totals_serializer import LedgerTotalsSerializer, ProductionTotalsSerializer
from app.services.period_totals_service import LedgerTotalsService, ProductionTotalsService
from app.services.request_scope import FarmScope
from app.utils.decorators import role_required
from app.utils.error_envelope import register_error_envelope
from app.utils.farm_time import farm_today

period_totals_bp = Blueprint('period_totals', __name__)
register_error_envelope(period_totals_bp)

_ledger_service = LedgerTotalsService()
_production_service = ProductionTotalsService()
_ledger_serializer = LedgerTotalsSerializer()
_production_serializer = ProductionTotalsSerializer()


@period_totals_bp.route('/api/ledger/summary', methods=['GET'])
@period_totals_bp.route('/api/finance/ledger/summary', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def ledger_summary():
    scope = FarmScope.from_request()
    query = PeriodQuery.from_args(request.args, today=farm_today())
    filters = LedgerFilters.from_args(request.args)
    return jsonify(_ledger_serializer.summary(_ledger_service.summary(scope, query, filters))), 200


@period_totals_bp.route('/api/ledger/group-totals', methods=['GET'])
@period_totals_bp.route('/api/finance/ledger/group-totals', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def ledger_group_totals():
    scope = FarmScope.from_request()
    levels = GroupLevelsQuery.from_args(request.args)
    filters = LedgerFilters.from_args(request.args)
    return jsonify(_ledger_serializer.groups(_ledger_service.group_totals(scope, filters, levels.levels))), 200


def production_period_summary():
    """``GET /api/production/summary?period=...``; dispatched from the legacy summary route."""
    scope = FarmScope.from_request()
    query = PeriodQuery.from_args(request.args, today=farm_today())
    filters = ProductionFilters.from_args(request.args)
    return jsonify(_production_serializer.summary(_production_service.summary(scope, query, filters))), 200


@period_totals_bp.route('/api/production/group-totals', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def production_group_totals():
    scope = FarmScope.from_request()
    levels = GroupLevelsQuery.from_args(request.args)
    filters = ProductionFilters.from_args(request.args)
    return jsonify(_production_serializer.groups(_production_service.group_totals(scope, filters, levels.levels))), 200

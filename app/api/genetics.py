"""
Genetics API — endpoints for genetic profiles, trait scores, and projections.

URL prefix: /api/v1/genetics
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required

from app.models.genetics import GeneticProfile, GeneticTraitScore
from app.models.user import Role
from app.repositories.cow_repo import CowRepository
from app.repositories.genetic_repo import GeneticRepository
from app.services.genetic_projection_service import GeneticProjectionService
from app.services.genetic_reliability_service import GeneticReliabilityService
from app.tasks.genetic_tasks import recalculate_genetic_reliability
from app.utils.decorators import require_tenant_context, role_required
from app.utils.jwt_payload import parse_public_int_id

genetics_bp = Blueprint('genetics', __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tenant_id() -> int | None:
    claims = get_jwt()
    raw = claims.get('tenant_id')
    if not raw:
        return None
    try:
        return parse_public_int_id(raw, 'tenant_')
    except (TypeError, ValueError):
        return None


def _bad_tenant():
    return jsonify({'error': 'Missing or invalid tenant in token.'}), 400


# ---------------------------------------------------------------------------
# GET /api/v1/genetics/traits
# List all trait definitions — used to build forms and radar chart axes.
# ---------------------------------------------------------------------------

@genetics_bp.get('/traits')
@jwt_required()
@require_tenant_context
def list_trait_definitions():
    """Return the full set of genetic trait definitions grouped by category."""
    definitions = GeneticRepository.get_all_trait_definitions()

    grouped: dict[str, list] = {}
    for td in definitions:
        grouped.setdefault(td.category, []).append(td.to_dict())

    return jsonify({'categories': grouped}), 200


# ---------------------------------------------------------------------------
# GET /api/v1/genetics/animals/<cow_id>/profile
# Fetch an animal's full genetic profile with all trait scores.
# ---------------------------------------------------------------------------

@genetics_bp.get('/animals/<int:cow_id>/profile')
@jwt_required()
@require_tenant_context
def get_animal_profile(cow_id: int):
    tenant_id = _tenant_id()
    if tenant_id is None:
        return _bad_tenant()

    cow = CowRepository.get_by_id(cow_id, tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404

    profile = GeneticRepository.get_profile_by_cow(cow_id, tenant_id)
    if not profile:
        return jsonify({'profile': None}), 200

    return jsonify({'profile': profile.to_dict()}), 200


# ---------------------------------------------------------------------------
# POST /api/v1/genetics/animals/<cow_id>/profile
# Create or fully replace the genetic profile for an existing (foundation)
# animal.  Used when a genomic test result arrives for a cow already on farm.
#
# Body:
# {
#   "source": "GENOMIC_TEST" | "MANUAL",
#   "trait_scores": [
#     {"trait_name": "milk_volume", "value": 28.5},
#     {"trait_name": "fat_percentage", "value": 4.1},
#     ...
#   ]
# }
# ---------------------------------------------------------------------------

@genetics_bp.post('/animals/<int:cow_id>/profile')
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER)
def upsert_animal_profile(cow_id: int):
    tenant_id = _tenant_id()
    if tenant_id is None:
        return _bad_tenant()

    cow = CowRepository.get_by_id(cow_id, tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404

    data = request.get_json(silent=True) or {}
    source = data.get('source', GeneticProfile.SOURCE_MANUAL)
    if source not in (GeneticProfile.SOURCE_GENOMIC_TEST, GeneticProfile.SOURCE_MANUAL):
        return jsonify({'error': f"source must be 'GENOMIC_TEST' or 'MANUAL'."}), 422

    raw_scores: list = data.get('trait_scores', [])
    if not raw_scores:
        return jsonify({'error': 'trait_scores is required and must not be empty.'}), 422

    profile = GeneticRepository.get_or_create_profile(cow_id, tenant_id, source)
    profile.source = source

    errors = []
    saved = 0
    for entry in raw_scores:
        trait_name = entry.get('trait_name', '').strip()
        value = entry.get('value')

        if not trait_name:
            errors.append('Each trait_score entry requires a trait_name.')
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            errors.append(f"Invalid value for trait '{trait_name}'.")
            continue

        trait_def = GeneticRepository.get_trait_definition_by_name(trait_name)
        if trait_def is None:
            errors.append(f"Unknown trait name: '{trait_name}'.")
            continue

        GeneticRepository.upsert_trait_score(
            profile_id=profile.id,
            trait_definition_id=trait_def.id,
            value=value,
            reliability=90 if source == GeneticProfile.SOURCE_GENOMIC_TEST else 50,
            scored_source=GeneticTraitScore.SCORED_SOURCE_USER,
        )
        saved += 1

    if errors and saved == 0:
        from app import db
        db.session.rollback()
        return jsonify({'errors': errors}), 422

    from app import db
    db.session.commit()

    response = {'profile': profile.to_dict(), 'saved': saved}
    if errors:
        response['warnings'] = errors

    return jsonify(response), 201


# ---------------------------------------------------------------------------
# POST /api/v1/genetics/animals/<calf_cow_id>/project
# System-generate a calf's projected scores from dam + sire PTA data.
# Called by the calving workflow once a calf is registered.
#
# Body:
# {
#   "dam_cow_id": 42,
#   "sire_pta_scores": {
#     "milk_volume": 320.5,
#     "fat_percentage": 0.12
#   }
# }
# ---------------------------------------------------------------------------

@genetics_bp.post('/animals/<int:calf_cow_id>/project')
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER)
def project_calf_scores(calf_cow_id: int):
    tenant_id = _tenant_id()
    if tenant_id is None:
        return _bad_tenant()

    calf = CowRepository.get_by_id(calf_cow_id, tenant_id)
    if not calf:
        return jsonify({'error': 'Calf animal not found.'}), 404

    data = request.get_json(silent=True) or {}
    dam_cow_id = data.get('dam_cow_id')
    sire_pta_scores = data.get('sire_pta_scores')

    if not dam_cow_id:
        return jsonify({'error': 'dam_cow_id is required.'}), 422
    if not isinstance(sire_pta_scores, dict) or not sire_pta_scores:
        return jsonify({'error': 'sire_pta_scores must be a non-empty object mapping trait_name -> value.'}), 422

    try:
        dam_cow_id = int(dam_cow_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'dam_cow_id must be an integer.'}), 422

    dam = CowRepository.get_by_id(dam_cow_id, tenant_id)
    if not dam:
        return jsonify({'error': 'Dam animal not found.'}), 404

    try:
        profile = GeneticProjectionService.project_calf_scores(
            calf_cow_id=calf_cow_id,
            dam_cow_id=dam_cow_id,
            sire_pta_scores=sire_pta_scores,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 422

    return jsonify({'profile': profile.to_dict()}), 201


# ---------------------------------------------------------------------------
# POST /api/v1/genetics/animals/<cow_id>/recalculate-reliability
# Manually trigger a reliability recalculation for a specific cow.
# Fires synchronously so the caller gets the updated value immediately.
# (The Celery task is the primary async path; this is the manual override.)
# ---------------------------------------------------------------------------

@genetics_bp.post('/animals/<int:cow_id>/recalculate-reliability')
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER)
def recalculate_reliability(cow_id: int):
    tenant_id = _tenant_id()
    if tenant_id is None:
        return _bad_tenant()

    cow = CowRepository.get_by_id(cow_id, tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404

    new_reliability = GeneticReliabilityService.recalculate(cow_id, tenant_id)
    return jsonify({'cow_id': cow_id, 'reliability': new_reliability}), 200


# ---------------------------------------------------------------------------
# POST /api/v1/genetics/animals/<cow_id>/recalculate-reliability/async
# Same as above but dispatches to Celery and returns immediately.
# Useful for bulk triggers from an admin dashboard.
# ---------------------------------------------------------------------------

@genetics_bp.post('/animals/<int:cow_id>/recalculate-reliability/async')
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER)
def recalculate_reliability_async(cow_id: int):
    tenant_id = _tenant_id()
    if tenant_id is None:
        return _bad_tenant()

    cow = CowRepository.get_by_id(cow_id, tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404

    task = recalculate_genetic_reliability.delay(cow_id=cow_id, tenant_id=tenant_id)
    return jsonify({'queued': True, 'task_id': task.id, 'cow_id': cow_id}), 202

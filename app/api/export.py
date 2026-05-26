from __future__ import annotations

import io

from flask import Blueprint, jsonify, g, render_template, send_file
from flask_jwt_extended import jwt_required
from weasyprint import HTML

from app.models.user import Role
from app.services.export_service import AnimalPassportService
from app.utils.decorators import require_tenant_context, role_required
from app.utils.jwt_payload import parse_public_int_id

export_bp = Blueprint('export', __name__)


def _get_tenant_id_from_context():
    tenant_public_id = getattr(g, 'tenant_id', None)
    if not tenant_public_id:
        return None

    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None


@export_bp.route('/api/v1/export/animal/<int:animal_id>/pdf', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.VET)
def export_animal_passport(animal_id):
    tenant_id = _get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400

    passport_context = AnimalPassportService.build_passport_context(animal_id=animal_id, tenant_id=tenant_id)
    if passport_context is None:
        return jsonify({"error": "Animal not found."}), 404

    html_string = render_template('pdf/animal_passport.html', **passport_context)
    pdf_bytes = HTML(string=html_string).write_pdf()

    animal = passport_context['animal']
    filename = f"Jivu_Passport_{animal['tag_number']}.pdf"

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename,
    )
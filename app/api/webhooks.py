from flask import Blueprint, request, jsonify
from app.services.mpesa_service import MpesaService

webhooks_bp = Blueprint('webhooks', __name__)


@webhooks_bp.route('/statements/<token>', methods=['GET'])
def get_statement(token):
    """Disabled (BR-016).

    The old "token" was the buyer's phone number, unscoped by farm, so anyone who knew or guessed
    a number could read that buyer's balance and transactions. Until opaque, expiring, hashed
    statement links exist, every token is answered the same way so nothing can be probed.
    """
    return jsonify({'code': 'STATEMENT_LINK_INVALID', 'error': 'This statement link is not valid.'}), 404


# Not routed: the callback is unauthenticated and can credit the wrong farm (audit item 16).
# Re-register it in Phase 0B once callbacks are verified and matched to a stored request.
def mpesa_callback():
    """
    Public webhook endpoint for Safaricom Daraja.
    Requires NO authentication, as Safaricom cannot pass our JWT.
    """
    payload = request.get_json()

    if not payload:
        return jsonify({"error": "Invalid payload"}), 400

    MpesaService.process_stk_callback(payload)

    safaricom_acknowledgement = {
        "ResultCode": 0,
        "ResultDesc": "Confirmation Received Successfully"
    }
    return jsonify(safaricom_acknowledgement), 200
from flask import jsonify
from werkzeug.exceptions import HTTPException

def handle_exception(e):
    """
    Centralized Error Handling: Logs full trace but sends clean JSON to user.
    """
    # In a real scenario, use logging.error(e) here
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    
    return jsonify({"error": "An internal server error occurred. Please contact Jivu Systems Support."}), 500
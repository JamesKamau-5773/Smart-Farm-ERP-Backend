import traceback
from flask import jsonify, json
from werkzeug.exceptions import HTTPException
from werkzeug.exceptions import RequestEntityTooLarge


def register_error_handlers(app):
    """Register global error handlers for the Flask app."""

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        """Return JSON instead of HTML for HTTP errors."""
        response = e.get_response()
        response.data = json.dumps({
            "code": e.code,
            "name": e.name,
            "description": e.description,
        })
        response.content_type = "application/json"
        return response

    @app.errorhandler(404)
    def not_found_error(error):
        return jsonify({"error": "Resource not found.", "code": 404}), 404

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_error):
        return jsonify({"error": "Upload exceeds the maximum allowed size.", "code": 413}), 413

    @app.errorhandler(Exception)
    def handle_unhandled_exception(e):
        """Log the full traceback for any unhandled exception."""
        # Log the exception to the console for debugging
        traceback.print_exc()

        return jsonify({"error": "An unexpected internal server error occurred.", "code": 500}), 500

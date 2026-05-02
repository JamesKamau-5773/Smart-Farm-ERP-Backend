from flask import jsonify
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import SQLAlchemyError

def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found_error(error):
        return jsonify({"error": "Resource not found.", "code": 404}), 404

    @app.errorhandler(400)
    def bad_request_error(error):
        return jsonify({"error": "Bad request. Please check your payload.", "code": 400}), 400

    @app.errorhandler(405)
    def method_not_allowed_error(error):
        return jsonify({"error": "Method not allowed for this endpoint.", "code": 405}), 405

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        # Rollback the session to prevent a locked database state
        from app import db
        db.session.rollback()
        # In production, log the actual `error` securely to a file/monitoring service here
        return jsonify({"error": "A database error occurred.", "code": 500}), 500

    @app.errorhandler(Exception)
    def unhandled_exception(error):
        # Catch-all for standard Python exceptions
        if isinstance(error, HTTPException):
            return jsonify({"error": error.description, "code": error.code}), error.code
            
        # Log the error trace securely here
        return jsonify({"error": "An unexpected internal server error occurred.", "code": 500}), 500
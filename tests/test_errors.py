import json
from tests.base import BaseTestCase
from flask import Blueprint, abort

# Create a temporary blueprint to test error handlers
errors_test_bp = Blueprint('errors_test', __name__)

@errors_test_bp.route('/test-400')
def test_400():
    abort(400)

@errors_test_bp.route('/test-500')
def test_500():
    abort(500)

class ErrorHandlerTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.app.register_blueprint(errors_test_bp)

    def test_404_not_found(self):
        """Test the global 404 error handler."""
        with self.client:
            response = self.client.get('/a-route-that-does-not-exist')
            self.assertEqual(response.status_code, 404)
            data = json.loads(response.data.decode())
            self.assertEqual(data['error'], 'Resource not found.')
            self.assertEqual(data['code'], 404)

    def test_400_bad_request(self):
        """Test the global 400 error handler."""
        with self.client:
            response = self.client.get('/test-400')
            self.assertEqual(response.status_code, 400)
            data = json.loads(response.data.decode())
            self.assertEqual(data['error'], 'Bad request. Please check your payload.')
            self.assertEqual(data['code'], 400)

    def test_405_method_not_allowed(self):
        """Test the global 405 error handler."""
        with self.client:
            response = self.client.post('/health') # /health is a GET route
            self.assertEqual(response.status_code, 405)
            data = json.loads(response.data.decode())
            self.assertEqual(data['error'], 'Method not allowed for this endpoint.')
            self.assertEqual(data['code'], 405)

    def test_500_internal_server_error(self):
        """Test the global 500 error handler for unhandled exceptions."""
        with self.client:
            response = self.client.get('/test-500')
            # The custom handler in errors.py for Exception returns a 500 code
            self.assertEqual(response.status_code, 500)
            data = json.loads(response.data.decode())
            self.assertIn('An unexpected internal server error occurred.', data['error'])
            self.assertEqual(data['code'], 500)

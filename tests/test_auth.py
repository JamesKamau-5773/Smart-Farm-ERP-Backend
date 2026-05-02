import json
from tests.base import BaseTestCase
from app.models.user import User, Role
from app import db

class AuthTestCase(BaseTestCase):

    def test_registration(self):
        """Test user registration."""
        with self.client:
            response = self.client.post(
                '/api/auth/register',
                data=json.dumps(dict(
                    username='testuser',
                    password='password',
                    role='FARMER'
                )),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 201)
            data = json.loads(response.data.decode())
            self.assertEqual(data['message'], 'User testuser registered successfully.')

    def test_login(self):
        """Test user login."""
        # First, register a user
        user = User(username='testuser', password='password', role=Role.FARMER)
        db.session.add(user)
        db.session.commit()

        with self.client:
            response = self.client.post(
                '/api/auth/login',
                data=json.dumps(dict(
                    username='testuser',
                    password='password'
                )),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data.decode())
            self.assertTrue(data['access_token'])

    def test_logout(self):
        """Test user logout."""
        # First, register and login a user
        user = User(username='testuser', password='password', role=Role.FARMER)
        db.session.add(user)
        db.session.commit()
        self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(
                username='testuser',
                password='password'
            )),
            content_type='application/json'
        )

        with self.client:
            response = self.client.post(
                '/api/auth/logout',
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data.decode())
            self.assertEqual(data['message'], 'Successfully logged out.')

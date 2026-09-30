"""Focused resource authorization tests; no production database is used."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from backend.routes.resources import resources_bp


class ResourcePrivacyTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(resources_bp)
        self.client = app.test_client()

    def test_dynamic_user_and_trip_models_require_admin(self):
        with patch('backend.utils.auth.get_current_user', return_value=SimpleNamespace(
            id=2, user_type='Driver'
        )):
            for name in ('AdminUser', 'Trip', 'TripBooking'):
                with self.subTest(name=name):
                    response = self.client.get(f'/api/api/{name}')
                    self.assertEqual(response.status_code, 403)

    def test_driver_directory_omits_private_fields(self):
        driver = SimpleNamespace(
            id=3, name='Driver', avatar=None, rating=4, vehicle_type='Truck',
            approved_groups=['Truck'], email='private@example.com', nin='private',
            current_latitude='1.23', current_longitude='4.56',
        )
        with patch('backend.utils.auth.get_current_user', return_value=SimpleNamespace(
            id=2, user_type='Customer'
        )), patch('backend.routes.resources.AdminUser') as user_model:
            user_model.query.filter_by.return_value.all.return_value = [driver]
            response = self.client.get('/api/drivers')
        self.assertEqual(response.status_code, 200)
        card = response.json['data'][0]
        self.assertEqual(card['name'], 'Driver')
        self.assertNotIn('nin', card)
        self.assertNotIn('email', card)
        self.assertNotIn('current_latitude', card)


if __name__ == '__main__':
    unittest.main()

"""Isolated fare regression tests: no configured or production database is used."""
import unittest
from unittest.mock import patch
from decimal import Decimal
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles
from backend.models import db
from backend.models.user import AdminUser
from backend.models.vehicle_category import VehicleCategory
from backend.models.negotiation import Negotiation
from backend.models.negotiation_record import NegotiationRecord
from backend.models.user_wallet import UserWallet
from backend.routes.rides import rides_bp
from backend.routes.negotiations import negotiations_bp


@compiles(BigInteger, 'sqlite')
def sqlite_integer(element, compiler, **kw):
    return 'INTEGER'


class LargeFareTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', TESTING=True,
                               JWT_SECRET_KEY='isolated-fare-test-key-not-for-production')
        db.init_app(self.app)
        JWTManager(self.app)
        self.app.register_blueprint(rides_bp)
        self.app.register_blueprint(negotiations_bp)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        db.session.add_all([
            AdminUser(id=1, username='customer', password='unused', user_type='Customer'),
            AdminUser(id=2, username='driver', password='unused', user_type='Driver'),
            VehicleCategory(id=1, name='Truck', code='truck', service_group='Truck',
                            min_price=1000, per_km_rate=10, is_active=1),
        ])
        db.session.commit()
        self.client = self.app.test_client()
        self.customer = {'Authorization': 'Bearer ' + create_access_token(identity='1')}
        self.driver = {'Authorization': 'Bearer ' + create_access_token(identity='2')}
        self.notify = patch('backend.routes.rides.notify_user')
        self.notify.start()

    def tearDown(self):
        self.notify.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def request_ride(self, fare):
        return self.client.post('/api/rides/request', json={
            'category_id': 1, 'driver_id': 2, 'pickup_lat': 6.5, 'pickup_lng': 3.4,
            'dropoff_lat': 6.6, 'dropoff_lng': 3.5, 'distance_km': 10,
            'duration_min': 20, 'proposed_price': fare,
        }, headers=self.customer)

    def test_large_fare_request_counter_accept_and_complete(self):
        for fare in (1000000, 1500000, 25000000, 1000000000):
            with self.subTest(fare=fare):
                response = self.request_ride(fare)
                self.assertEqual(response.status_code, 200, response.get_json())
                ride_id = response.get_json()['data']['ride_id']
                ride = db.session.get(Negotiation, ride_id)
                self.assertEqual(ride.initial_price, fare * 100)
                self.assertEqual(NegotiationRecord.query.filter_by(
                    negotiation_id=ride_id).first().price, fare * 100)
                response = self.client.post(f'/api/rides/{ride_id}/respond',
                    json={'action': 'negotiate'}, headers=self.driver)
                self.assertEqual(response.status_code, 200)
                counter = fare + 250000
                response = self.client.post(f'/api/rides/{ride_id}/negotiation',
                    json={'action': 'offer', 'price': counter}, headers=self.driver)
                self.assertEqual(response.status_code, 200, response.get_json())
                response = self.client.post(f'/api/rides/{ride_id}/negotiation',
                    json={'action': 'accept'}, headers=self.customer)
                self.assertEqual(response.status_code, 200, response.get_json())
                self.assertEqual(ride.agreed_price, Decimal(counter * 100))
                self.assertEqual(ride.to_dict()['fare'], counter)
                for action in ('start', 'complete'):
                    response = self.client.post(f'/api/rides/{ride_id}/{action}',
                                                headers=self.driver)
                    self.assertEqual(response.status_code, 200, response.get_json())
                self.assertEqual(ride.status, 'Completed')
        self.assertEqual(UserWallet.query.filter_by(user_id=2).one().wallet_balance,
                         Decimal(sum(x + 250000 for x in
                                     (1000000, 1500000, 25000000, 1000000000))))

    def test_legacy_mobile_counter_and_accept(self):
        response = self.request_ride(1500000)
        ride_id = response.get_json()['data']['ride_id']
        response = self.client.post('/api/negotiations-records', json={
            'negotiation_id': ride_id, 'price': 25000000,
            'message_type': 'Negotiation', 'message_body': 'Counter offer',
        }, headers=self.driver)
        self.assertEqual(response.status_code, 201, response.get_json())
        response = self.client.post('/api/negotiations-accept', json={
            'negotiation_id': ride_id, 'message_type': 'Accept',
        }, headers=self.customer)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(db.session.get(Negotiation, ride_id).agreed_price,
                         Decimal(2500000000))

    def test_agreed_price_endpoint_has_no_business_ceiling(self):
        ride_id = self.request_ride(1500000).get_json()['data']['ride_id']
        response = self.client.post(f'/api/negotiations/{ride_id}/set-agreed-price',
            json={'agreed_price': 2500000000}, headers=self.customer)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['data']['fare'], 25000000)

    def test_large_suggested_fare_without_customer_override(self):
        with patch('backend.routes.rides._estimate', return_value={'estimate': 1500000}):
            response = self.client.post('/api/rides/request', json={
                'category_id': 1, 'driver_id': 2, 'pickup_lat': 6.5, 'pickup_lng': 3.4,
                'distance_km': 10, 'duration_min': 20,
            }, headers=self.customer)
        self.assertEqual(response.status_code, 200, response.get_json())
        ride = db.session.get(Negotiation, response.get_json()['data']['ride_id'])
        self.assertEqual(ride.initial_price, 150000000)

    def test_invalid_fares_still_rejected(self):
        for fare in (0, -1, 'NaN', 'Infinity', '-Infinity', 'invalid'):
            with self.subTest(fare=fare):
                response = self.request_ride(fare)
                self.assertEqual(response.get_json()['code'], 0)
        self.assertEqual(Negotiation.query.count(), 0)


if __name__ == '__main__':
    unittest.main()

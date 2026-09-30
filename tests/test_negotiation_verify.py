"""Isolated tests for ghost-trip prevention: /api/negotiations-verify and the
machine-readable `negotiation_not_found` error code. No real database is used."""
import unittest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles
from backend.models import db
from backend.models.user import AdminUser
from backend.models.negotiation import Negotiation
from backend.routes.negotiations import negotiations_bp


@compiles(BigInteger, 'sqlite')
def sqlite_integer(element, compiler, **kw):
    return 'INTEGER'


class NegotiationVerifyTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', TESTING=True,
                               JWT_SECRET_KEY='isolated-verify-test-key-not-for-production')
        db.init_app(self.app)
        JWTManager(self.app)
        self.app.register_blueprint(negotiations_bp)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        db.session.add_all([
            AdminUser(id=1, username='customer', password='x', user_type='Customer'),
            AdminUser(id=2, username='driver', password='x', user_type='Driver'),
            AdminUser(id=3, username='stranger', password='x', user_type='Customer'),
            Negotiation(id=10, customer_id=1, driver_id=2, status='Accepted', is_active='Yes'),
            Negotiation(id=11, customer_id=1, driver_id=2, status='Completed', is_active='No'),
            Negotiation(id=12, customer_id=3, driver_id=2, status='Active', is_active='Yes'),
            Negotiation(id=13, customer_id=1, driver_id=2, status='Accepted', is_active='No'),
        ])
        db.session.commit()
        self.client = self.app.test_client()
        self.customer = {'Authorization': 'Bearer ' + create_access_token(identity='1')}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_verify_classifies_active_ended_and_gone(self):
        r = self.client.post('/api/negotiations-verify', json={'ids': [10, 11, 12, 13, 104]}, headers=self.customer)
        self.assertEqual(r.status_code, 200, r.get_json())
        d = r.get_json()['data']
        self.assertEqual(d['results']['10']['state'], 'active')
        self.assertEqual(d['results']['11']['state'], 'ended')
        self.assertEqual(d['results']['12']['state'], 'gone')      # someone else's ride
        self.assertEqual(d['results']['13']['state'], 'ended')     # inactive row with a stale open status
        self.assertEqual(d['results']['104']['state'], 'gone')     # does not exist
        self.assertEqual(sorted(d['gone_ids']), [12, 104])
        self.assertEqual(d['active_ids'], [10])

    def test_verify_accepts_comma_string_and_ignores_junk(self):
        r = self.client.post('/api/negotiations-verify', data={'ids': '10, x, 104'}, headers=self.customer)
        d = r.get_json()['data']
        self.assertEqual(set(d['results']), {'10', '104'})

    def test_missing_negotiation_has_machine_readable_code(self):
        r = self.client.post('/api/negotiations-complete', json={'negotiation_id': 104}, headers=self.customer)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()['data']['error_code'], 'negotiation_not_found')


if __name__ == '__main__':
    unittest.main()

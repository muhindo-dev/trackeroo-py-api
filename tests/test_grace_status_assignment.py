"""Regression tests for assigning grace subscriptions during driver status refresh."""
import unittest
from datetime import datetime, timedelta

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles

from backend.models import db
from backend.models.grace_policy import DriverGracePolicy
from backend.models.subscription import Subscription, SubscriptionPlan
from backend.models.user import AdminUser
from backend.routes.subscriptions import subscriptions_bp


@compiles(BigInteger, 'sqlite')
def sqlite_integer(element, compiler, **kw):
    return 'INTEGER'


class GraceStatusAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SQLALCHEMY_DATABASE_URI='sqlite://', TESTING=True,
            JWT_SECRET_KEY='isolated-grace-test-key-not-for-production',
        )
        db.init_app(self.app)
        JWTManager(self.app)
        self.app.register_blueprint(subscriptions_bp)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        now = datetime.utcnow()
        self.plan = SubscriptionPlan(
            id=1, name='Premium weekly', code='weekly', period='Weekly',
            duration_days=7, amount=2500, currency='NGN', is_active=1,
        )
        db.session.add(self.plan)
        db.session.commit()
        self.now = now
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def add_policy(self, *, existing=False):
        policy = DriverGracePolicy(
            id=1, name='Launch offer', plan_id=1,
            start_at=self.now - timedelta(days=1),
            end_at=self.now + timedelta(days=1), duration_days=14,
            apply_to_new_drivers=1, apply_to_existing=1 if existing else 0,
            is_active=1, redemption_count=0,
        )
        db.session.add(policy)
        db.session.commit()
        return policy

    def add_driver(self, *, account_type='Driver', created_at=None):
        driver = AdminUser(
            id=1, username='driver', password='x',
            user_type='Pending Driver', account_type=account_type,
            created_at=created_at or self.now - timedelta(minutes=1),
        )
        db.session.add(driver)
        db.session.commit()
        return driver

    def status(self):
        token = create_access_token(identity='1')
        return self.client.get('/api/subscriptions/status', headers={
            'Authorization': 'Bearer ' + token,
        })

    def test_status_retries_grant_for_new_driver_registered_during_offer(self):
        policy = self.add_policy(existing=False)
        self.add_driver(account_type='Driver')

        response = self.status()

        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()['data']
        self.assertTrue(data['is_subscribed'])
        self.assertTrue(data['active']['is_grace'])
        self.assertEqual(data['active']['amount'], 0)
        self.assertEqual(data['active']['plan_id'], self.plan.id)
        self.assertEqual(Subscription.query.count(), 1)
        self.assertEqual(db.session.get(DriverGracePolicy, policy.id).redemption_count, 1)

        # Refreshing again must not create another free subscription.
        self.status()
        self.assertEqual(Subscription.query.count(), 1)

    def test_old_driver_does_not_redeem_new_driver_only_offer(self):
        self.add_policy(existing=False)
        self.add_driver(account_type='Driver', created_at=self.now - timedelta(days=2))

        response = self.status()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['data']['is_subscribed'])
        self.assertEqual(Subscription.query.count(), 0)

    def test_existing_driver_can_receive_offer_when_policy_includes_existing(self):
        self.add_policy(existing=True)
        self.add_driver(account_type='Driver', created_at=self.now - timedelta(days=30))

        response = self.status()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['data']['active']['is_grace'])
        self.assertEqual(Subscription.query.count(), 1)

    def test_converted_customer_uses_existing_driver_eligibility(self):
        self.add_policy(existing=True)
        self.add_driver(account_type='Customer', created_at=self.now - timedelta(days=30))

        response = self.status()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['data']['active']['is_grace'])


if __name__ == '__main__':
    unittest.main()

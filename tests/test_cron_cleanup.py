"""Isolated regression tests for the cleanup scheduler; no live DB is used."""

import os
import hashlib
import hmac
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles

from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.user import AdminUser
from backend.routes.cron import cron_bp
from backend.routes.rides import rides_bp
from backend.routes.subscriptions import subscriptions_bp
from backend.routes.flutterwave import flutterwave_bp
from backend.services.flutterwave_service import FlutterwaveService


@compiles(BigInteger, 'sqlite')
def sqlite_integer(element, compiler, **kw):
    return 'INTEGER'


class CleanupCronTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', TESTING=True)
        db.init_app(self.app)
        self.app.register_blueprint(cron_bp)
        self.app.register_blueprint(rides_bp)
        self.app.register_blueprint(subscriptions_bp)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        old = datetime.utcnow() - timedelta(minutes=40)
        db.session.add_all([
            AdminUser(id=1, username='driver', password='x',
                      user_type='Driver', ready_for_trip='Yes',
                      location_updated_at=old),
            Negotiation(id=10, customer_id=2, driver_id=1,
                        status='Active', is_active='Yes', updated_at=old),
        ])
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_get_and_unconfigured_requests_cannot_run_cleanup(self):
        with patch.dict(os.environ, {'SUBSCRIPTION_CRON_SECRET': ''}):
            self.assertEqual(self.client.get('/api/cron/cleanup').status_code, 405)
            self.assertEqual(self.client.post('/api/cron/cleanup').status_code, 503)
        self.assertEqual(db.session.get(Negotiation, 10).status, 'Active')
        self.assertEqual(db.session.get(AdminUser, 1).ready_for_trip, 'Yes')

    def test_wrong_secret_does_not_change_state(self):
        with patch.dict(os.environ, {'SUBSCRIPTION_CRON_SECRET': 'correct'}):
            resp = self.client.post('/api/cron/cleanup',
                                    headers={'X-Cron-Secret': 'wrong'})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(db.session.get(Negotiation, 10).status, 'Active')

    def test_other_scheduler_routes_also_fail_closed(self):
        paths = ['/api/rides/dispatch-due', '/api/subscriptions/expire']
        for path in paths:
            with patch.dict(os.environ, {'SUBSCRIPTION_CRON_SECRET': ''}):
                self.assertEqual(self.client.post(path).status_code, 503)
            with patch.dict(os.environ, {'SUBSCRIPTION_CRON_SECRET': 'correct'}):
                self.assertEqual(self.client.post(path,
                    headers={'X-Cron-Secret': 'wrong'}).status_code, 403)

    def test_flutterwave_webhook_requires_configured_hash(self):
        payload = b'{"event":"charge.completed"}'
        with patch.dict(os.environ, {'FLW_SECRET_HASH': ''}):
            self.assertFalse(FlutterwaveService().verify_webhook_signature(
                payload, 'anything'))
        with patch.dict(os.environ, {'FLW_SECRET_HASH': 'correct'}):
            signature = hmac.new(b'correct', payload, hashlib.sha256).hexdigest()
            service = FlutterwaveService()
            self.assertTrue(service.verify_webhook_signature(payload, signature))
            self.assertFalse(service.verify_webhook_signature(payload, 'wrong'))

    def test_correct_secret_runs_cleanup_once(self):
        with patch.dict(os.environ, {'SUBSCRIPTION_CRON_SECRET': 'correct'}):
            resp = self.client.post('/api/cron/cleanup',
                                    headers={'X-Cron-Secret': 'correct'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json['data']['drivers_offline'], 1)
        self.assertEqual(resp.json['data']['negotiations_cancelled'], 1)
        db.session.expire_all()
        self.assertEqual(db.session.get(AdminUser, 1).ready_for_trip, 'No')
        self.assertEqual(db.session.get(Negotiation, 10).status, 'Cancelled')
        self.assertEqual(db.session.get(Negotiation, 10).is_active, 'No')


class TransferCallbackAuthTests(unittest.TestCase):
    def test_callback_rejects_unsigned_and_accepts_signed_payload(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(flutterwave_bp)
        client = app.test_client()
        payload = b'{"id":"123","status":"SUCCESSFUL"}'
        with patch.dict(os.environ, {'FLW_SECRET_HASH': 'callback-secret'}), patch(
            'backend.routes.flutterwave._handle_transfer_completed'
        ) as handler:
            self.assertEqual(client.post('/api/flutterwave/transfer-callback',
                                         data=payload, content_type='application/json').status_code, 401)
            handler.assert_not_called()
            signature = hmac.new(b'callback-secret', payload, hashlib.sha256).hexdigest()
            self.assertEqual(client.post('/api/flutterwave/transfer-callback',
                                         data=payload, content_type='application/json',
                                         headers={'verificationhash': signature}).status_code, 200)
            handler.assert_called_once()

    def test_transfer_status_does_not_disclose_another_drivers_payout(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(flutterwave_bp)
        with patch('backend.utils.auth.get_current_user', return_value=SimpleNamespace(
            id=2, user_type='Driver'
        )), patch('backend.routes.flutterwave.PayoutRequest') as payout_model, patch(
            'backend.routes.flutterwave.get_flutterwave'
        ) as provider:
            payout_model.query.filter_by.return_value.first.return_value = SimpleNamespace(
                user_id=3
            )
            response = app.test_client().get(
                '/api/flutterwave/transfer-status?flw_transfer_id=other-driver-transfer'
            )
            self.assertEqual(response.status_code, 404)
            provider.assert_not_called()


if __name__ == '__main__':
    unittest.main()

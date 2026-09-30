"""Driver reviews cannot grant retired services or silently invent one."""
import unittest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles
from backend.models import db
from backend.models.user import AdminUser
from backend.routes.admin import admin_bp


@compiles(BigInteger, 'sqlite')
def sqlite_integer(element, compiler, **kw):
    return 'INTEGER'


class DriverServiceApprovalTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', TESTING=True,
                               JWT_SECRET_KEY='service-review-test-key')
        db.init_app(self.app)
        JWTManager(self.app)
        self.app.register_blueprint(admin_bp)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        db.session.add_all([
            AdminUser(id=1, username='admin', password='x', user_type='Admin'),
            AdminUser(id=2, username='applicant', password='x', user_type='Pending Driver',
                      is_car='Yes', is_delivery='Yes', is_ambulance='Yes',
                      is_ambulance_approved='Yes'),
        ])
        db.session.commit()
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer ' + create_access_token(identity='1')}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def approve(self, **kwargs):
        return self.client.post('/api/admin/users/2/approve-driver',
                                headers=self.headers, **kwargs)

    def test_retired_or_empty_services_cannot_approve_driver(self):
        for selected in (['ambulance'], ['car', 'police'], []):
            response = self.approve(json={'services': selected})
            self.assertEqual(response.status_code, 422, response.get_json())
            self.assertEqual(db.session.get(AdminUser, 2).user_type, 'Pending Driver')

    def test_review_approves_selected_services_only_and_clears_legacy_approval(self):
        response = self.approve(json={'services': ['delivery']})
        self.assertEqual(response.status_code, 200, response.get_json())
        driver = db.session.get(AdminUser, 2)
        self.assertEqual(driver.user_type, 'Driver')
        self.assertEqual(driver.is_delivery_approved, 'Yes')
        self.assertEqual(driver.is_car_approved, 'No')
        self.assertEqual(driver.is_ambulance_approved, 'No')

    def test_legacy_quick_approve_uses_only_current_applications(self):
        response = self.approve()
        self.assertEqual(response.status_code, 200, response.get_json())
        driver = db.session.get(AdminUser, 2)
        self.assertEqual(driver.is_car_approved, 'Yes')
        self.assertEqual(driver.is_delivery_approved, 'Yes')
        self.assertEqual(driver.is_ambulance_approved, 'No')


if __name__ == '__main__':
    unittest.main()

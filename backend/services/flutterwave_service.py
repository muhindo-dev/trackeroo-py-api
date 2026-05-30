"""
Flutterwave Payment Service — Truckeroo Nigeria

Replaces Stripe. Handles:
  • Hosted payment page initiation (standard checkout)
  • Transaction verification (by tx_ref or ID)
  • Webhook signature verification
  • Bank transfers / payouts
  • Bank account lookup
  • Nigerian bank list

API base: https://api.flutterwave.com/v3
Docs: https://developer.flutterwave.com
"""

import hashlib
import hmac
import os
import uuid
from datetime import datetime

import requests
from flask import current_app


class FlutterwaveError(Exception):
    """Raised when Flutterwave returns an error or network failure."""
    pass


class FlutterwaveService:
    """Core Flutterwave integration for Truckeroo Nigeria."""

    BASE_URL = "https://api.flutterwave.com/v3"

    def __init__(self):
        self._secret_key = os.getenv('FLW_SECRET_KEY', '')
        self._public_key = os.getenv('FLW_PUBLIC_KEY', '')
        self._secret_hash = os.getenv('FLW_SECRET_HASH', '')
        self._currency = os.getenv('FLW_CURRENCY', 'NGN')
        self._payment_options = os.getenv('FLW_PAYMENT_OPTIONS', 'card,banktransfer,ussd')
        self._timeout = int(os.getenv('FLW_TIMEOUT', 30))
        self._app_url = os.getenv('APP_URL', 'https://truckeroo.mruodel.com')

    # ── Internal helpers ──────────────────────────────────────────────────────

    @property
    def _headers(self) -> dict:
        if not self._secret_key:
            raise FlutterwaveError(
                'Flutterwave not configured: FLW_SECRET_KEY missing in environment.'
            )
        return {
            'Authorization': f'Bearer {self._secret_key}',
            'Content-Type': 'application/json',
        }

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.BASE_URL}{path}"
        try:
            resp = requests.get(url, headers=self._headers, params=params,
                                timeout=self._timeout)
        except requests.RequestException as e:
            raise FlutterwaveError(f"Network error calling Flutterwave: {e}")
        data = resp.json()
        if not resp.ok:
            raise FlutterwaveError(
                f"Flutterwave GET {path} failed [{resp.status_code}]: "
                f"{data.get('message', resp.text)}"
            )
        return data

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.BASE_URL}{path}"
        try:
            resp = requests.post(url, json=payload, headers=self._headers,
                                 timeout=self._timeout)
        except requests.RequestException as e:
            raise FlutterwaveError(f"Network error calling Flutterwave: {e}")
        data = resp.json()
        if not resp.ok:
            raise FlutterwaveError(
                f"Flutterwave POST {path} failed [{resp.status_code}]: "
                f"{data.get('message', resp.text)}"
            )
        return data

    # ── Webhook verification ──────────────────────────────────────────────────

    def verify_webhook_signature(self, payload_bytes: bytes, signature: str) -> bool:
        """Verify Flutterwave webhook using HMAC-SHA256 with FLW_SECRET_HASH.

        Flutterwave sends the hash in the 'verificationhash' header.
        """
        if not self._secret_hash:
            # No hash configured — skip verification (dev mode)
            return True
        computed = hmac.new(
            self._secret_hash.encode('utf-8'),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(computed, str(signature))

    # ── Payment initiation ────────────────────────────────────────────────────

    def initialize_payment(
        self,
        amount: float,
        tx_ref: str,
        customer_name: str,
        customer_email: str,
        customer_phone: str,
        redirect_url: str = None,
        description: str = 'Truckeroo Payment',
        currency: str = None,
        payment_options: str = None,
        meta: dict = None,
    ) -> dict:
        """Create a Flutterwave hosted payment page.

        Returns a dict with 'payment_link' (the hosted URL) and 'tx_ref'.
        The customer is redirected to `payment_link` to complete payment.
        """
        payload = {
            'tx_ref': tx_ref,
            'amount': float(amount),
            'currency': currency or self._currency,
            'redirect_url': redirect_url or f"{self._app_url}/api/flutterwave/callback",
            'payment_options': payment_options or self._payment_options,
            'customer': {
                'email': customer_email or f"customer_{tx_ref}@truckeroo.com",
                'phonenumber': self._normalize_phone(customer_phone),
                'name': customer_name or 'Truckeroo Customer',
            },
            'customizations': {
                'title': 'Truckeroo Nigeria',
                'description': description,
                'logo': f"{self._app_url}/uploads/images/truckero.png",
            },
        }
        if meta:
            payload['meta'] = meta

        data = self._post('/payments', payload)

        # Flutterwave returns status='success' and data.link for hosted page
        if data.get('status') != 'success' or not data.get('data', {}).get('link'):
            raise FlutterwaveError(
                f"Flutterwave did not return a payment link: {data.get('message', data)}"
            )

        return {
            'tx_ref': tx_ref,
            'payment_link': data['data']['link'],
            'flw_response': data,
        }

    # ── Transaction verification ──────────────────────────────────────────────

    def verify_by_tx_ref(self, tx_ref: str) -> dict:
        """Verify a transaction using your unique tx_ref.

        Returns the raw Flutterwave response dict.
        Raises FlutterwaveError if not found or API failure.
        """
        data = self._get('/transactions/verify_by_reference', {'tx_ref': tx_ref})
        return data

    def verify_by_id(self, transaction_id: str) -> dict:
        """Verify a transaction using Flutterwave's own transaction ID."""
        data = self._get(f'/transactions/{transaction_id}/verify')
        return data

    def is_payment_successful(self, verification_response: dict, expected_amount: float,
                               expected_currency: str = None) -> bool:
        """Check if a verification response represents a successful, valid payment.

        Validates:
          1. status == 'success'
          2. data.status == 'successful'
          3. amount_paid >= expected_amount (within 1% tolerance)
          4. currency matches (if expected_currency provided)
        """
        if verification_response.get('status') != 'success':
            return False
        tx_data = verification_response.get('data', {})
        if tx_data.get('status') != 'successful':
            return False
        paid_amount = float(tx_data.get('amount', 0))
        if paid_amount < (float(expected_amount) * 0.99):
            return False
        if expected_currency and tx_data.get('currency', '').upper() != expected_currency.upper():
            return False
        return True

    def extract_payment_info(self, verification_response: dict) -> dict:
        """Extract useful payment info from a verified transaction."""
        tx = verification_response.get('data', {})
        return {
            'flw_tx_id': str(tx.get('id', '')),
            'tx_ref': tx.get('tx_ref', ''),
            'amount': float(tx.get('amount', 0)),
            'currency': tx.get('currency', ''),
            'payment_type': tx.get('payment_type', ''),
            'customer_email': tx.get('customer', {}).get('email', ''),
            'customer_name': tx.get('customer', {}).get('name', ''),
            'customer_phone': tx.get('customer', {}).get('phone_number', ''),
            'flw_ref': tx.get('flw_ref', ''),
            'status': tx.get('status', ''),
        }

    # ── Nigerian bank utilities ───────────────────────────────────────────────

    def get_banks(self, country: str = 'NG') -> list:
        """Fetch list of supported banks for a country.
        FLW endpoint: GET /v3/banks/{country}
        """
        data = self._get(f'/banks/{country}')
        return data.get('data', [])

    def verify_bank_account(self, account_number: str, bank_code: str) -> dict:
        """Verify a Nigerian bank account and get the account holder name.

        Returns dict with 'account_name', 'account_number', 'bank_id'.
        """
        payload = {
            'account_number': account_number,
            'account_bank': bank_code,
            'country': 'NG',
        }
        data = self._post('/accounts/resolve', payload)
        if data.get('status') != 'success':
            raise FlutterwaveError(
                f"Bank account verification failed: {data.get('message', 'Unknown error')}"
            )
        return {
            'account_name': data.get('data', {}).get('account_name', ''),
            'account_number': account_number,
            'bank_code': bank_code,
            'flw_response': data,
        }

    # ── Transfers / Payouts ───────────────────────────────────────────────────

    def initiate_transfer(
        self,
        account_bank: str,
        account_number: str,
        amount: float,
        beneficiary_name: str,
        narration: str,
        reference: str = None,
        currency: str = None,
    ) -> dict:
        """Send money to a Nigerian bank account (payout to driver).

        Args:
            account_bank: CBN bank code (e.g., '044' for Access Bank)
            account_number: Beneficiary account number
            amount: Transfer amount in NGN
            beneficiary_name: Account holder name
            narration: Payment description (max 100 chars)
            reference: Unique transfer reference (auto-generated if None)
            currency: Default NGN

        Returns dict with transfer id, reference, status.
        """
        if not reference:
            reference = f"truckeroo-payout-{uuid.uuid4().hex[:16]}"

        payload = {
            'account_bank': account_bank,
            'account_number': account_number,
            'amount': float(amount),
            'narration': narration[:100],
            'currency': currency or self._currency,
            'reference': reference,
            'beneficiary_name': beneficiary_name,
            'callback_url': f"{self._app_url}/api/flutterwave/transfer-callback",
        }

        data = self._post('/transfers', payload)

        if data.get('status') != 'success':
            raise FlutterwaveError(
                f"Transfer failed: {data.get('message', 'Unknown error')}"
            )

        tx_data = data.get('data', {})
        return {
            'flw_transfer_id': str(tx_data.get('id', '')),
            'reference': tx_data.get('reference', reference),
            'status': tx_data.get('status', 'PENDING'),
            'amount': float(tx_data.get('amount', amount)),
            'currency': tx_data.get('currency', self._currency),
            'flw_response': data,
        }

    def get_transfer_status(self, transfer_id: str) -> dict:
        """Check the current status of an initiated transfer."""
        data = self._get(f'/transfers/{transfer_id}')
        tx = data.get('data', {})
        return {
            'flw_transfer_id': str(tx.get('id', transfer_id)),
            'reference': tx.get('reference', ''),
            'status': tx.get('status', 'UNKNOWN'),
            'amount': float(tx.get('amount', 0)),
            'currency': tx.get('currency', ''),
            'narration': tx.get('narration', ''),
            'flw_response': data,
        }

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def generate_tx_ref(prefix: str = 'truck') -> str:
        """Generate a unique transaction reference."""
        ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        rand = uuid.uuid4().hex[:8]
        return f"{prefix}-{ts}-{rand}"

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """Normalize Nigerian phone number to international format (+234...)."""
        if not phone:
            return ''
        digits = ''.join(c for c in str(phone) if c.isdigit())
        if digits.startswith('234') and len(digits) >= 13:
            return f"+{digits[:13]}"
        if digits.startswith('0') and len(digits) == 11:
            return f"+234{digits[1:]}"
        if len(digits) == 10:
            return f"+234{digits}"
        return f"+{digits}" if digits else ''

    def format_ngn(self, amount: float) -> str:
        """Format amount as NGN string."""
        return f"₦{amount:,.0f}"


# Singleton-like factory — instantiate once per request context
def get_flutterwave() -> FlutterwaveService:
    """Get a FlutterwaveService instance."""
    return FlutterwaveService()

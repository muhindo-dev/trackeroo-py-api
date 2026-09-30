"""Shared fail-closed authentication for background scheduler endpoints."""

import hmac
import os

from flask import request

from backend.utils.response import error_response


def cron_auth_error():
    """Return an HTTP error if the configured scheduler header is not valid."""
    secret = os.getenv('SUBSCRIPTION_CRON_SECRET', '').strip()
    if not secret:
        return error_response('Scheduler is not configured', status_code=503)
    provided = request.headers.get('X-Cron-Secret', '')
    if not hmac.compare_digest(provided, secret):
        return error_response('Forbidden', status_code=403)
    return None

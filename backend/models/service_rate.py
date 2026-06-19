from datetime import datetime
from backend.models import db


class ServiceRate(db.Model):
    __tablename__ = 'service_rates'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    service_type = db.Column(db.String(100), nullable=False)
    vehicle_type = db.Column(db.String(100), default='Any')
    # Columns keep _cad suffix for DB compat but values are in NGN
    base_rate_cad = db.Column(db.Numeric(10, 2), default=0.00)
    per_km_rate_cad = db.Column(db.Numeric(10, 2), default=0.00)
    per_minute_rate_cad = db.Column(db.Numeric(10, 2), default=0.00)
    surge_multiplier = db.Column(db.Numeric(4, 2), default=1.00)
    minimum_fare_cad = db.Column(db.Numeric(10, 2), default=0.00)
    currency = db.Column(db.String(5), default='NGN')
    is_active = db.Column(db.SmallInteger, default=1)
    notes = db.Column(db.Text, nullable=True)

    # ---- Client pricing-formula parameters (migration 0013) ----
    # PRICE = base + p*extra_km + q*peak_min + r*offpeak_min
    #               + s*(start - est_loading) + t*(time_from_est_completion)
    p_extra_km = db.Column(db.Numeric(10, 2), default=0.00)        # p
    q_peak_minute = db.Column(db.Numeric(10, 2), default=0.00)     # q
    r_offpeak_minute = db.Column(db.Numeric(10, 2), default=0.00)  # r
    s_loading_overrun = db.Column(db.Numeric(10, 2), default=0.00) # s
    t_completion_overrun = db.Column(db.Numeric(10, 2), default=0.00)  # t
    free_km = db.Column(db.Numeric(10, 2), default=0.00)           # km included in base
    peak_start_hour = db.Column(db.Integer, default=7)             # local peak window
    peak_end_hour = db.Column(db.Integer, default=10)
    peak_start_hour_pm = db.Column(db.Integer, default=16)
    peak_end_hour_pm = db.Column(db.Integer, default=20)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get_rate(service_type: str, vehicle_type: str = None):
        q = ServiceRate.query.filter_by(is_active=1, service_type=service_type)
        if vehicle_type:
            exact = q.filter_by(vehicle_type=vehicle_type).first()
            if exact:
                return exact
        return q.filter_by(vehicle_type='Any').first() or q.first()

    @staticmethod
    def estimate_fare(service_type: str, vehicle_type: str, distance_km: float, duration_min: float = 0) -> dict:
        rate = ServiceRate.get_rate(service_type, vehicle_type)
        currency = rate.currency if rate else 'NGN'
        if not rate:
            return {'min': 0, 'max': 0, 'base': 0, 'per_km': 0, 'currency': currency}

        base = float(rate.base_rate_cad or 0)
        per_km = float(rate.per_km_rate_cad or 0)
        per_min = float(rate.per_minute_rate_cad or 0)
        surge = float(rate.surge_multiplier or 1)
        minimum = float(rate.minimum_fare_cad or 0)

        estimated = (base + per_km * distance_km + per_min * duration_min) * surge
        estimated = max(estimated, minimum)

        return {
            'min': round(estimated * 0.9, 0),
            'max': round(estimated * 1.1, 0),
            'estimate': round(estimated, 0),
            'base_rate': base,
            'per_km_rate': per_km,
            'surge_multiplier': surge,
            'currency': currency,
        }

    def _peak_split(self, duration_min: float, start_dt=None):
        """Split a trip duration into peak vs off-peak minutes using the
        configured peak windows. If we cannot tell, treat all as off-peak."""
        from datetime import datetime as _dt
        duration_min = float(duration_min or 0)
        if duration_min <= 0:
            return 0.0, 0.0
        start_dt = start_dt or _dt.utcnow()
        hour = start_dt.hour
        in_peak = (
            (int(self.peak_start_hour or 0) <= hour < int(self.peak_end_hour or 0)) or
            (int(self.peak_start_hour_pm or 0) <= hour < int(self.peak_end_hour_pm or 0))
        )
        if in_peak:
            return duration_min, 0.0
        return 0.0, duration_min

    def estimate_fare_v2(self, distance_km: float, duration_min: float = 0,
                         loading_overrun_min: float = 0, completion_overrun_min: float = 0,
                         start_dt=None, min_price: float = None,
                         base_price: float = None, per_km: float = None) -> dict:
        """Client pricing formula:
        PRICE = base + p*extra_km + q*peak_min + r*offpeak_min
                     + s*loading_overrun + t*completion_overrun
        `extra_km` is distance beyond the included free_km. Result is floored at
        the greater of the rate's minimum fare and the category min_price.

        `base_price` and `per_km` (p) can be overridden by the caller — used so a
        vehicle category can supply the base price and per-km charge while this
        rate row supplies the time coefficients (q, r, s, t).
        """
        base = float(base_price) if base_price is not None else float(self.base_rate_cad or 0)
        free_km = float(self.free_km or 0)
        p = float(per_km) if per_km is not None else float(self.p_extra_km or 0)
        q = float(self.q_peak_minute or 0)
        r = float(self.r_offpeak_minute or 0)
        s = float(self.s_loading_overrun or 0)
        t = float(self.t_completion_overrun or 0)
        surge = float(self.surge_multiplier or 1)

        extra_km = max(float(distance_km or 0) - free_km, 0)
        peak_min, offpeak_min = self._peak_split(duration_min, start_dt)

        price = (
            base
            + p * extra_km
            + q * peak_min
            + r * offpeak_min
            + s * max(float(loading_overrun_min or 0), 0)
            + t * max(float(completion_overrun_min or 0), 0)
        ) * surge

        floor = max(float(self.minimum_fare_cad or 0), float(min_price or 0))
        price = max(price, floor)

        return {
            'estimate': round(price, 0),
            'min': round(price * 0.95, 0),
            'max': round(price * 1.1, 0),
            'currency': self.currency or 'NGN',
            'breakdown': {
                'base': base,
                'extra_km': extra_km,
                'p_extra_km': p * extra_km,
                'peak_minutes': peak_min,
                'q_peak': q * peak_min,
                'offpeak_minutes': offpeak_min,
                'r_offpeak': r * offpeak_min,
                's_loading_overrun': s * max(float(loading_overrun_min or 0), 0),
                't_completion_overrun': t * max(float(completion_overrun_min or 0), 0),
                'surge_multiplier': surge,
                'floor': floor,
            },
        }

    def to_dict(self):
        return {
            'id': self.id,
            'service_type': self.service_type,
            'vehicle_type': self.vehicle_type,
            'base_rate': float(self.base_rate_cad or 0),
            'per_km_rate': float(self.per_km_rate_cad or 0),
            'per_minute_rate': float(self.per_minute_rate_cad or 0),
            'surge_multiplier': float(self.surge_multiplier or 1),
            'minimum_fare': float(self.minimum_fare_cad or 0),
            'currency': self.currency or 'NGN',
            'is_active': bool(self.is_active),
            'notes': self.notes,
            # Pricing-formula parameters
            'p_extra_km': float(self.p_extra_km or 0),
            'q_peak_minute': float(self.q_peak_minute or 0),
            'r_offpeak_minute': float(self.r_offpeak_minute or 0),
            's_loading_overrun': float(self.s_loading_overrun or 0),
            't_completion_overrun': float(self.t_completion_overrun or 0),
            'free_km': float(self.free_km or 0),
            'peak_start_hour': self.peak_start_hour,
            'peak_end_hour': self.peak_end_hour,
            'peak_start_hour_pm': self.peak_start_hour_pm,
            'peak_end_hour_pm': self.peak_end_hour_pm,
            # Backward-compat aliases
            'base_rate_cad': float(self.base_rate_cad or 0),
            'per_km_rate_cad': float(self.per_km_rate_cad or 0),
            'minimum_fare_cad': float(self.minimum_fare_cad or 0),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

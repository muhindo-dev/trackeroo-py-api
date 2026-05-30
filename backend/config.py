import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'negoride-default-secret-key-2026')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'negoride-default-jwt-key-2026')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(seconds=int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES', 315360000)))

    # MySQL via MAMP socket (Unix) or TCP/IP (Windows/TCP)
    DB_USER = os.getenv('DB_USERNAME', 'root')
    DB_PASS = os.getenv('DB_PASSWORD', 'root')
    DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
    DB_PORT = os.getenv('DB_PORT', '3306')
    DB_NAME = os.getenv('DB_DATABASE', 'negoride')
    DB_SOCKET = os.getenv('DB_SOCKET', '/Applications/MAMP/tmp/mysql/mysql.sock')

    # Build SQLAlchemy connection string
    _base_uri = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    SQLALCHEMY_DATABASE_URI = (
        _base_uri if not os.path.exists(DB_SOCKET)
        else f"{_base_uri}?unix_socket={DB_SOCKET}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Server
    SERVER_HOST = os.getenv('SERVER_HOST', '0.0.0.0')
    SERVER_PORT = int(os.getenv('SERVER_PORT', 5000))

    # Upload settings
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max file upload
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')

    # Flutterwave (primary payment gateway)
    FLW_SECRET_KEY = os.getenv('FLW_SECRET_KEY', '')
    FLW_PUBLIC_KEY = os.getenv('FLW_PUBLIC_KEY', '')
    FLW_ENCRYPTION_KEY = os.getenv('FLW_ENCRYPTION_KEY', '')
    FLW_SECRET_HASH = os.getenv('FLW_SECRET_HASH', '')
    FLW_BASE_URL = os.getenv('FLW_BASE_URL', 'https://api.flutterwave.com')
    FLW_CURRENCY = os.getenv('FLW_CURRENCY', 'NGN')
    FLW_PAYMENT_OPTIONS = os.getenv('FLW_PAYMENT_OPTIONS', 'card,banktransfer,ussd')
    FLW_TIMEOUT = int(os.getenv('FLW_TIMEOUT', 30))

    # Service fee
    SERVICE_FEE_PERCENTAGE = int(os.getenv('SERVICE_FEE_PERCENTAGE', 10))

    # Stripe (legacy — kept for DB column compat, not used for new payments)
    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY', '')
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')

    # OneSignal
    ONESIGNAL_APP_ID = os.getenv('ONESIGNAL_APP_ID', '56ef70cd-45a3-4a66-9838-3146fbbffe77')
    ONESIGNAL_REST_API_KEY = os.getenv('ONESIGNAL_REST_API_KEY', '')

    # App URL
    APP_URL = os.getenv('APP_URL', 'https://negoride.ugnews24.info')
    APP_NAME = os.getenv('APP_NAME', 'Truckeroo Nigeria')

    # SMTP / Email
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USE_SSL = os.getenv('MAIL_USE_SSL', 'false').lower() == 'true'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
    MAIL_FROM_NAME = os.getenv('MAIL_FROM_NAME', 'Truckeroo Nigeria')
    MAIL_FROM_ADDRESS = os.getenv('MAIL_FROM_ADDRESS', os.getenv('MAIL_USERNAME', ''))

"""
Django settings for agriplot project.
Configured for development with structured logging and PostgreSQL database.
"""

from pathlib import Path
import os
import importlib.util
from urllib.parse import parse_qs, unquote, urlparse
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key
import importlib

if importlib.util.find_spec("dj_database_url") is not None:
    dj_database_url = importlib.import_module("dj_database_url")
else:
    dj_database_url = None

if importlib.util.find_spec("decouple") is not None:
    config = importlib.import_module("decouple").config
else:
    def config(name, default=None, cast=None):
        value = os.environ.get(name, default)
        if cast and value is not None:
            return cast(value)
        return value

# Load environment variables from .env file
load_dotenv()

# =============================================================================
# PATH CONFIGURATION
# =============================================================================

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Create necessary directories
LOG_DIR = BASE_DIR / "logs"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"

# Ensure directories exist
for directory in [LOG_DIR, STATIC_ROOT, MEDIA_ROOT]:
    os.makedirs(directory, exist_ok=True)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _env_bool(name: str, default: bool = False) -> bool:
    """
    Parse environment variable as boolean.
    
    Args:
        name: Environment variable name
        default: Default value if variable not set
    
    Returns:
        Boolean value (True for '1', 'true', 'yes', 'on' case-insensitive)
    """
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str = "") -> list:
    """
    Parse environment variable as comma-separated list.
    
    Args:
        name: Environment variable name
        default: Default comma-separated string
    
    Returns:
        List of stripped strings
    """
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _normalize_base_url(value: str, default: str = "https://example.com") -> str:
    """
    Normalize a base URL so the rest of the project can safely build absolute links.

    Accepts values with or without a scheme and removes any trailing slash.
    """
    raw = (value or default).strip()
    if not raw:
        raw = default
    if not raw.startswith(("http://", "https://")):
        raw = f"{'http' if DEBUG else 'https'}://{raw}"
    return raw.rstrip("/")


def _host_from_url(value: str) -> str:
    """Extract the hostname portion from a URL-like value."""
    parsed = urlparse(_normalize_base_url(value))
    return parsed.hostname or ""


def _host_requires_ssl(host: str) -> bool:
    """Return True for managed Postgres hosts that should use SSL."""
    normalized = (host or "").lower()
    if normalized in {"localhost", "127.0.0.1", "::1", ""}:
        return False
    return "supabase.co" in normalized or "pooler.supabase.com" in normalized


def _database_from_url(database_url: str) -> dict:
    """Build a PostGIS Django database config from a Postgres URL."""
    conn_max_age = int(os.environ.get("DB_CONN_MAX_AGE", "600"))
    if dj_database_url:
        database = dj_database_url.parse(
            database_url,
            conn_max_age=conn_max_age,
            engine="django.db.backends.postgresql",
        )
    else:
        parsed = urlparse(database_url)
        database = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/") or "postgres"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or 5432),
            "CONN_MAX_AGE": conn_max_age,
            "OPTIONS": {},
        }
        query = parse_qs(parsed.query)
        if query.get("sslmode"):
            database["OPTIONS"]["sslmode"] = query["sslmode"][-1]

    options = database.setdefault("OPTIONS", {})
    options.setdefault("connect_timeout", int(os.environ.get("DB_CONNECT_TIMEOUT", "10")))

    host = database.get("HOST", "")
    sslmode = os.environ.get("DB_SSLMODE")
    if sslmode:
        options["sslmode"] = sslmode
    elif _env_bool("DB_SSL", default=_host_requires_ssl(host)):
        options.setdefault("sslmode", "require")

    return database


def _database_from_parts() -> dict:
    """Build the default database config from individual DB_* values."""
    host = config("DB_HOST", default="localhost")
    options = {
        "connect_timeout": int(os.environ.get("DB_CONNECT_TIMEOUT", "10")),
    }
    sslmode = os.environ.get("DB_SSLMODE")
    if sslmode:
        options["sslmode"] = sslmode
    elif _env_bool("DB_SSL", default=_host_requires_ssl(host)):
        options["sslmode"] = "require"

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="agriplot"),
        "USER": config("DB_USER", default="postgres"),
        "PASSWORD": config("DB_PASSWORD", default="postgres"),
        "HOST": host,
        "PORT": config("DB_PORT", default="5432"),
        "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "600")),
        "OPTIONS": options,
    }


def _database_config() -> dict:
    """Prefer a DATABASE_URL/SUPABASE_DATABASE_URL, otherwise use DB_* values."""
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DATABASE_URL")
    if database_url:
        return _database_from_url(database_url)
    return _database_from_parts()


# =============================================================================
# CORE SECURITY SETTINGS
# =============================================================================

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or os.environ.get("SECRET_KEY")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = _env_bool("DJANGO_DEBUG", default=False)

if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = get_random_secret_key()
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY (or SECRET_KEY) must be set when DEBUG=False."
        )

# Host/domain validation
ALLOWED_HOSTS = _env_csv(
    "DJANGO_ALLOWED_HOSTS",
    default="localhost,127.0.0.1,::1,testserver" if DEBUG else "",
)
if DEBUG:
    for development_host in [".ngrok-free.dev"]:
        if development_host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(development_host)

# Security middleware settings
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_BROWSER_XSS_FILTER = True

# Conditional SSL/HTTPS settings (enable in production)
SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = _env_bool("DJANGO_SESSION_COOKIE_SECURE", default=False)
CSRF_COOKIE_SECURE = _env_bool("DJANGO_CSRF_COOKIE_SECURE", default=False)

# HTTP Strict Transport Security (HSTS)
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = _env_bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)

# Trust proxy headers (for production behind load balancer)
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# =============================================================================
# AUTHENTICATION & URL REDIRECTS
# =============================================================================

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'


# =============================================================================
# APPLICATION DEFINITION
# =============================================================================

INSTALLED_APPS = [
    # Third Party Admin Theme - MUST BE FIRST
    'jazzmin',  # django-jazzmin admin theme
    # Django Core Apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",  # PostgreSQL specific features
    "django.contrib.sitemaps",

    # Local Apps
    "accounts",
    "authentication",
    "security",
    "verification",
    "notifications",
    "listings",
    "crops",
    "payments",
    "registry_mock",
    "reports",
    "transactions",
]

OPTIONAL_APPS = [
    "django_extensions",
    "formtools",
]

for app_label in reversed(OPTIONAL_APPS):
    if importlib.util.find_spec(app_label):
        INSTALLED_APPS.insert(0, app_label)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "payments.middleware.LeaseLifecycleHeartbeatMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    
    # Security middleware (in correct order)
    'security.middleware.SecurityHeadersMiddleware',  # Add security headers
    'security.middleware.EnforceTwoFactorEnrollmentMiddleware',  # Enforce 2FA
    'security.middleware.AuditLogMiddleware',  # Auto-audit all requests
]

# 2FA Settings
REQUIRE_2FA = True  # Require 2FA for all users
REQUIRE_2FA_ENROLLMENT = True  # Force enrollment

ROOT_URLCONF = "agriplot.urls"

WSGI_APPLICATION = "agriplot.wsgi.application"


# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
#
# Priority order for 'default' database:
#   1. DATABASE_URL env var  (Render, Railway, Heroku, etc.)
#   2. SUPABASE_DATABASE_URL env var
#   3. Individual DB_* env vars (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, ...)
#
# In production, set DATABASE_URL in your .env:
#   DATABASE_URL=postgresql://user:password@host:5432/dbname
#
# _database_config() is defined above and handles all three cases automatically.

DATABASES = {
    "default": _database_config(),
}

# Optional: keep Supabase as a named secondary connection (for scripts/migration)
_supabase_password = os.getenv("SUPABASE_DB_PASSWORD")
if _supabase_password:
    DATABASES["supabase"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("SUPABASE_DB_NAME", "postgres"),
        "USER": os.getenv("SUPABASE_DB_USER", ""),
        "PASSWORD": _supabase_password,
        "HOST": os.getenv("SUPABASE_DB_HOST", "aws-0-eu-west-1.pooler.supabase.com"),
        "PORT": os.getenv("SUPABASE_DB_PORT", "5432"),
        "CONN_MAX_AGE": int(os.getenv("SUPABASE_DB_CONN_MAX_AGE", "300")),
        "OPTIONS": {
            "sslmode": os.getenv("SUPABASE_DB_SSLMODE", "require"),
            "connect_timeout": int(os.getenv("SUPABASE_DB_CONNECT_TIMEOUT", "10")),
        },
    }



# =============================================================================
# TEMPLATE CONFIGURATION
# =============================================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "builtins": ["listings.templatetags.custom_filters"],
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "notifications.context_processors.nav_activity",
                "security.context_processors.contact_verification_banner",
                'payments.context_processors.wallet_balance',
            ],
        },
    },
]


# =============================================================================
# PASSWORD VALIDATION
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# =============================================================================
# INTERNATIONALIZATION
# =============================================================================

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True


# =============================================================================
# STATIC & MEDIA FILES
# =============================================================================

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files (User uploads)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# =============================================================================
# SESSION MANAGEMENT
# =============================================================================

SESSION_COOKIE_AGE = 600  # 10 minutes of inactivity
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True


# =============================================================================
# DEFAULT PRIMARY KEY FIELD TYPE
# =============================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# =============================================================================
# EMAIL CONFIGURATION
# =============================================================================

EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND', 
    'django.core.mail.backends.smtp.EmailBackend'
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = _env_bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
# Fallback to console backend if SMTP credentials are not set
if not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = os.environ.get(
    'DEFAULT_FROM_EMAIL', 
    'AgriPlot Connect <[EMAIL_ADDRESS]>'
)
SITE_URL = _normalize_base_url(
    os.environ.get("SITE_URL"),
    default="http://127.0.0.1:8000" if DEBUG else "https://example.com",
)
if not DEBUG and not os.environ.get("SITE_URL"):
    raise ImproperlyConfigured("SITE_URL must be set when DEBUG=False.")
SITE_HOST = _host_from_url(SITE_URL)

if SITE_HOST and SITE_HOST not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(SITE_HOST)

CSRF_TRUSTED_ORIGINS = _env_csv("DJANGO_CSRF_TRUSTED_ORIGINS")
if SITE_URL and SITE_URL not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(SITE_URL)


# =============================================================================
# SMS CONFIGURATION
# =============================================================================

SMS_PROVIDER = os.environ.get('SMS_PROVIDER', 'opensms').strip().lower()

OPENSMS_API_URL = os.environ.get(
    'OPENSMS_API_URL',
    'https://api.opensms.co.ke/v3/sms/send'
).strip()
OPENSMS_API_TOKEN = os.environ.get('OPENSMS_API_TOKEN', '').strip()
OPENSMS_SENDER_ID = os.environ.get('OPENSMS_SENDER_ID', 'AgriPlot').strip()


# =============================================================================
# EXTERNAL API CONFIGURATION
# =============================================================================

# Ardhiasa API (Land verification)
ARDHISASA_API_URL = os.environ.get("ARDHISASA_API_URL", "")
ARDHISASA_API_KEY = os.environ.get("ARDHISASA_API_KEY", "")
ARDHISASA_MODE = os.environ.get("ARDHISASA_MODE", "mock")  # mock | live
ARDHISASA_WEBHOOK_URL = os.environ.get(
    "ARDHISASA_WEBHOOK_URL",
    f"{SITE_URL}/webhooks/ardhisasa/",
)


# =============================================================================
# FIREBASE CONFIGURATION
# =============================================================================

# Absolute path to the Firebase service account JSON key file.
# Download from: Firebase Console → Project Settings → Service accounts
#                → Generate new private key
# Keep this file OUT of version control (.gitignore already covers it).
FIREBASE_CREDENTIALS_PATH = os.environ.get("FIREBASE_CREDENTIALS_PATH", "")

# Firebase project ID (visible in Firebase Console URL, e.g. "agriplot-connect")
FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "")



# =============================================================================
# PAYMENT GATEWAY CONFIGURATION
# =============================================================================

PAYMENT_PROVIDER = os.environ.get("PAYMENT_PROVIDER", "daraja").lower()

MPESA_CONSUMER_KEY = os.environ.get("MPESA_CONSUMER_KEY", "")
MPESA_CONSUMER_SECRET = os.environ.get("MPESA_CONSUMER_SECRET", "")
MPESA_BUSINESS_SHORTCODE = os.environ.get("MPESA_BUSINESS_SHORTCODE", "")
MPESA_PASSKEY = os.environ.get("MPESA_PASSKEY", "")
MPESA_ENVIRONMENT = os.environ.get("MPESA_ENVIRONMENT", "sandbox").lower()
MPESA_TRANSACTION_TYPE = os.environ.get(
    "MPESA_TRANSACTION_TYPE",
    "CustomerPayBillOnline",
)
MPESA_CALLBACK_URL = os.environ.get("MPESA_CALLBACK_URL", "")
MPESA_TEST_MODE = _env_bool("MPESA_TEST_MODE", default=False)

CARD_PAYMENTS_ENABLED = _env_bool("CARD_PAYMENTS_ENABLED", default=False)
CARD_PROVIDER = os.environ.get("CARD_PROVIDER", "")
CARD_PUBLIC_KEY = os.environ.get("CARD_PUBLIC_KEY", "")
CARD_SECRET_KEY = os.environ.get("CARD_SECRET_KEY", "")
CARD_WEBHOOK_SECRET = os.environ.get("CARD_WEBHOOK_SECRET", "")

BANK_TRANSFER_ENABLED = _env_bool("BANK_TRANSFER_ENABLED", default=False)
BANK_TRANSFER_PROVIDER = os.environ.get("BANK_TRANSFER_PROVIDER", "jenga").lower()
BANK_TRANSFER_API_BASE_URL = os.environ.get("BANK_TRANSFER_API_BASE_URL", "https://jengaapi.io")
BANK_TRANSFER_API_PATH = os.environ.get("BANK_TRANSFER_API_PATH", "/v3/transaction/sendmoney")
BANK_TRANSFER_AUTH_API_BASE_URL = os.environ.get("BANK_TRANSFER_AUTH_API_BASE_URL", "https://api.finserve.africa")
BANK_TRANSFER_AUTH_API_PATH = os.environ.get(
    "BANK_TRANSFER_AUTH_API_PATH",
    "/authentication/api/v3/authenticate/merchant",
)
BANK_TRANSFER_SOURCE_COUNTRY_CODE = os.environ.get("BANK_TRANSFER_SOURCE_COUNTRY_CODE", "KE")
BANK_TRANSFER_DESTINATION_COUNTRY_CODE = os.environ.get("BANK_TRANSFER_DESTINATION_COUNTRY_CODE", "KE")
BANK_TRANSFER_SOURCE_ACCOUNT_NUMBER = os.environ.get("BANK_TRANSFER_SOURCE_ACCOUNT_NUMBER", "")
BANK_TRANSFER_SOURCE_ACCOUNT_NAME = os.environ.get("BANK_TRANSFER_SOURCE_ACCOUNT_NAME", "")
BANK_TRANSFER_BEARER_TOKEN = os.environ.get("BANK_TRANSFER_BEARER_TOKEN", "")
BANK_TRANSFER_SIGNATURE_ALGORITHM = os.environ.get("BANK_TRANSFER_SIGNATURE_ALGORITHM", "rsa").lower()
BANK_TRANSFER_PRIVATE_KEY_PATH = os.environ.get("BANK_TRANSFER_PRIVATE_KEY_PATH", "")
BANK_TRANSFER_PRIVATE_KEY_PASSWORD = os.environ.get("BANK_TRANSFER_PRIVATE_KEY_PASSWORD", "")
BANK_TRANSFER_WEBHOOK_SECRET = os.environ.get("BANK_TRANSFER_WEBHOOK_SECRET", "")
BANK_TRANSFER_CALLBACK_PUBLIC_KEY_PATH = os.environ.get("BANK_TRANSFER_CALLBACK_PUBLIC_KEY_PATH", "")
BANK_TRANSFER_CALLBACK_SIGNATURE_HEADER = os.environ.get("BANK_TRANSFER_CALLBACK_SIGNATURE_HEADER", "X-Signature")
BANK_TRANSFER_CALLBACK_VERIFY_SIGNATURE = _env_bool("BANK_TRANSFER_CALLBACK_VERIFY_SIGNATURE", default=False)
BANK_TRANSFER_PESALINK_LIMIT = os.environ.get("BANK_TRANSFER_PESALINK_LIMIT", "999999.00")
BANK_TRANSFER_TIMEOUT_SECONDS = int(os.environ.get("BANK_TRANSFER_TIMEOUT_SECONDS", "30"))
BANK_TRANSFER_BANK_NAME = os.environ.get("BANK_TRANSFER_BANK_NAME", "")
BANK_TRANSFER_ACCOUNT_NAME = os.environ.get("BANK_TRANSFER_ACCOUNT_NAME", "")
BANK_TRANSFER_ACCOUNT_NUMBER = os.environ.get("BANK_TRANSFER_ACCOUNT_NUMBER", "")
BANK_TRANSFER_SWIFT_CODE = os.environ.get("BANK_TRANSFER_SWIFT_CODE", "")
BANK_TRANSFER_SENDER_NAME = os.environ.get("BANK_TRANSFER_SENDER_NAME", "")
BANK_TRANSFER_SENDER_DOCUMENT_TYPE = os.environ.get("BANK_TRANSFER_SENDER_DOCUMENT_TYPE", "")
BANK_TRANSFER_SENDER_DOCUMENT_NUMBER = os.environ.get("BANK_TRANSFER_SENDER_DOCUMENT_NUMBER", "")
BANK_TRANSFER_SENDER_COUNTRY_CODE = os.environ.get("BANK_TRANSFER_SENDER_COUNTRY_CODE", "KE")
BANK_TRANSFER_SENDER_MOBILE_NUMBER = os.environ.get("BANK_TRANSFER_SENDER_MOBILE_NUMBER", "")
BANK_TRANSFER_SENDER_EMAIL = os.environ.get("BANK_TRANSFER_SENDER_EMAIL", "")
BANK_TRANSFER_SENDER_ADDRESS = os.environ.get("BANK_TRANSFER_SENDER_ADDRESS", "")
BANK_TRANSFER_DESTINATION_DOCUMENT_TYPE = os.environ.get("BANK_TRANSFER_DESTINATION_DOCUMENT_TYPE", "")
BANK_TRANSFER_DESTINATION_DOCUMENT_NUMBER = os.environ.get("BANK_TRANSFER_DESTINATION_DOCUMENT_NUMBER", "")
BANK_TRANSFER_DESTINATION_MOBILE_NUMBER = os.environ.get("BANK_TRANSFER_DESTINATION_MOBILE_NUMBER", "")
BANK_TRANSFER_DESTINATION_EMAIL = os.environ.get("BANK_TRANSFER_DESTINATION_EMAIL", "")
BANK_TRANSFER_DESTINATION_ADDRESS = os.environ.get("BANK_TRANSFER_DESTINATION_ADDRESS", "")

# ===============================================================================
# JENGA SPECIFIC CONFIGURATION
# ===============================================================================

# Jenga API Configuration
JENGA_ENVIRONMENT = os.environ.get('JENGA_ENVIRONMENT', 'sandbox')  # sandbox or live
JENGA_API_BASE_URL = os.environ.get('JENGA_API_BASE_URL', 'https://uat.jengahq.io/api/v3')
JENGA_API_KEY = os.environ.get('JENGA_API_KEY', '')
JENGA_API_SECRET = os.environ.get('JENGA_API_SECRET', '')
JENGA_MERCHANT_CODE = os.environ.get('JENGA_MERCHANT_CODE', '')
JENGA_WEBHOOK_SECRET = os.environ.get('JENGA_WEBHOOK_SECRET', '')  # For signature verification

# Corporate Account Details
JENGA_CORPORATE_ACCOUNT_NUMBER = os.environ.get('JENGA_CORPORATE_ACCOUNT_NUMBER', '')
JENGA_CORPORATE_ACCOUNT_NAME = os.environ.get('JENGA_CORPORATE_ACCOUNT_NAME', '')
JENGA_CORPORATE_BANK_CODE = os.environ.get('JENGA_CORPORATE_BANK_CODE', '')  # e.g., '68' for Equity

# C2B Configuration
JENGA_PAYBILL_NUMBER = os.environ.get('JENGA_PAYBILL_NUMBER', '')  # For M-Pesa style payments
JENGA_TILL_NUMBER = os.environ.get('JENGA_TILL_NUMBER', '')  # For card/Till payments
JENGA_CHECKOUT_REDIRECT_URL = os.environ.get('JENGA_CHECKOUT_REDIRECT_URL', '')
JENGA_WEBHOOK_C2B_URL = os.environ.get('JENGA_WEBHOOK_C2B_URL', '')
JENGA_WEBHOOK_B2C_URL = os.environ.get('JENGA_WEBHOOK_B2C_URL', '')
JENGA_WEBHOOK_B2B_URL = os.environ.get('JENGA_WEBHOOK_B2B_URL', '')
AIRTEL_MONEY_ENABLED = _env_bool("AIRTEL_MONEY_ENABLED", default=False)
AIRTEL_MONEY_CLIENT_ID = os.environ.get("AIRTEL_MONEY_CLIENT_ID", "")
AIRTEL_MONEY_CLIENT_SECRET = os.environ.get("AIRTEL_MONEY_CLIENT_SECRET", "")
AIRTEL_MONEY_CALLBACK_URL = os.environ.get("AIRTEL_MONEY_CALLBACK_URL", "")

WALLET_ENABLED = _env_bool("WALLET_ENABLED", default=True)
WALLET_MPESA_CALLBACK_URL = os.environ.get("WALLET_MPESA_CALLBACK_URL", "")

# Enable test mode for wallet deposits only.
WALLET_TEST_MODE = _env_bool("WALLET_TEST_MODE", default=False)

# =============================================================================
# CELERY CONFIGURATION
# =============================================================================

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or None
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = _env_bool("CELERY_TASK_TRACK_STARTED", default=False)
CELERY_TASK_IGNORE_RESULT = _env_bool("CELERY_TASK_IGNORE_RESULT", default=True)
CELERY_TASK_TIME_LIMIT = 300  # 5 minutes hard limit per task
CELERY_TASK_SOFT_TIME_LIMIT = 240
# Retry failed tasks with exponential backoff
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1


# =============================================================================
# FEATURE FLAGS & SECURITY CONTROLS
# =============================================================================

# Verification requirements
REQUIRE_CONTACT_VERIFICATION = _env_bool("REQUIRE_CONTACT_VERIFICATION", default=False)
REQUIRE_2FA_FOR_LISTING = _env_bool("REQUIRE_2FA_FOR_LISTING", default=False)
REQUIRE_DOCUMENT_VERIFICATION = _env_bool("REQUIRE_DOCUMENT_VERIFICATION", default=False)
REQUIRE_2FA = _env_bool("REQUIRE_2FA", default=False)
REQUIRE_2FA_ENROLLMENT = _env_bool("REQUIRE_2FA_ENROLLMENT", default=False)

# Rate limiting
PLOT_CREATE_RATE_LIMIT = int(os.environ.get("PLOT_CREATE_RATE_LIMIT", "0"))

# OTP / verification settings
OTP_PROVIDER = os.environ.get("OTP_PROVIDER", "email")  # email | sms | both
PHONE_OTP_VERIFICATION_ENABLED = _env_bool("PHONE_OTP_VERIFICATION_ENABLED", default=False)
USE_SMS_MOCK = _env_bool("USE_SMS_MOCK", default=True)
ENABLE_SMS_NOTIFICATIONS = _env_bool("ENABLE_SMS_NOTIFICATIONS", default=False)
NOTIFICATION_DELAY_SECONDS = int(os.environ.get("NOTIFICATION_DELAY_SECONDS", "60"))
SMS_HTTP_RETRIES = int(os.environ.get("SMS_HTTP_RETRIES", "1"))
SMS_REQUEST_TIMEOUT = float(os.environ.get("SMS_REQUEST_TIMEOUT", "5"))
SMS_READ_TIMEOUT = float(os.environ.get("SMS_READ_TIMEOUT", "8"))


# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

LOGS_WRITABLE = os.access(LOG_DIR, os.W_OK)
LOG_FILE = LOG_DIR / "app.log"
ERROR_LOG_FILE = LOG_DIR / "errors.log"
LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "DEBUG" if DEBUG else "INFO").upper()
ERROR_LOG_LEVEL = os.environ.get("DJANGO_ERROR_LOG_LEVEL", "ERROR").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{levelname} | {asctime} | {name} | {module}.{funcName}:{lineno} | {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": LOG_LEVEL,
            "formatter": "standard",
        },
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_FILE,
            "level": LOG_LEVEL,
            "formatter": "standard",
            "maxBytes": 10485760,
            "backupCount": 5,
        } if LOGS_WRITABLE else {
            "class": "logging.StreamHandler",
            "level": LOG_LEVEL,
            "formatter": "standard",
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": ERROR_LOG_FILE,
            "level": ERROR_LOG_LEVEL,
            "formatter": "standard",
            "maxBytes": 10485760,
            "backupCount": 10,
        } if LOGS_WRITABLE else {
            "class": "logging.StreamHandler",
            "level": ERROR_LOG_LEVEL,
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console", "app_file", "error_file"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django.request": {
            "handlers": ["console", "error_file"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console", "error_file"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["error_file"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console", "error_file"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}


# =============================================================================
# JAZZMIN ADMIN THEME CONFIGURATION
# =============================================================================

JAZZMIN_SETTINGS = {
    # Site branding
    "site_title": "AgriPlot Admin",
    "site_header": "AgriPlot Administration",
    "site_brand": "AgriPlot",
    "site_logo": None,
    "login_logo": None,
    "login_logo_dark": None,
    "site_icon": None,
    "welcome_sign": "Welcome to AgriPlot Admin",
    "copyright": "AgriPlot Ltd",
    
    # User avatar
    "user_avatar": None,
    
    # Top menu
    "topmenu_links": [
        {"name": "Home", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"name": "View Site", "url": "/", "new_window": True},
        {"app": "listings", "label": "Listings"},
    ],
    
    # Side menu
    "navigation_expanded": True,
    
    # Custom icons per app/model (adjust app names as needed)
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "auth.group": "fas fa-users",
        "accounts.Profile": "fas fa-id-card",
        "accounts.LandownerProfile": "fas fa-user-tie",
        "accounts.Agent": "fas fa-handshake",
        "verification.ExtensionOfficer": "fas fa-leaf",
        "verification.LandSurveyor": "fas fa-ruler-combined",
        "listings.Plot": "fas fa-map-marked-alt",
        "verification.SurveyorReport": "fas fa-file-signature",
        "verification.ExtensionReport": "fas fa-file-alt",
        "listings.MarketPriceBand": "fas fa-chart-line",
        "listings.ComparableSale": "fas fa-balance-scale",
        "listings.ContactRequest": "fas fa-envelope",
        "listings.UserInterest": "fas fa-heart",
        "security.AuditLog": "fas fa-shield-alt",
        "verification.DocumentVerification": "fas fa-file-contract",
        "security.ImpersonationDetection": "fas fa-user-secret",
        "security.PhoneEmailVerification": "fas fa-key",
        "security.DocumentHash": "fas fa-fingerprint",
        "security.EmailOTP": "fas fa-lock",
        "verification.VerificationStatus": "fas fa-check-circle",
        "verification.VerificationTask": "fas fa-tasks",
        "verification.VerificationLog": "fas fa-clipboard-list",
        "listings.PriceComparable": "fas fa-chart-bar",
        "listings.PricingSuggestion": "fas fa-tag",
        "verification.TitleSearchResult": "fas fa-search",
        "verification.VerificationDocument": "fas fa-file-pdf",
        # Payments
        "payments.Wallet": "fas fa-wallet",
        "payments.WalletTransaction": "fas fa-exchange-alt",
        "payments.PaymentRequest": "fas fa-credit-card",
        "payments.BankTransferRequest": "fas fa-university",
        # Transactions
        "transactions.Transaction": "fas fa-file-contract",
        "transactions.TransactionMilestone": "fas fa-flag-checkered",
        # Crops
        "crops.CropProfile": "fas fa-seedling",
    },
    
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",
    
    "custom_links": {
        "listings": [
            {
                "name": "System Journal",
                "url": "/verify/system-construction/",
                "icon": "fas fa-journal-whills",
                "permissions": ["listings.view_verificationstatus"],
            }
        ]
    },
    
    "order_with_respect_to": [
        "auth",
        "accounts.Profile",
        "accounts.LandownerProfile",
        "verification.LandSurveyor",
        "verification.SurveyorReport",
        "accounts.Agent",
        "security.PhoneEmailVerification",
        "security.EmailOTP",
        "listings.Plot",
        "verification.ExtensionOfficer",
        "verification.ExtensionReport",
        "listings.MarketPriceBand",
        "listings.ComparableSale",
        "listings.ContactRequest",
        "listings.UserInterest",
        "security.AuditLog",
        "verification.DocumentVerification",
        "security.DocumentHash",
        "security.ImpersonationDetection",
        "verification.VerificationStatus",
        "verification.VerificationTask",
        "verification.VerificationLog",
        "payments",
        "transactions",
        "crops",
    ],
    
    "show_ui_builder": DEBUG,
    "changeform_format": "horizontal_tabs",
    "language_chooser": False,
}

# Jazzmin UI tweaks
JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": "navbar-primary",
    "accent": "accent-primary",
    "navbar": "navbar-white navbar-light",
    "no_navbar_border": False,
    "navbar_fixed": True,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": True,
    "sidebar": "sidebar-dark-primary",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": False,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,
    "theme": "default",
    "dark_mode_theme": None,
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
    "actions_sticky_top": True,
}

# =============================================================================
# FILE UPLOAD LIMITS
# =============================================================================

# Increase max memory sizes for data and file uploads (50MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800

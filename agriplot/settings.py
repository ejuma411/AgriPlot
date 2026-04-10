"""
Django settings for agriplot project.
Configured for development with structured logging and PostgreSQL database.
"""

from pathlib import Path
import os
import logging
from urllib.parse import urlparse
from dotenv import load_dotenv
from django.core.management.utils import get_random_secret_key
from decouple import config

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


def _normalize_base_url(value: str, default: str = "http://127.0.0.1:8000") -> str:
    """
    Normalize a base URL so the rest of the project can safely build absolute links.

    Accepts values with or without a scheme and removes any trailing slash.
    """
    raw = (value or default).strip()
    if not raw:
        raw = default
    if not raw.startswith(("http://", "https://")):
        raw = f"http://{raw}"
    return raw.rstrip("/")


def _host_from_url(value: str) -> str:
    """Extract the hostname portion from a URL-like value."""
    parsed = urlparse(_normalize_base_url(value))
    return parsed.hostname or ""


# =============================================================================
# CORE SECURITY SETTINGS
# =============================================================================

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = (
    os.environ.get("DJANGO_SECRET_KEY")
    or os.environ.get("SECRET_KEY")
    or get_random_secret_key()
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = _env_bool("DJANGO_DEBUG", default=False)

# Host/domain validation
ALLOWED_HOSTS = _env_csv("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1,testserver")

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
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'


# =============================================================================
# APPLICATION DEFINITION
# =============================================================================

INSTALLED_APPS = [
    # Admin interface enhancement (must come before django.contrib.admin)
    "jazzmin",
    
    # Django Core Apps
    'django_extensions',
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",  # PostgreSQL specific features

    # Third Party Apps
    "formtools",

    # Local Apps
    "accounts",
    "authentication",
    "security",
    "verification",
    "notifications",
    "listings",
    "payments",
    "registry_mock",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "payments.middleware.LeaseLifecycleHeartbeatMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "security.middleware.EnforceTwoFactorEnrollmentMiddleware",
]

ROOT_URLCONF = "agriplot.urls"

WSGI_APPLICATION = "agriplot.wsgi.application"


# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
        
        # Connection pooling and performance settings
        'CONN_MAX_AGE': 600,  # Keep connections alive for 10 minutes
        'OPTIONS': {
            'connect_timeout': 10,  # Connection timeout in seconds
        },
    }
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
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "notifications.context_processors.nav_activity",
                "payments.context_processors.payment_admin_nav",
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
STATIC_URL = "static/"
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
DEFAULT_FROM_EMAIL = os.environ.get(
    'DEFAULT_FROM_EMAIL', 
    'AgriPlot Connect <noreply@agriplot.com>'
)
SITE_URL = _normalize_base_url(os.environ.get("SITE_URL"))
SITE_HOST = _host_from_url(SITE_URL)

if SITE_HOST and SITE_HOST not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(SITE_HOST)

CSRF_TRUSTED_ORIGINS = _env_csv("DJANGO_CSRF_TRUSTED_ORIGINS")
if SITE_URL and SITE_URL not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(SITE_URL)


# =============================================================================
# SMS CONFIGURATION
# =============================================================================

SMS_PROVIDER = os.environ.get('SMS_PROVIDER', 'textsms').lower()

TEXTSMS_PARTNER_ID = os.environ.get('TEXTSMS_PARTNER_ID', '')
TEXTSMS_API_KEY = os.environ.get('TEXTSMS_API_KEY', '')
TEXTSMS_SENDER_ID = os.environ.get('TEXTSMS_SENDER_ID', 'AgriPlot')
TEXTSMS_API_URL = os.environ.get(
    'TEXTSMS_API_URL',
    'https://sms.textsms.co.ke/api/services/sendsms/'
)

OPENSMS_API_URL = os.environ.get(
    'OPENSMS_API_URL',
    'https://api.opensms.co.ke/v3/sms/send'
)
OPENSMS_API_TOKEN = os.environ.get('OPENSMS_API_TOKEN', '')
OPENSMS_SENDER_ID = os.environ.get('OPENSMS_SENDER_ID', 'AgriPlot')


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
# PAYMENT GATEWAY CONFIGURATION
# =============================================================================

PAYMENT_PROVIDER = os.environ.get("PAYMENT_PROVIDER", "daraja").lower()

PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_BASE_URL = os.environ.get("PAYSTACK_BASE_URL", "https://api.paystack.co")
PAYSTACK_CURRENCY = os.environ.get("PAYSTACK_CURRENCY", "KES")
PAYSTACK_ENABLED = _env_bool("PAYSTACK_ENABLED", default=False)
PAYSTACK_AUTO_RELEASE_TEST_DEALS = _env_bool(
    "PAYSTACK_AUTO_RELEASE_TEST_DEALS",
    default=DEBUG,
)

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
USE_SMS_MOCK = _env_bool("USE_SMS_MOCK", default=True)


# =============================================================================
# ENHANCED LOGGING CONFIGURATION
# =============================================================================

# Log file paths
ERROR_LOG_FILE = LOG_DIR / "error.log"
DEBUG_LOG_FILE = LOG_DIR / "debug.log"
DJANGO_LOG_FILE = LOG_DIR / "django.log"
LISTINGS_LOG_FILE = LOG_DIR / "listings.log"
SECURITY_LOG_FILE = LOG_DIR / "security.log"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "verbose": {
            "format": "{levelname} | {asctime} | {name} | {module}:{lineno} | {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "detailed": {
            "format": "{levelname} | {asctime} | {name} | {module}.{funcName}:{lineno} | {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "simple": {
            "format": "{levelname} | {asctime} | {message}",
            "style": "{",
            "datefmt": "%H:%M:%S",
        },
        "security": {
            "format": "{levelname} | {asctime} | SECURITY | {module}:{lineno} | {message} | User: {user} | IP: {ip}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },

    "filters": {
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        },
        "require_debug_false": {
            "()": "django.utils.log.RequireDebugFalse",
        },
    },

    "handlers": {
        # Console Handler - shows all logs in terminal
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple" if DEBUG else "verbose",
            "level": "DEBUG" if DEBUG else "INFO",
        },

        # Error Handler - captures all ERROR and above
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": ERROR_LOG_FILE,
            "formatter": "detailed",
            "level": "ERROR",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
        },

        # Debug File Handler - detailed debugging
        "debug_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": DEBUG_LOG_FILE,
            "formatter": "detailed",
            "level": "DEBUG",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 3,
        },

        # Django-specific log file
        "django_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": DJANGO_LOG_FILE,
            "formatter": "verbose",
            "level": "INFO",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 3,
        },

        # Listings app specific log file
        "listings_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LISTINGS_LOG_FILE,
            "formatter": "detailed",
            "level": "DEBUG",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
        },

        # Security events log file
        "security_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": SECURITY_LOG_FILE,
            "formatter": "security",
            "level": "INFO",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
        },

        # Mail handler for critical errors (production only)
        "mail_admins": {
            "class": "django.utils.log.AdminEmailHandler",
            "level": "ERROR",
            "filters": ["require_debug_false"],
            "include_html": True,
        },
    },

    "loggers": {
        # Root logger - captures everything
        "": {
            "handlers": ["console", "error_file"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": True,
        },

        # Django Framework Logs
        "django": {
            "handlers": ["console", "django_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },

        # Django Request/Response logs (includes 4xx and 5xx errors)
        "django.request": {
            "handlers": ["error_file", "console"],
            "level": "ERROR",
            "propagate": False,
        },

        # Django Server logs
        "django.server": {
            "handlers": ["error_file", "console"],
            "level": "ERROR",
            "propagate": False,
        },

        # Django DB logs (SQL queries when DEBUG=True)
        "django.db.backends": {
            "handlers": ["debug_file"],
            "level": "DEBUG" if DEBUG else "WARNING",
            "propagate": False,
        },

        # Django Security logs
        "django.security": {
            "handlers": ["security_file", "error_file", "console"],
            "level": "INFO",
            "propagate": False,
        },

        # Listings App - all logs from your app
        "listings": {
            "handlers": ["console", "listings_file", "error_file"],
            "level": "DEBUG",
            "propagate": False,
        },

        # Forms and Validation errors
        "django.contrib.messages": {
            "handlers": ["console", "debug_file"],
            "level": "INFO",
            "propagate": False,
        },

        # Authentication logs
        "django.contrib.auth": {
            "handlers": ["console", "security_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },

        # Validation logging
        "listings.validation": {
            "handlers": ["debug_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },

        # Third-party apps (set to WARNING to reduce noise)
        "formtools": {
            "handlers": ["error_file"],
            "level": "WARNING",
            "propagate": False,
        },
        "jazzmin": {
            "handlers": ["error_file"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

# Create custom loggers
validation_logger = logging.getLogger('listings.validation')
security_logger = logging.getLogger('django.security')


# =============================================================================
# JAZZMIN ADMIN CUSTOMIZATION
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
    
    # Custom icons per app/model
    "icons": {
        # Auth app
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "auth.group": "fas fa-users",
        
        # Listings app models
        "listings.Profile": "fas fa-id-card",
        "listings.LandownerProfile": "fas fa-user-tie",
        "listings.Agent": "fas fa-handshake",
        "listings.ExtensionOfficer": "fas fa-leaf",
        "listings.LandSurveyor": "fas fa-ruler-combined",
        "listings.Plot": "fas fa-map-marked-alt",
        "listings.SurveyorReport": "fas fa-file-signature",
        "listings.ExtensionReport": "fas fa-file-alt",
        "listings.MarketPriceBand": "fas fa-chart-line",
        "listings.ComparableSale": "fas fa-balance-scale",
        "listings.ContactRequest": "fas fa-envelope",
        "listings.UserInterest": "fas fa-heart",
        "listings.AuditLog": "fas fa-shield-alt",
        "listings.DocumentVerification": "fas fa-file-contract",
        "listings.ImpersonationDetection": "fas fa-user-secret",
        "listings.PhoneEmailVerification": "fas fa-key",
        "listings.DocumentHash": "fas fa-fingerprint",
        "listings.EmailOTP": "fas fa-lock",
        "listings.VerificationStatus": "fas fa-check-circle",
        "listings.VerificationTask": "fas fa-tasks",
        "listings.VerificationLog": "fas fa-clipboard-list",
        "listings.PriceComparable": "fas fa-chart-bar",
        "listings.PricingSuggestion": "fas fa-tag",
        "listings.PlotReaction": "fas fa-thumbs-up",
        "listings.TitleSearchResult": "fas fa-search",
        "listings.VerificationDocument": "fas fa-file-pdf",
    },
    
    # Icons for default models
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",
    
    # Custom links to append to app groups
    "custom_links": {
        "listings": [
            {
                "name": "System Journal",
                "url": "system_construction_journal",
                "icon": "fas fa-journal-whills",
                "permissions": ["listings.view_verificationstatus"],
            }
        ]
    },
    
    # Menu structure (order and grouping)
    "order_with_respect_to": [
        "auth",
        "listings.Profile",
        "listings.LandownerProfile",
        "listings.LandSurveyor",
        "listings.SurveyorReport",
        "listings.Agent",
        "listings.PhoneEmailVerification",
        "listings.EmailOTP",
        "listings.Plot",
        "listings.ExtensionOfficer",
        "listings.ExtensionReport",
        "listings.MarketPriceBand",
        "listings.ComparableSale",
        "listings.ContactRequest",
        "listings.UserInterest",
        "listings.AuditLog",
        "listings.DocumentVerification",
        "listings.DocumentHash",
        "listings.ImpersonationDetection",
        "listings.VerificationStatus",
        "listings.VerificationTask",
        "listings.VerificationLog",
    ],
    
    # Custom menu structure
    "menu": [
        {"app": "auth", "label": "Users & Groups", "icon": "fas fa-users-cog"},
        {
            "label": "User Profiles",
            "icon": "fas fa-id-card",
            "models": [
                "listings.Profile",
                "listings.LandownerProfile",
                "listings.Agent",
                "listings.ExtensionOfficer",
                "listings.LandSurveyor",
            ],
        },
        {
            "label": "Land Management",
            "icon": "fas fa-map-marked-alt",
            "models": [
                "listings.Plot",
                "listings.VerificationDocument",
                "listings.TitleSearchResult",
            ],
        },
        {
            "label": "Verification & Reports",
            "icon": "fas fa-clipboard-check",
            "models": [
                "listings.VerificationStatus",
                "listings.VerificationTask",
                "listings.VerificationLog",
                "listings.ExtensionReport",
                "listings.SurveyorReport",
            ],
        },
        {
            "label": "Market Analysis",
            "icon": "fas fa-chart-line",
            "models": [
                "listings.MarketPriceBand",
                "listings.ComparableSale",
                "listings.PriceComparable",
                "listings.PricingSuggestion",
            ],
        },
        {
            "label": "Engagement",
            "icon": "fas fa-comments",
            "models": [
                "listings.ContactRequest",
                "listings.UserInterest",
                "listings.PlotReaction",
            ],
        },
        {
            "label": "Security & Compliance",
            "icon": "fas fa-shield-alt",
            "models": [
                "listings.AuditLog",
                "listings.DocumentVerification",
                "listings.ImpersonationDetection",
                "listings.PhoneEmailVerification",
                "listings.DocumentHash",
                "listings.EmailOTP",
            ],
        },
    ],
    
    # UI Customization
    "show_ui_builder": DEBUG,
    "changeform_format": "horizontal_tabs",
    "language_chooser": False,
}

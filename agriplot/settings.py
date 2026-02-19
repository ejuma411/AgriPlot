"""
Django settings for agriplot project.
Configured for development with structured logging.
"""

from pathlib import Path
import os
from dotenv import load_dotenv
load_dotenv() 

# Authentication URLs
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# =============================================================================
# BASE DIRECTORY
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent.parent


# =============================================================================
# SECURITY SETTINGS
# =============================================================================

SECRET_KEY = "django-insecure-lej7c!(e^gslp%rblu7%b0gny9vdd2v#2175qw29^q2*$0$u=i"

DEBUG = True

ALLOWED_HOSTS = ["*"]


# =============================================================================
# APPLICATION DEFINITION
# =============================================================================

INSTALLED_APPS = [
    "jazzmin",  # Admin interface enhancement
    # Django Core Apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third Party Apps
    "formtools",

    # Local Apps
    "listings",
]


# =============================================================================
# MIDDLEWARE CONFIGURATION
# =============================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# =============================================================================
# URL & WSGI CONFIG
# =============================================================================

ROOT_URLCONF = "agriplot.urls"
WSGI_APPLICATION = "agriplot.wsgi.application"


# =============================================================================
# TEMPLATE SETTINGS
# =============================================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",

        # Global template directory
        "DIRS": [BASE_DIR / "templates"],

        "APP_DIRS": True,

        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Email Configuration - reads from .env
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = 'AgriPlot Connect <ejuma411@gmail.com>'

# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


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
# STATIC FILES
# =============================================================================

STATIC_URL = "static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]


# =============================================================================
# MEDIA FILES (Uploads)
# =============================================================================

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# =============================================================================
# AUTH REDIRECTS
# =============================================================================

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"


# =============================================================================
# DEFAULT PRIMARY KEY
# =============================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# =============================================================================
# ENHANCED LOGGING CONFIGURATION
# =============================================================================

# Create logs directory automatically
LOG_DIR = BASE_DIR / "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Log file paths
ERROR_LOG_FILE = LOG_DIR / "error.log"
DEBUG_LOG_FILE = LOG_DIR / "debug.log"
DJANGO_LOG_FILE = LOG_DIR / "django.log"
LISTINGS_LOG_FILE = LOG_DIR / "listings.log"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "verbose": {
            "format": "{levelname} | {asctime} | {name} | {module} | {lineno} | {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "detailed": {
            "format": "{levelname} | {asctime} | {name} | {module} | {funcName} | {lineno} | {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "simple": {
            "format": "{levelname} | {asctime} | {message}",
            "style": "{",
            "datefmt": "%H:%M:%S",
        },
        "error_format": {
            "format": "{levelname} | {asctime} | {name} | {module} | {lineno} | {message}\nRequest: {request_path}\nUser: {user}\nMethod: {method}\n",
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
            "formatter": "simple",
            "level": "DEBUG",
        },

        # Main Error Handler - captures all ERROR and above
        "error_file": {
            "class": "logging.FileHandler",
            "filename": ERROR_LOG_FILE,
            "formatter": "verbose",
            "level": "ERROR",
        },

        # Debug File Handler - captures DEBUG and above for detailed debugging
        "debug_file": {
            "class": "logging.FileHandler",
            "filename": DEBUG_LOG_FILE,
            "formatter": "detailed",
            "level": "DEBUG",
        },

        # Django-specific log file
        "django_file": {
            "class": "logging.FileHandler",
            "filename": DJANGO_LOG_FILE,
            "formatter": "verbose",
            "level": "INFO",
        },

        # Listings app specific log file
        "listings_file": {
            "class": "logging.FileHandler",
            "filename": LISTINGS_LOG_FILE,
            "formatter": "detailed",
            "level": "DEBUG",
        },

        # Mail handler for critical errors (uncomment and configure for production)
        # "mail_admins": {
        #     "class": "django.utils.log.AdminEmailHandler",
        #     "level": "ERROR",
        #     "filters": ["require_debug_false"],
        #     "include_html": True,
        # },
    },

    "loggers": {
        # Root logger - captures everything
        "": {
            "handlers": ["console", "error_file", "debug_file"],
            "level": "DEBUG",
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
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },

        # Django Security logs
        "django.security": {
            "handlers": ["error_file", "console"],
            "level": "ERROR",
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
            "handlers": ["console", "debug_file", "error_file"],
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

# Optional: Add custom logging configuration for specific error tracking
if DEBUG:
    # In development, log all SQL queries to debug file
    LOGGING['loggers']['django.db.backends']['level'] = 'DEBUG'
else:
    # In production, only log slow queries
    LOGGING['loggers']['django.db.backends']['level'] = 'INFO'

# Create a custom logger for form validation errors
import logging
validation_logger = logging.getLogger('listings.validation')
"""
Django settings for the fuel route planner.

All environment-specific values come from environment variables (optionally
loaded from a local `.env` file). See `.env.example`.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")
    SECRET_KEY = "insecure-local-development-key-only"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "stations",
    "trips",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "fuel-route-planner",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "trips.exceptions.api_exception_handler",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    # 4xx responses are expected API outcomes; runserver already logs every request.
    "loggers": {"django.request": {"level": "ERROR"}},
}

# --- Fuel data -------------------------------------------------------------

FUEL_DATA_CSV = Path(os.environ.get("FUEL_DATA_CSV", BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"))
CITY_COORDINATES_CSV = Path(
    os.environ.get("CITY_COORDINATES_CSV", BASE_DIR / "data" / "city_coordinates.csv")
)

# --- External map services (OpenStreetMap ecosystem, no API key required) --

GEOCODING_API_URL = os.environ.get("GEOCODING_API_URL", "https://nominatim.openstreetmap.org")
ROUTING_API_URL = os.environ.get("ROUTING_API_URL", "https://router.project-osrm.org")
# Nominatim's usage policy requires an identifying User-Agent.
EXTERNAL_API_USER_AGENT = os.environ.get(
    "EXTERNAL_API_USER_AGENT", "fuel-route-planner/1.0 (take-home assessment)"
)
EXTERNAL_API_TIMEOUT_SECONDS = float(os.environ.get("EXTERNAL_API_TIMEOUT_SECONDS", "10"))

GEOCODE_CACHE_SECONDS = int(os.environ.get("GEOCODE_CACHE_SECONDS", 60 * 60 * 24))
ROUTE_CACHE_SECONDS = int(os.environ.get("ROUTE_CACHE_SECONDS", 60 * 60))

# --- Trip planning assumptions (from the assignment) ------------------------

VEHICLE_MAX_RANGE_MILES = 500.0
VEHICLE_MPG = 10.0
# Stations are located at their city centre, a few miles from the actual exit,
# so the corridor is wider than the true detour a driver would make.
ROUTE_CORRIDOR_MILES = float(os.environ.get("ROUTE_CORRIDOR_MILES", "10"))
# Route geometry is thinned to about one vertex per this many miles.
ROUTE_SAMPLING_MILES = 1.0

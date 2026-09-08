"""Configuracion de la aplicacion, leida del entorno."""
from __future__ import annotations

import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _bool(nombre: str, defecto: bool = False) -> bool:
    return os.environ.get(nombre, str(defecto)).strip().lower() in {"1", "true", "yes", "si"}


def _int(nombre: str, defecto: int) -> int:
    try:
        return int(os.environ.get(nombre, defecto))
    except (TypeError, ValueError):
        return defecto


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "clave-insegura-solo-para-desarrollo")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://tickets:tickets@localhost:5432/tickets"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 1800}

    # --- Zona horaria de presentacion --------------------------------------
    # Todo se almacena en UTC (timestamptz); esto solo afecta como se muestra.
    APP_TZ = os.environ.get("APP_TZ", "UTC")

    # --- Object storage (Garage) -------------------------------------------
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "http://garage:3900")
    # Endpoint con el que se FIRMAN las URL que abre el navegador. Debe ser
    # alcanzable desde el cliente, no desde la red interna de Docker.
    S3_PUBLIC_ENDPOINT = os.environ.get("S3_PUBLIC_ENDPOINT", "http://localhost:3900")
    S3_REGION = os.environ.get("S3_REGION", "garage")
    S3_BUCKET = os.environ.get("S3_BUCKET", "tickets-adjuntos")
    S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
    S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
    S3_URL_EXPIRACION = _int("S3_URL_EXPIRACION", 900)

    # --- Fotos --------------------------------------------------------------
    MAX_FOTO_MB = _int("MAX_FOTO_MB", 8)
    FOTO_MAX_PIXELES = _int("FOTO_MAX_PIXELES", 1920)
    EXTENSIONES_FOTO = {"jpg", "jpeg", "png", "webp"}

    # Tope global de subida: las dos fotos de una orden viajan en la misma
    # peticion, de ahi el margen extra.
    MAX_CONTENT_LENGTH = (_int("MAX_FOTO_MB", 8) * 2 + 2) * 1024 * 1024

    # --- Sesion -------------------------------------------------------------
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    WTF_CSRF_TIME_LIMIT = None

    # --- Varios -------------------------------------------------------------
    POR_PAGINA = _int("POR_PAGINA", 25)
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    @classmethod
    def zona_horaria(cls) -> ZoneInfo:
        try:
            return ZoneInfo(cls.APP_TZ)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")


class DevConfig(Config):
    DEBUG = True
    TEMPLATES_AUTO_RELOAD = True


class ProdConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL", "postgresql+psycopg://tickets:tickets@localhost:5432/tickets"
        ).rsplit("/", 1)[0]
        + "/tickets_test",
    )
    RATELIMIT_ENABLED = False


CONFIGS = {"development": DevConfig, "production": ProdConfig, "testing": TestConfig}


def obtener_config(nombre: str | None = None):
    nombre = nombre or os.environ.get("FLASK_ENV", "production")
    return CONFIGS.get(nombre, ProdConfig)

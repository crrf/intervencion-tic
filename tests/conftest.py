"""Configuracion comun de las pruebas.

El almacenamiento se sustituye por uno en memoria: las pruebas ejercitan la
validacion real de las fotos (extension, tamano, que Pillow pueda abrirlas)
pero no tocan la red ni Garage.
"""
from __future__ import annotations

import io
import os

import pytest
import sqlalchemy as sa

from app import create_app
from app.extensions import db as _db
from app.models.enums import RolUsuario
from app.models.usuario import Usuario
from app.services import storage


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
def _asegurar_base_de_pruebas(uri: str) -> None:
    """Crea la base de datos de pruebas si todavia no existe."""
    url = sa.engine.make_url(uri)
    nombre = url.database
    admin = sa.create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as con:
        existe = con.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": nombre}
        ).scalar()
        if not existe:
            con.execute(sa.text(f'CREATE DATABASE "{nombre}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def _aplicacion():
    os.environ.setdefault("SECRET_KEY", "pruebas")
    aplicacion = create_app("testing")
    _asegurar_base_de_pruebas(aplicacion.config["SQLALCHEMY_DATABASE_URI"])
    with aplicacion.app_context():
        _db.drop_all()
        _db.create_all()
    yield aplicacion
    with aplicacion.app_context():
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def app(_aplicacion):
    """Un contexto de aplicacion NUEVO por prueba.

    Es importante que no sea uno solo para toda la sesion: Flask-Login guarda
    el usuario en `g`, y un contexto compartido arrastraria la sesion (y el
    objeto Usuario ya borrado) de una prueba a la siguiente.
    """
    with _aplicacion.app_context():
        yield _aplicacion
        _db.session.rollback()
        for tabla in reversed(_db.metadata.sorted_tables):
            _db.session.execute(tabla.delete())
        _db.session.commit()
        _db.session.remove()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def cliente(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Almacenamiento simulado
# ---------------------------------------------------------------------------
class AlmacenFalso:
    def __init__(self) -> None:
        self.objetos: dict[str, bytes] = {}

    def subir(self, clave, datos, extension):
        self.objetos[clave] = datos
        return clave

    def url_prefirmada(self, clave, segundos=None):
        return f"http://storage.local/{clave}?firma=1" if clave else None

    def eliminar(self, clave):
        self.objetos.pop(clave, None)

    def existe(self, clave):
        return clave in self.objetos

    def asegurar_bucket(self):
        return None


@pytest.fixture(autouse=True)
def almacen(monkeypatch):
    falso = AlmacenFalso()
    monkeypatch.setattr(storage, "subir", falso.subir)
    monkeypatch.setattr(storage, "url_prefirmada", falso.url_prefirmada)
    monkeypatch.setattr(storage, "eliminar", falso.eliminar)
    monkeypatch.setattr(storage, "existe", falso.existe)
    monkeypatch.setattr(storage, "asegurar_bucket", falso.asegurar_bucket)
    return falso


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
def crear_usuario(login: str, *roles: RolUsuario, activo: bool = True) -> Usuario:
    u = Usuario(
        usuario=login,
        nombre_completo=login.replace("_", " ").title(),
        email=f"{login}@test.local",
        activo=activo,
    )
    u.set_password("Clave.2026")
    u.roles = list(roles)
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture
def admin(app):
    return crear_usuario("admin", RolUsuario.ADMIN)


@pytest.fixture
def despachador(app):
    return crear_usuario("despachador", RolUsuario.DESPACHADOR)


@pytest.fixture
def operador(app):
    return crear_usuario("operador", RolUsuario.OPERADOR)


@pytest.fixture
def operador_b(app):
    return crear_usuario("operador_b", RolUsuario.OPERADOR)


@pytest.fixture
def agente_fibra(app):
    return crear_usuario("fibra", RolUsuario.AGENTE_FIBRA)


@pytest.fixture
def mixto(app):
    """Un mismo usuario con dos roles: despachador y operador."""
    return crear_usuario("mixto", RolUsuario.DESPACHADOR, RolUsuario.OPERADOR)


# ---------------------------------------------------------------------------
# Fotos de prueba
# ---------------------------------------------------------------------------
class ArchivoFalso:
    """Imita el objeto FileStorage de Werkzeug."""

    def __init__(self, nombre: str, datos: bytes) -> None:
        self.filename = nombre
        self._datos = datos

    def read(self) -> bytes:
        return self._datos


def imagen_jpeg(color=(20, 80, 140)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (60, 40), color).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def foto():
    return lambda nombre="foto.jpg": ArchivoFalso(nombre, imagen_jpeg())


# ---------------------------------------------------------------------------
# Atajos para crear tickets
# ---------------------------------------------------------------------------
@pytest.fixture
def nueva_orden(app, foto):
    from app.services.tickets import crear_orden

    def _crear(creador, **kwargs):
        datos = {
            "identificador_externo": "ED123456",
            "nombre_cliente": "Cliente de prueba",
            "titulo": "Instalacion de enlace",
            "foto_anverso": ArchivoFalso("a.jpg", imagen_jpeg()),
            "foto_reverso": ArchivoFalso("r.jpg", imagen_jpeg()),
        }
        datos.update(kwargs)
        return crear_orden(creador, **datos)

    return _crear


@pytest.fixture
def nueva_interrupcion(app):
    from app.services.tickets import crear_interrupcion

    def _crear(creador, **kwargs):
        datos = {
            "identificador_externo": "FD654321",
            "nombre_cliente": "Cliente de prueba",
            "titulo": "Perdida total de servicio",
            "foto": ArchivoFalso("i.jpg", imagen_jpeg()),
        }
        datos.update(kwargs)
        return crear_interrupcion(creador, **datos)

    return _crear

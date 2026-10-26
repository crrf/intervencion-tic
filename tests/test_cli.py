"""Comandos de consola: siembra de ejemplo, alta de usuarios y diagnostico."""
from __future__ import annotations

from sqlalchemy import select

from app.cli import crear_usuario as cmd_crear_usuario, seed, storage_check
from app.extensions import db
from app.models.enums import (
    CategoriaInterrupcion,
    EstadoInterrupcion,
    EstadoOrden,
    RolUsuario,
)
from app.models.interrupcion import Interrupcion
from app.models.orden import OrdenTrabajo
from app.models.usuario import Usuario
from app.services.estados import validar_destinatario
from tests.conftest import crear_usuario


def sembrar(app, monkeypatch):
    monkeypatch.setenv("SEED_PASSWORD", "Clave.2026")
    monkeypatch.setenv("ADMIN_PASSWORD", "ClaveAdmin.1")
    return app.test_cli_runner().invoke(seed)


def usuarios():
    return db.session.execute(select(Usuario)).scalars().unique().all()


# ---------------------------------------------------------------------------
# flask seed
# ---------------------------------------------------------------------------
def test_la_siembra_crea_los_nueve_perfiles(app, monkeypatch):
    resultado = sembrar(app, monkeypatch)
    assert resultado.exit_code == 0, resultado.output
    assert "Sembrados 9 usuarios" in resultado.output

    logins = {u.usuario for u in usuarios()}
    assert {
        "admin", "despachador1", "operador1", "operador2", "operador3",
        "fibra1", "fibra2", "mixto1", "wifi1",
    } <= logins

    wifi1 = next(u for u in usuarios() if u.usuario == "wifi1")
    assert wifi1.roles == {RolUsuario.TECNICO_WIFI}
    assert wifi1.activo is True

    mixto = next(u for u in usuarios() if u.usuario == "mixto1")
    assert mixto.roles == {RolUsuario.DESPACHADOR, RolUsuario.OPERADOR}


def test_la_siembra_crea_tickets_de_los_dos_tipos(app, monkeypatch):
    sembrar(app, monkeypatch)
    ordenes = db.session.execute(select(OrdenTrabajo)).scalars().unique().all()
    interrupciones = db.session.execute(select(Interrupcion)).scalars().unique().all()

    assert len(ordenes) == 22
    assert len(interrupciones) == 26
    assert all(o.folio.startswith("OT-") for o in ordenes)
    assert all(i.folio.startswith("INT-") for i in interrupciones)
    # Hay variedad de estados, no todo en uno.
    assert len({o.estado for o in ordenes}) >= 4
    assert len({i.estado for i in interrupciones}) >= 4


def test_las_ordenes_cerradas_pasaron_por_el_ok(app, monkeypatch):
    """La siembra tiene que reflejar el flujo real, no el viejo."""
    sembrar(app, monkeypatch)
    cerradas = [
        o
        for o in db.session.execute(select(OrdenTrabajo)).scalars().unique().all()
        if o.estado is EstadoOrden.CERRADA
    ]
    assert cerradas, "la siembra deberia dejar ordenes cerradas"

    for orden in cerradas:
        estados = [h.valor_nuevo for h in orden.historial if h.campo == "estado"]
        assert "OK del operador" in estados, orden.folio
        assert estados.index("OK del operador") < estados.index("Cerrada")
        assert orden.cerrado_en is not None


def test_la_siembra_deja_ordenes_esperando_el_cierre(app, monkeypatch):
    sembrar(app, monkeypatch)
    con_ok = [
        o
        for o in db.session.execute(select(OrdenTrabajo)).scalars().unique().all()
        if o.estado is EstadoOrden.OK_OPERADOR
    ]
    assert con_ok, "deberia haber alguna en la columna del despachador"
    assert all(o.cerrado_en is None for o in con_ok)


def test_la_siembra_crea_sitios_wifi_y_respeta_la_regla(app, monkeypatch):
    sembrar(app, monkeypatch)
    interrupciones = db.session.execute(select(Interrupcion)).scalars().unique().all()

    wifi = [i for i in interrupciones if i.categoria is CategoriaInterrupcion.SITIO_WIFI]
    assert wifi, "deberia haber interrupciones de sitio wifi"

    tecnico = next(u for u in usuarios() if u.usuario == "wifi1")
    assert any(i.asignado_a_id == tecnico.id for i in wifi), "alguna va al tecnico"

    # Ningun ticket sembrado viola la regla de asignacion.
    for inter in interrupciones:
        if inter.asignado_a is not None:
            validar_destinatario(inter, inter.asignado_a)
    for orden in db.session.execute(select(OrdenTrabajo)).scalars().unique().all():
        if orden.asignado_a is not None:
            validar_destinatario(orden, orden.asignado_a)


def test_las_interrupciones_cerradas_tienen_dependencia(app, monkeypatch):
    sembrar(app, monkeypatch)
    for inter in db.session.execute(select(Interrupcion)).scalars().unique().all():
        if inter.estado is EstadoInterrupcion.CERRADA:
            assert inter.dependencia is not None, inter.folio


def test_la_siembra_es_idempotente(app, monkeypatch):
    sembrar(app, monkeypatch)
    cuantos = len(usuarios())

    segunda = sembrar(app, monkeypatch)
    assert "no se siembra nada" in segunda.output
    assert len(usuarios()) == cuantos


def test_la_siembra_aguanta_un_storage_caido(app, monkeypatch):
    """Sin object storage se siembra igual, solo sin fotos."""
    from app.services import storage

    def caido(*args, **kwargs):
        raise RuntimeError("garage no responde")

    monkeypatch.setattr(storage, "asegurar_bucket", caido)
    resultado = sembrar(app, monkeypatch)
    assert resultado.exit_code == 0, resultado.output
    assert "AVISO" in resultado.output
    assert len(usuarios()) == 9


# ---------------------------------------------------------------------------
# flask crear-usuario
# ---------------------------------------------------------------------------
def test_crea_un_usuario_con_dos_roles(app):
    resultado = app.test_cli_runner().invoke(
        cmd_crear_usuario,
        [
            "--usuario", "tecnico9",
            "--nombre", "Tecnico Nueve",
            "--password", "ClaveLarga.1",
            "--rol", "TECNICO_WIFI",
            "--rol", "OPERADOR",
            "--email", "t9@empresa.com",
        ],
    )
    assert resultado.exit_code == 0, resultado.output

    u = db.session.execute(
        select(Usuario).where(Usuario.usuario == "tecnico9")
    ).scalar_one()
    assert u.roles == {RolUsuario.TECNICO_WIFI, RolUsuario.OPERADOR}
    assert u.check_password("ClaveLarga.1")
    assert u.email == "t9@empresa.com"


def test_no_crea_dos_veces_el_mismo_usuario(app):
    crear_usuario("repetido", RolUsuario.OPERADOR)
    resultado = app.test_cli_runner().invoke(
        cmd_crear_usuario,
        [
            "--usuario", "repetido",
            "--nombre", "Otro",
            "--password", "ClaveLarga.1",
            "--rol", "OPERADOR",
        ],
    )
    assert resultado.exit_code != 0
    assert "ya existe" in resultado.output


def test_un_rol_que_no_existe_se_rechaza(app):
    resultado = app.test_cli_runner().invoke(
        cmd_crear_usuario,
        [
            "--usuario", "x9",
            "--nombre", "X",
            "--password", "ClaveLarga.1",
            "--rol", "PRESIDENTE",
        ],
    )
    assert resultado.exit_code != 0
    assert db.session.execute(
        select(Usuario).where(Usuario.usuario == "x9")
    ).scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# flask storage-check
# ---------------------------------------------------------------------------
def test_el_diagnostico_del_storage_informa(app, almacen):
    resultado = app.test_cli_runner().invoke(storage_check)
    assert resultado.exit_code == 0, resultado.output
    assert "bucket accesible: si" in resultado.output
    assert "objeto escrito y leido: True" in resultado.output
    assert "URL firmada: http" in resultado.output
    assert almacen.objetos == {}, "el objeto de prueba se borra al final"

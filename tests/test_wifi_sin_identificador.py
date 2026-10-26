"""Las interrupciones de sitio wifi no llevan identificador externo.

No vienen del sistema externo, asi que el formulario no lo pide, el servicio
no lo exige y la pantalla no deja un hueco donde iria.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models.enums import CategoriaInterrupcion, RolUsuario
from app.models.interrupcion import Interrupcion
from app.services import tickets as servicio
from tests.conftest import crear_usuario

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    return cliente.post("/login", data={"usuario": usuario.usuario, "password": CLAVE})


def texto(cliente, ruta):
    respuesta = cliente.get(ruta)
    assert respuesta.status_code == 200, ruta
    return respuesta.get_data(as_text=True)


@pytest.fixture
def tecnico_wifi(app):
    return crear_usuario("wifi", RolUsuario.TECNICO_WIFI)


def crear_wifi(cliente, **extra):
    datos = {
        "nombre_cliente": "Plaza Bolivar",
        "titulo": "El sitio wifi no da servicio",
        "direccion": "Av. Bolivar con calle 5",
        "prioridad": "ALTA",
    }
    datos.update(extra)
    return cliente.post(
        "/interrupciones/nueva-wifi", data=datos, follow_redirects=True
    )


def buscar_wifi() -> Interrupcion:
    return db.session.execute(
        select(Interrupcion).where(
            Interrupcion.categoria == CategoriaInterrupcion.SITIO_WIFI
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# El formulario
# ---------------------------------------------------------------------------
def test_el_formulario_no_pide_identificador(cliente, despachador):
    entrar(cliente, despachador)
    html = texto(cliente, "/interrupciones/nueva-wifi")
    assert 'name="identificador_externo"' not in html
    assert "Identificador" not in html


def test_los_otros_dos_formularios_si_lo_piden(cliente, despachador):
    entrar(cliente, despachador)
    for ruta in ("/ordenes/nueva", "/interrupciones/nueva"):
        html = texto(cliente, ruta)
        assert 'name="identificador_externo"' in html, ruta


def test_se_crea_sin_identificador(cliente, despachador, tecnico_wifi):
    entrar(cliente, despachador)
    respuesta = crear_wifi(cliente, asignado_a_id=str(tecnico_wifi.id))
    assert "creada" in respuesta.get_data(as_text=True)

    inter = buscar_wifi()
    assert inter.identificador_externo is None
    assert inter.es_sitio_wifi is True
    assert inter.asignado_a_id == tecnico_wifi.id
    assert inter.folio.startswith("INT-")


def test_el_servicio_tampoco_lo_exige(app, despachador):
    inter = servicio.crear_interrupcion(
        despachador,
        nombre_cliente="Plaza Bolivar",
        titulo="Sin servicio",
        categoria="SITIO_WIFI",
    )
    assert inter.identificador_externo is None


def test_la_interrupcion_de_enlace_si_lo_exige(app, despachador):
    with pytest.raises(servicio.DatosInvalidos, match="identificador"):
        servicio.crear_interrupcion(
            despachador,
            nombre_cliente="Clinica",
            titulo="Sin servicio",
            categoria="ENLACE_CLIENTE",
        )


def test_si_se_manda_uno_igual_se_valida(app, despachador):
    """El formulario no lo pide, pero si llega tiene que ser valido."""
    with pytest.raises(servicio.DatosInvalidos, match="identificador"):
        servicio.crear_interrupcion(
            despachador,
            identificador_externo="esto-no-vale",
            nombre_cliente="Plaza",
            titulo="Sin servicio",
            categoria="SITIO_WIFI",
        )

    inter = servicio.crear_interrupcion(
        despachador,
        identificador_externo="WF123",
        nombre_cliente="Plaza",
        titulo="Sin servicio",
        categoria="SITIO_WIFI",
    )
    assert inter.identificador_externo == "WF123"


# ---------------------------------------------------------------------------
# Donde iria el identificador
# ---------------------------------------------------------------------------
def test_el_detalle_no_deja_un_hueco(cliente, despachador):
    entrar(cliente, despachador)
    crear_wifi(cliente)
    inter = buscar_wifi()

    detalle = texto(cliente, inter.url_detalle)
    assert "No aplica" in detalle
    assert inter.folio in detalle, "el folio es el que identifica el ticket"


def test_la_tarjeta_no_muestra_una_linea_vacia(cliente, despachador):
    entrar(cliente, despachador)
    crear_wifi(cliente)
    inter = buscar_wifi()

    tablero = texto(cliente, "/tablero?tipo=interrupciones")
    assert inter.folio in tablero
    assert 'class="identificador mono"></div>' not in tablero


def test_los_listados_y_el_csv_ponen_un_guion(cliente, despachador):
    entrar(cliente, despachador)
    crear_wifi(cliente)
    inter = buscar_wifi()

    listado = texto(cliente, "/interrupciones/")
    assert inter.folio in listado

    csv = texto(cliente, "/buscar/csv")
    fila = next(f for f in csv.split("\r\n") if inter.folio in f)
    assert fila.split(";")[1] == "", "la columna va vacia, no con 'None'"
    assert "None" not in fila


def test_se_sigue_buscando_por_folio_y_direccion(cliente, despachador):
    entrar(cliente, despachador)
    crear_wifi(cliente)
    inter = buscar_wifi()

    for consulta in (inter.folio, "Bolivar"):
        resultados = texto(
            cliente, f"/buscar/?texto={consulta}",
        )
        assert inter.folio in resultados, consulta


# ---------------------------------------------------------------------------
# Datos de ejemplo
# ---------------------------------------------------------------------------
def test_la_siembra_deja_los_sitios_wifi_sin_identificador(app, monkeypatch):
    from app.cli import seed

    monkeypatch.setenv("SEED_PASSWORD", "Clave.2026")
    monkeypatch.setenv("ADMIN_PASSWORD", "ClaveAdmin.1")
    assert app.test_cli_runner().invoke(seed).exit_code == 0

    interrupciones = db.session.execute(select(Interrupcion)).scalars().unique().all()
    wifi = [i for i in interrupciones if i.es_sitio_wifi]
    enlace = [i for i in interrupciones if not i.es_sitio_wifi]

    assert wifi and all(i.identificador_externo is None for i in wifi)
    assert enlace and all(i.identificador_externo for i in enlace)

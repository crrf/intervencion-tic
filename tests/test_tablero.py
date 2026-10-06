"""El tablero kanban: columnas, filtros, modales y movimientos."""
from __future__ import annotations

import pytest

from app.extensions import db
from app.models.enums import EstadoInterrupcion, EstadoOrden, RolUsuario
from app.services.estados import ejecutar_transicion
from tests.conftest import crear_usuario

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    return cliente.post("/login", data={"usuario": usuario.usuario, "password": CLAVE})


def salir(cliente):
    cliente.get("/logout")


@pytest.fixture
def tecnico_wifi(app):
    return crear_usuario("wifi", RolUsuario.TECNICO_WIFI)


# ---------------------------------------------------------------------------
# Columnas y entrada
# ---------------------------------------------------------------------------
def test_estan_todas_las_columnas_de_ordenes(cliente, despachador):
    entrar(cliente, despachador)
    cuerpo = cliente.get("/tablero?tipo=ordenes").get_data(as_text=True)
    for estado in EstadoOrden:
        assert estado.etiqueta in cuerpo, estado.name


def test_estan_todas_las_columnas_de_interrupciones(cliente, despachador):
    entrar(cliente, despachador)
    cuerpo = cliente.get("/tablero?tipo=interrupciones").get_data(as_text=True)
    for estado in EstadoInterrupcion:
        assert estado.etiqueta in cuerpo, estado.name


def test_un_tipo_inventado_cae_en_el_de_siempre(cliente, despachador):
    entrar(cliente, despachador)
    respuesta = cliente.get("/tablero?tipo=cohetes")
    assert respuesta.status_code == 200
    assert "Ordenes de trabajo" in respuesta.get_data(as_text=True)


def test_el_agente_de_fibra_puro_va_a_su_bandeja(cliente, agente_fibra):
    entrar(cliente, agente_fibra)
    assert cliente.get("/tablero").headers["Location"].endswith("/fibra/")
    assert cliente.get("/").headers["Location"].endswith("/fibra/")


def test_el_tecnico_de_wifi_entra_a_interrupciones(cliente, tecnico_wifi):
    entrar(cliente, tecnico_wifi)
    cuerpo = cliente.get("/tablero").get_data(as_text=True)
    # La pestana activa es la de interrupciones, no la de ordenes vacia.
    assert "Derivada a fibra" in cuerpo


def test_el_refresco_parcial_devuelve_solo_las_columnas(cliente, despachador):
    entrar(cliente, despachador)
    respuesta = cliente.get("/tablero/columnas?tipo=ordenes")
    cuerpo = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 200
    assert "<html" not in cuerpo
    assert "columna" in cuerpo


def test_el_refresco_de_un_tipo_que_no_existe_da_404(cliente, despachador):
    entrar(cliente, despachador)
    assert cliente.get("/tablero/columnas?tipo=cohetes").status_code == 404


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
def test_el_filtro_de_solo_mios(cliente, nueva_orden, despachador, operador, mixto):
    propia = nueva_orden(despachador, asignado_a=mixto)
    ajena = nueva_orden(
        despachador, identificador_externo="ED222222", asignado_a=operador
    )
    db.session.commit()

    entrar(cliente, mixto)
    todas = cliente.get("/tablero?tipo=ordenes").get_data(as_text=True)
    assert propia.folio in todas and ajena.folio in todas

    solo_mias = cliente.get("/tablero?tipo=ordenes&mios=1").get_data(as_text=True)
    assert propia.folio in solo_mias
    assert ajena.folio not in solo_mias


def test_el_filtro_de_prioridad(cliente, nueva_orden, despachador):
    critica = nueva_orden(despachador, prioridad="CRITICA")
    baja = nueva_orden(despachador, identificador_externo="ED222222", prioridad="BAJA")
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = cliente.get("/tablero?tipo=ordenes&prioridad=CRITICA").get_data(as_text=True)
    assert critica.folio in cuerpo
    assert baja.folio not in cuerpo


def test_una_prioridad_inventada_no_filtra_nada(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = cliente.get("/tablero?tipo=ordenes&prioridad=URGENTISIMA").get_data(
        as_text=True
    )
    assert orden.folio in cuerpo


# ---------------------------------------------------------------------------
# Modal de la transicion
# ---------------------------------------------------------------------------
def test_el_modal_trae_los_campos_que_exige_la_transicion(
    cliente, nueva_orden, despachador, operador
):
    orden = nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = cliente.get(
        f"/tablero/accion/ordenes/{orden.id}?transicion=estado:ASIGNADA"
    ).get_data(as_text=True)
    assert "Asignar a un operador" in cuerpo
    assert 'name="asignado_a_id"' in cuerpo
    assert operador.nombre_completo in cuerpo
    assert 'name="telefono_contacto"' in cuerpo


def test_el_modal_de_una_transicion_no_permitida_explica(
    cliente, nueva_orden, despachador, operador
):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, operador)
    respuesta = cliente.get(
        f"/tablero/accion/ordenes/{orden.id}?transicion=estado:CERRADA"
    )
    assert respuesta.status_code == 200
    assert "no esta permitido" in respuesta.get_data(as_text=True)


def test_el_modal_de_un_ticket_ajeno_da_403(
    cliente, nueva_orden, despachador, operador, operador_b
):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, operador_b)
    respuesta = cliente.get(
        f"/tablero/accion/ordenes/{orden.id}?transicion=estado:EN_PROCESO"
    )
    assert respuesta.status_code == 403


def test_el_modal_de_un_tipo_que_no_existe_da_404(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    assert cliente.get(f"/tablero/accion/cohetes/{orden.id}").status_code == 404


# ---------------------------------------------------------------------------
# Mover desde el tablero
# ---------------------------------------------------------------------------
def test_se_mueve_desde_el_tablero_y_se_redibuja(
    cliente, nueva_orden, despachador, operador
):
    orden = nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    respuesta = cliente.post(
        f"/tablero/mover/ordenes/{orden.id}",
        data={"transicion": "estado:ASIGNADA", "asignado_a_id": str(operador.id)},
    )
    assert respuesta.status_code == 200
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.ASIGNADA
    # Devuelve las columnas, no una pagina entera.
    cuerpo = respuesta.get_data(as_text=True)
    assert "<html" not in cuerpo
    assert orden.folio in cuerpo


def test_el_error_al_mover_se_muestra_en_el_tablero(
    cliente, nueva_orden, despachador, operador
):
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    db.session.commit()

    entrar(cliente, operador)
    respuesta = cliente.post(
        f"/tablero/mover/ordenes/{orden.id}",
        data={"transicion": "estado:OK_OPERADOR"},  # falta el comentario
    )
    assert respuesta.status_code == 200
    assert "exige un comentario" in respuesta.get_data(as_text=True)
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.EN_PROCESO


def test_el_telefono_se_guarda_al_asignar_desde_el_tablero(
    cliente, nueva_orden, despachador, operador
):
    orden = nueva_orden(despachador, telefono_contacto=None)
    db.session.commit()

    entrar(cliente, despachador)
    cliente.post(
        f"/tablero/mover/ordenes/{orden.id}",
        data={
            "transicion": "estado:ASIGNADA",
            "asignado_a_id": str(operador.id),
            "telefono_contacto": "0412-3334455",
        },
    )
    db.session.refresh(orden)
    assert orden.asignado_a_id == operador.id
    assert orden.telefono_contacto == "0412-3334455"


def test_mover_un_ticket_ajeno_da_403(
    cliente, nueva_orden, despachador, operador, operador_b
):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, operador_b)
    respuesta = cliente.post(
        f"/tablero/mover/ordenes/{orden.id}", data={"transicion": "estado:EN_PROCESO"}
    )
    assert respuesta.status_code == 403
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.ASIGNADA


def test_sin_sesion_no_hay_tablero(cliente):
    assert cliente.get("/tablero").status_code == 302
    assert cliente.get("/tablero/columnas?tipo=ordenes").status_code == 302
    assert cliente.post("/tablero/mover/ordenes/1", data={}).status_code == 302

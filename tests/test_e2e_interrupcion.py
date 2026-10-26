"""Recorrido completo de una interrupcion por HTTP: operador, agente de fibra
y tecnico de wifi, cada uno con su sesion."""
from __future__ import annotations

import io

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models.enums import (
    CategoriaInterrupcion,
    Dependencia,
    EstadoFibra,
    EstadoInterrupcion,
    RolUsuario,
)
from app.models.interrupcion import Interrupcion
from app.services import notificaciones as notif
from tests.conftest import crear_usuario, imagen_jpeg

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    respuesta = cliente.post(
        "/login", data={"usuario": usuario.usuario, "password": CLAVE}
    )
    assert respuesta.status_code == 302
    return respuesta


def salir(cliente):
    cliente.get("/logout")


def crear_por_formulario(cliente, ruta="/interrupciones/nueva", **extra):
    datos = {
        "identificador_externo": "FD778899",
        "nombre_cliente": "Clinica Santa Rosa",
        "telefono_contacto": "0212-5556677",
        "titulo": "Perdida total del servicio",
        "descripcion": "Sin enlace desde las 08:00.",
        "prioridad": "CRITICA",
        "foto": (io.BytesIO(imagen_jpeg()), "foto.jpg"),
    }
    datos.update(extra)
    return cliente.post(
        ruta, data=datos, content_type="multipart/form-data", follow_redirects=True
    )


def mover(cliente, inter, clave, **datos):
    return cliente.post(
        f"/interrupciones/{inter.id}/mover", data={"transicion": clave, **datos},
        follow_redirects=True,
    )


def buscar(identificador="FD778899") -> Interrupcion:
    return db.session.execute(
        select(Interrupcion).where(Interrupcion.identificador_externo == identificador)
    ).scalar_one()


@pytest.fixture
def tecnico_wifi(app):
    return crear_usuario("wifi", RolUsuario.TECNICO_WIFI)


# ---------------------------------------------------------------------------
# Interrupcion que acaba derivada a fibra
# ---------------------------------------------------------------------------
def test_de_la_creacion_al_cierre_pasando_por_fibra(
    cliente, despachador, operador, agente_fibra
):
    # --- El despachador la crea y la asigna --------------------------------
    entrar(cliente, despachador)
    assert cliente.get("/interrupciones/nueva").status_code == 200
    crear_por_formulario(cliente, asignado_a_id=str(operador.id))

    inter = buscar()
    assert inter.estado is EstadoInterrupcion.ASIGNADA
    assert inter.categoria is CategoriaInterrupcion.ENLACE_CLIENTE
    assert inter.dependencia is None, "la dependencia la pone quien diagnostica"
    assert inter.foto_key
    salir(cliente)

    # --- El operador diagnostica ------------------------------------------
    entrar(cliente, operador)
    mover(cliente, inter, "estado:EN_PROCESO")
    db.session.refresh(inter)
    assert inter.estado is EstadoInterrupcion.EN_PROCESO

    # Sin clasificar la dependencia no puede cerrar.
    respuesta = mover(cliente, inter, "estado:CERRADA", comentario="resuelto")
    db.session.refresh(inter)
    assert inter.estado is EstadoInterrupcion.EN_PROCESO
    assert "dependencia" in respuesta.get_data(as_text=True)

    cliente.post(
        f"/interrupciones/{inter.id}/dependencia",
        data={"dependencia": "CAPA_FISICA"}, follow_redirects=True,
    )
    db.session.refresh(inter)
    assert inter.dependencia is Dependencia.CAPA_FISICA

    # --- Y la deriva a fibra ----------------------------------------------
    mover(
        cliente, inter, "estado:DERIVADA_FIBRA",
        comentario="Se descarto el equipo activo", dependencia="CAPA_FISICA",
    )
    db.session.refresh(inter)
    assert inter.estado is EstadoInterrupcion.DERIVADA_FIBRA
    assert inter.estado_fibra is EstadoFibra.EN_REVISION
    assert inter.derivado_fibra_en is not None
    assert notif.contar_no_leidas(agente_fibra.id) == 1
    salir(cliente)

    # --- El agente de fibra responde desde su bandeja ---------------------
    entrar(cliente, agente_fibra)
    bandeja = cliente.get("/fibra/").get_data(as_text=True)
    assert inter.folio in bandeja
    assert "Marcar fibra con falla" in bandeja

    # No puede cerrar la interrupcion, solo mover el estado de la fibra.
    rechazo = cliente.post(
        f"/fibra/mover/{inter.id}",
        data={"transicion": "estado:CERRADA", "comentario": "ya"},
    )
    db.session.refresh(inter)
    assert inter.estado is EstadoInterrupcion.DERIVADA_FIBRA
    assert "solo se cambia el estado de la fibra" in rechazo.get_data(as_text=True)

    cliente.post(
        f"/fibra/mover/{inter.id}",
        data={
            "transicion": "estado_fibra:FIBRA_CON_FALLA",
            "comentario": "Corte confirmado en el tramo aereo",
        },
    )
    db.session.refresh(inter)
    assert inter.estado_fibra is EstadoFibra.FIBRA_CON_FALLA
    assert inter.agente_fibra_id == agente_fibra.id
    assert inter.respuesta_fibra_en is not None
    assert notif.contar_no_leidas(operador.id) >= 1
    salir(cliente)

    # --- El operador cierra tras leer la respuesta ------------------------
    entrar(cliente, operador)
    detalle = cliente.get(inter.url_detalle).get_data(as_text=True)
    assert "Fibra con falla" in detalle
    assert "Corte confirmado en el tramo aereo" in detalle

    mover(cliente, inter, "estado:CERRADA", comentario="Empalme hecho, servicio arriba")
    db.session.refresh(inter)
    assert inter.estado is EstadoInterrupcion.CERRADA
    assert inter.cerrado_en is not None

    estados = [h.valor_nuevo for h in inter.historial if h.campo == "estado"]
    assert estados == ["Nueva", "Asignada", "En proceso", "Derivada a fibra", "Cerrada"]


def test_no_se_deriva_a_fibra_lo_que_no_es_capa_fisica(cliente, despachador, operador):
    entrar(cliente, despachador)
    crear_por_formulario(cliente, asignado_a_id=str(operador.id))
    inter = buscar()
    salir(cliente)

    entrar(cliente, operador)
    mover(cliente, inter, "estado:EN_PROCESO")
    respuesta = mover(
        cliente, inter, "estado:DERIVADA_FIBRA",
        comentario="parece fibra", dependencia="CORE_IPMPLS",
    )
    db.session.refresh(inter)
    assert inter.estado is EstadoInterrupcion.EN_PROCESO
    assert "capa fisica" in respuesta.get_data(as_text=True)


def test_el_operador_la_retoma_de_fibra(cliente, despachador, operador):
    entrar(cliente, despachador)
    crear_por_formulario(cliente, asignado_a_id=str(operador.id))
    inter = buscar()
    salir(cliente)

    entrar(cliente, operador)
    mover(cliente, inter, "estado:EN_PROCESO")
    mover(
        cliente, inter, "estado:DERIVADA_FIBRA",
        comentario="posible corte", dependencia="CAPA_FISICA",
    )
    mover(cliente, inter, "estado:EN_PROCESO", comentario="Era el equipo del cliente")
    db.session.refresh(inter)
    assert inter.estado is EstadoInterrupcion.EN_PROCESO


# ---------------------------------------------------------------------------
# Interrupcion de sitio wifi
# ---------------------------------------------------------------------------
def test_recorrido_de_un_sitio_wifi(cliente, despachador, tecnico_wifi):
    # --- El despachador la crea de sitio wifi y se la entrega al tecnico --
    entrar(cliente, despachador)
    formulario = cliente.get("/interrupciones/nueva-wifi").get_data(as_text=True)
    assert "sitio wifi" in formulario.lower()
    assert tecnico_wifi.nombre_completo in formulario
    assert 'name="categoria"' not in formulario, "la categoria ya la fija el flujo"

    respuesta = crear_por_formulario(
        cliente, ruta="/interrupciones/nueva-wifi",
        asignado_a_id=str(tecnico_wifi.id),
    )
    assert "operador activo" not in respuesta.get_data(as_text=True)

    inter = buscar()
    assert inter.es_sitio_wifi is True
    assert inter.asignado_a_id == tecnico_wifi.id
    assert inter.estado is EstadoInterrupcion.ASIGNADA
    assert "Sitio wifi" in cliente.get(inter.url_detalle).get_data(as_text=True)
    salir(cliente)

    # --- El tecnico la trabaja como un operador ---------------------------
    entrar(cliente, tecnico_wifi)
    tablero = cliente.get("/tablero").get_data(as_text=True)
    assert inter.folio in tablero, "entra directo al tablero de interrupciones"
    assert "Sitio wifi" in tablero

    mover(cliente, inter, "estado:EN_PROCESO")
    db.session.refresh(inter)
    assert inter.estado is EstadoInterrupcion.EN_PROCESO

    cliente.post(
        f"/interrupciones/{inter.id}/dependencia",
        data={"dependencia": "DISTRIBUCION"}, follow_redirects=True,
    )
    db.session.refresh(inter)
    assert inter.dependencia is Dependencia.DISTRIBUCION

    cliente.post(
        f"/interrupciones/{inter.id}/comentar",
        data={"texto": "Se reinicio el AP y quedo estable"}, follow_redirects=True,
    )
    mover(cliente, inter, "estado:CERRADA", comentario="Resuelto en sitio")
    db.session.refresh(inter)
    assert inter.estado is EstadoInterrupcion.CERRADA
    assert inter.cerrado_en is not None
    assert any("AP" in c.texto for c in inter.comentarios)


def test_el_formulario_de_enlace_no_ofrece_al_tecnico_de_wifi(
    cliente, despachador, operador, tecnico_wifi
):
    entrar(cliente, despachador)
    formulario = cliente.get("/interrupciones/nueva").get_data(as_text=True)
    assert operador.nombre_completo in formulario
    assert tecnico_wifi.nombre_completo not in formulario
    assert 'name="categoria"' not in formulario


def test_el_servidor_rechaza_la_combinacion_aunque_se_fuerce(
    cliente, despachador, tecnico_wifi
):
    """La interfaz ya no lo ofrece, pero el servidor no se fia de la interfaz."""
    entrar(cliente, despachador)
    respuesta = crear_por_formulario(cliente, asignado_a_id=str(tecnico_wifi.id))
    cuerpo = respuesta.get_data(as_text=True)
    assert "solo se le pueden entregar interrupciones de sitio wifi" in cuerpo
    assert "operador activo" not in cuerpo, "el motivo tiene que ser el especifico"
    assert db.session.execute(select(Interrupcion)).first() is None


def test_el_flujo_de_wifi_fija_la_categoria_aunque_la_manden_cambiada(
    cliente, despachador
):
    entrar(cliente, despachador)
    crear_por_formulario(
        cliente, ruta="/interrupciones/nueva-wifi", categoria="ENLACE_CLIENTE"
    )
    assert buscar().es_sitio_wifi is True


def test_las_tres_puertas_estan_en_la_barra(cliente, despachador):
    """Las tres viven en el menu de "+ Nuevo" y en el menu de movil."""
    entrar(cliente, despachador)
    barra = cliente.get("/tablero").get_data(as_text=True)
    assert "/ordenes/nueva" in barra
    assert "/interrupciones/nueva" in barra
    assert "/interrupciones/nueva-wifi" in barra
    assert "menu-nuevo" in barra
    assert "Interrupcion de sitio wifi" in barra


def test_el_flujo_de_wifi_es_solo_para_gestion(cliente, operador, tecnico_wifi):
    for usuario in (operador, tecnico_wifi):
        cliente.get("/logout")
        entrar(cliente, usuario)
        assert cliente.get("/interrupciones/nueva-wifi").status_code == 403


def test_si_no_hay_tecnicos_el_formulario_lo_advierte(cliente, despachador):
    entrar(cliente, despachador)
    cuerpo = cliente.get("/interrupciones/nueva-wifi").get_data(as_text=True)
    assert "No hay ningun tecnico de wifi activo" in cuerpo


def test_un_tecnico_inactivo_no_sale_en_el_formulario(
    cliente, despachador, tecnico_wifi
):
    tecnico_wifi.activo = False
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = cliente.get("/interrupciones/nueva-wifi").get_data(as_text=True)
    assert tecnico_wifi.nombre_completo not in cuerpo
    assert "No hay ningun tecnico de wifi activo" in cuerpo


def test_el_despachador_cambia_la_categoria_desde_el_detalle(
    cliente, despachador, tecnico_wifi
):
    entrar(cliente, despachador)
    crear_por_formulario(cliente)
    inter = buscar()

    cliente.post(
        f"/interrupciones/{inter.id}/categoria",
        data={"categoria": "SITIO_WIFI"}, follow_redirects=True,
    )
    db.session.refresh(inter)
    assert inter.es_sitio_wifi is True

    # Y ahora si se la puede entregar al tecnico.
    mover(cliente, inter, "estado:ASIGNADA", asignado_a_id=str(tecnico_wifi.id))
    db.session.refresh(inter)
    assert inter.asignado_a_id == tecnico_wifi.id

    # Pero ya no puede volver a enlace de cliente sin reasignar.
    respuesta = cliente.post(
        f"/interrupciones/{inter.id}/categoria",
        data={"categoria": "ENLACE_CLIENTE"}, follow_redirects=True,
    )
    db.session.refresh(inter)
    assert inter.es_sitio_wifi is True
    assert "reasignala" in respuesta.get_data(as_text=True)

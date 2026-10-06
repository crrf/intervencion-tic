"""Acciones compartidas de la pantalla de detalle, por HTTP.

Comentar, reasignar, corregir el telefono y reemplazar fotos se hacen igual en
ordenes e interrupciones; este modulo cubre los dos lados y los permisos.
"""
from __future__ import annotations

import io

from app.extensions import db
from app.models.enums import EstadoOrden
from app.services import notificaciones as notif
from tests.conftest import imagen_jpeg

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    return cliente.post("/login", data={"usuario": usuario.usuario, "password": CLAVE})


def salir(cliente):
    cliente.get("/logout")


def archivo(nombre="x.jpg"):
    return (io.BytesIO(imagen_jpeg()), nombre)


# ---------------------------------------------------------------------------
# Comentarios
# ---------------------------------------------------------------------------
def test_el_asignado_comenta_su_ticket(cliente, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, operador)
    respuesta = cliente.post(
        f"/ordenes/{orden.id}/comentar",
        data={"texto": "Llegue al sitio, no hay nadie"}, follow_redirects=True,
    )
    assert respuesta.status_code == 200
    db.session.refresh(orden)
    assert orden.comentarios[-1].texto == "Llegue al sitio, no hay nadie"
    assert orden.comentarios[-1].autor_id == operador.id
    assert "Llegue al sitio" in respuesta.get_data(as_text=True)


def test_un_comentario_vacio_se_rechaza(cliente, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, operador)
    respuesta = cliente.post(
        f"/ordenes/{orden.id}/comentar", data={"texto": "   "}, follow_redirects=True
    )
    db.session.refresh(orden)
    assert orden.comentarios == []
    assert "vac" in respuesta.get_data(as_text=True).lower()


def test_un_ajeno_no_comenta(cliente, nueva_orden, despachador, operador, operador_b):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, operador_b)
    respuesta = cliente.post(f"/ordenes/{orden.id}/comentar", data={"texto": "hola"})
    assert respuesta.status_code == 403
    db.session.refresh(orden)
    assert orden.comentarios == []


def test_se_comenta_una_interrupcion_igual(
    cliente, nueva_interrupcion, despachador, operador
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, operador)
    cliente.post(
        f"/interrupciones/{inter.id}/comentar",
        data={"texto": "Revisando el nodo"}, follow_redirects=True,
    )
    db.session.refresh(inter)
    assert inter.comentarios[-1].texto == "Revisando el nodo"


# ---------------------------------------------------------------------------
# Reasignacion
# ---------------------------------------------------------------------------
def test_el_despachador_reasigna(cliente, nueva_orden, despachador, operador, operador_b):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, despachador)
    cliente.post(
        f"/ordenes/{orden.id}/reasignar",
        data={"nuevo_operador_id": str(operador_b.id)}, follow_redirects=True,
    )
    db.session.refresh(orden)
    assert orden.asignado_a_id == operador_b.id
    assert notif.contar_no_leidas(operador_b.id) == 1
    assert any(
        h.campo == "asignado_a" and h.valor_nuevo == operador_b.nombre_completo
        for h in orden.historial
    )


def test_el_operador_no_reasigna(cliente, nueva_orden, despachador, operador, operador_b):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, operador)
    respuesta = cliente.post(
        f"/ordenes/{orden.id}/reasignar",
        data={"nuevo_operador_id": str(operador_b.id)}, follow_redirects=True,
    )
    db.session.refresh(orden)
    assert orden.asignado_a_id == operador.id
    assert "despachador" in respuesta.get_data(as_text=True)


def test_no_se_reasigna_un_ticket_cerrado(
    cliente, nueva_orden, despachador, operador, operador_b
):
    from app.services.estados import ejecutar_transicion

    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:OK_OPERADOR", comentario="listo")
    ejecutar_transicion(orden, despachador, "estado:CERRADA", comentario="en SIPREC")
    db.session.commit()
    assert orden.estado is EstadoOrden.CERRADA

    entrar(cliente, despachador)
    respuesta = cliente.post(
        f"/ordenes/{orden.id}/reasignar",
        data={"nuevo_operador_id": str(operador_b.id)}, follow_redirects=True,
    )
    db.session.refresh(orden)
    assert orden.asignado_a_id == operador.id
    assert "cerrado" in respuesta.get_data(as_text=True)


def test_reasignar_a_nadie_avisa(cliente, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, despachador)
    respuesta = cliente.post(
        f"/ordenes/{orden.id}/reasignar", data={}, follow_redirects=True
    )
    db.session.refresh(orden)
    assert orden.asignado_a_id == operador.id
    assert "operador activo" in respuesta.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Telefono de contacto
# ---------------------------------------------------------------------------
def test_el_despachador_completa_el_telefono(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador, telefono_contacto=None)
    db.session.commit()
    assert orden.telefono_contacto is None

    entrar(cliente, despachador)
    cliente.post(
        f"/ordenes/{orden.id}/telefono",
        data={"telefono_contacto": "0426-9998877"}, follow_redirects=True,
    )
    db.session.refresh(orden)
    assert orden.telefono_contacto == "0426-9998877"


def test_un_telefono_invalido_se_rechaza(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador, telefono_contacto=None)
    db.session.commit()

    entrar(cliente, despachador)
    respuesta = cliente.post(
        f"/ordenes/{orden.id}/telefono",
        data={"telefono_contacto": "no-es-telefono"}, follow_redirects=True,
    )
    db.session.refresh(orden)
    assert orden.telefono_contacto is None
    assert "telefono" in respuesta.get_data(as_text=True).lower()


# ---------------------------------------------------------------------------
# Fotos
# ---------------------------------------------------------------------------
def test_el_despachador_agrega_una_foto_despues(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador, foto_anverso=None, foto_reverso=None)
    db.session.commit()
    assert orden.foto_anverso_key is None

    entrar(cliente, despachador)
    respuesta = cliente.post(
        f"/ordenes/{orden.id}/foto/anverso",
        data={"foto": archivo("anverso.jpg")},
        content_type="multipart/form-data", follow_redirects=True,
    )
    db.session.refresh(orden)
    assert orden.foto_anverso_key
    assert "agregada" in respuesta.get_data(as_text=True).lower()


def test_el_operador_no_cambia_fotos(cliente, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()
    clave_previa = orden.foto_anverso_key

    entrar(cliente, operador)
    respuesta = cliente.post(
        f"/ordenes/{orden.id}/foto/anverso",
        data={"foto": archivo()},
        content_type="multipart/form-data", follow_redirects=True,
    )
    db.session.refresh(orden)
    assert orden.foto_anverso_key == clave_previa
    assert "Solo el despachador" in respuesta.get_data(as_text=True)


def test_una_foto_que_no_existe_para_el_tipo_se_avisa(cliente, nueva_orden, despachador):
    """El nombre de la foto viene en la URL: no debe reventar, solo avisar."""
    orden = nueva_orden(despachador)
    db.session.commit()
    claves_previas = (orden.foto_anverso_key, orden.foto_reverso_key)

    entrar(cliente, despachador)
    respuesta = cliente.post(
        f"/ordenes/{orden.id}/foto/reverso_izquierdo",
        data={"foto": archivo()}, content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert respuesta.status_code == 200
    assert "Esa foto no existe para este tipo de ticket" in respuesta.get_data(as_text=True)
    db.session.refresh(orden)
    assert (orden.foto_anverso_key, orden.foto_reverso_key) == claves_previas


def test_la_interrupcion_no_acepta_las_fotos_de_una_orden(
    cliente, nueva_interrupcion, despachador
):
    inter = nueva_interrupcion(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    respuesta = cliente.post(
        f"/interrupciones/{inter.id}/foto/anverso",
        data={"foto": archivo()}, content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "Esa foto no existe para este tipo de ticket" in respuesta.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Transiciones desde el detalle
# ---------------------------------------------------------------------------
def test_una_transicion_inventada_no_rompe(cliente, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, operador)
    respuesta = cliente.post(
        f"/ordenes/{orden.id}/mover",
        data={"transicion": "estado:VOLANDO"}, follow_redirects=True,
    )
    assert respuesta.status_code == 200
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.ASIGNADA
    assert "no esta permitido" in respuesta.get_data(as_text=True)


def test_un_ticket_que_no_existe_da_404(cliente, despachador):
    entrar(cliente, despachador)
    assert cliente.get("/ordenes/987654").status_code == 404
    assert cliente.get("/interrupciones/987654").status_code == 404
    assert cliente.post("/ordenes/987654/comentar", data={"texto": "x"}).status_code == 404

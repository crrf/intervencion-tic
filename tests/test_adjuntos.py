"""Entrega de fotos: el bucket es privado, todo pasa por el permiso del ticket."""
from __future__ import annotations

from app.extensions import db
from app.models.enums import Dependencia
from app.services import storage
from app.services.estados import ejecutar_transicion

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    return cliente.post("/login", data={"usuario": usuario.usuario, "password": CLAVE})


def salir(cliente):
    cliente.get("/logout")


# ---------------------------------------------------------------------------
# Entrega normal
# ---------------------------------------------------------------------------
def test_redirige_a_una_url_firmada(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    for cual in ("anverso", "reverso"):
        respuesta = cliente.get(f"/adjuntos/orden/{orden.id}/{cual}")
        assert respuesta.status_code == 302
        assert "firma=1" in respuesta.headers["Location"]
        assert orden.clave_foto(cual) in respuesta.headers["Location"]


def test_la_foto_de_una_interrupcion(cliente, nueva_interrupcion, despachador):
    inter = nueva_interrupcion(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    respuesta = cliente.get(f"/adjuntos/interrupcion/{inter.id}/foto")
    assert respuesta.status_code == 302


# ---------------------------------------------------------------------------
# Lo que no existe
# ---------------------------------------------------------------------------
def test_un_tipo_desconocido_da_404(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    assert cliente.get(f"/adjuntos/cohete/{orden.id}/anverso").status_code == 404


def test_un_ticket_que_no_existe_da_404(cliente, despachador):
    entrar(cliente, despachador)
    assert cliente.get("/adjuntos/orden/987654/anverso").status_code == 404


def test_una_foto_que_no_aplica_al_tipo_da_404(cliente, nueva_interrupcion, despachador):
    inter = nueva_interrupcion(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    assert cliente.get(f"/adjuntos/interrupcion/{inter.id}/anverso").status_code == 404


def test_una_foto_sin_subir_da_404(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador, foto_anverso=None, foto_reverso=None)
    db.session.commit()

    entrar(cliente, despachador)
    assert cliente.get(f"/adjuntos/orden/{orden.id}/anverso").status_code == 404


def test_si_el_storage_no_firma_responde_503(
    cliente, nueva_orden, despachador, monkeypatch
):
    orden = nueva_orden(despachador)
    db.session.commit()

    monkeypatch.setattr(storage, "url_prefirmada", lambda clave, segundos=None: None)
    entrar(cliente, despachador)
    assert cliente.get(f"/adjuntos/orden/{orden.id}/anverso").status_code == 503


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
def test_sin_sesion_no_se_entrega_nada(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    db.session.commit()
    salir(cliente)
    assert cliente.get(f"/adjuntos/orden/{orden.id}/anverso").status_code == 302


def test_un_operador_ajeno_no_ve_la_foto(
    cliente, nueva_orden, despachador, operador, operador_b
):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, operador)
    assert cliente.get(f"/adjuntos/orden/{orden.id}/anverso").status_code == 302
    salir(cliente)

    entrar(cliente, operador_b)
    assert cliente.get(f"/adjuntos/orden/{orden.id}/anverso").status_code == 403


def test_el_agente_de_fibra_ve_la_foto_solo_si_esta_derivada(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, agente_fibra)
    assert cliente.get(f"/adjuntos/interrupcion/{inter.id}/foto").status_code == 403
    salir(cliente)

    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="posible corte", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()

    entrar(cliente, agente_fibra)
    assert cliente.get(f"/adjuntos/interrupcion/{inter.id}/foto").status_code == 302


def test_el_detalle_enlaza_a_la_foto_por_esta_ruta(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = cliente.get(orden.url_detalle).get_data(as_text=True)
    assert f"/adjuntos/orden/{orden.id}/anverso" in cuerpo

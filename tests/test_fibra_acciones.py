"""Bandeja de fibra: orden, busqueda, modal y limites del agente.

Complementa test_fibra_bandeja.py, que cubre el listado y las demoras.
"""
from __future__ import annotations

from app.extensions import db
from app.models.enums import Dependencia, EstadoFibra, EstadoInterrupcion
from app.services.estados import ejecutar_transicion

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    return cliente.post("/login", data={"usuario": usuario.usuario, "password": CLAVE})


def derivar(inter, operador, comentario="posible corte"):
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario=comentario, dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()


def texto(cliente, ruta):
    respuesta = cliente.get(ruta)
    assert respuesta.status_code == 200, ruta
    return respuesta.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Modal de la bandeja
# ---------------------------------------------------------------------------
def test_el_modal_pide_comentario(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    derivar(inter, operador)

    entrar(cliente, agente_fibra)
    cuerpo = texto(
        cliente, f"/fibra/accion/{inter.id}?transicion=estado_fibra:FIBRA_OK"
    )
    assert "Marcar fibra OK" in cuerpo
    assert 'name="comentario"' in cuerpo
    assert inter.folio in cuerpo


def test_el_modal_rechaza_una_transicion_de_estado(
    cliente, nueva_interrupcion, despachador, operador, admin
):
    """Un admin si tiene la transicion de estado, pero no desde esta bandeja."""
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    derivar(inter, operador)

    entrar(cliente, admin)
    respuesta = cliente.get(f"/fibra/accion/{inter.id}?transicion=estado:CERRADA")
    assert respuesta.status_code == 403


def test_el_modal_de_una_transicion_imposible_explica(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    derivar(inter, operador)

    entrar(cliente, agente_fibra)
    respuesta = cliente.get(f"/fibra/accion/{inter.id}?transicion=estado_fibra:EN_REVISION")
    assert respuesta.status_code == 200
    assert "no esta permitido" in respuesta.get_data(as_text=True)


def test_el_modal_de_algo_que_no_existe_da_404(cliente, agente_fibra):
    entrar(cliente, agente_fibra)
    assert cliente.get("/fibra/accion/987654").status_code == 404


def test_una_interrupcion_sin_derivar_no_se_ve_en_fibra(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, agente_fibra)
    assert inter.folio not in texto(cliente, "/fibra/")
    assert cliente.get(f"/fibra/accion/{inter.id}").status_code == 403


# ---------------------------------------------------------------------------
# Busqueda, orden y vista ampliada
# ---------------------------------------------------------------------------
def test_la_bandeja_busca(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    una = nueva_interrupcion(
        despachador, asignado_a=operador, nombre_cliente="Hotel Las Palmas"
    )
    otra = nueva_interrupcion(
        despachador, identificador_externo="FD222222", asignado_a=operador,
        nombre_cliente="Bodegon Central",
    )
    derivar(una, operador)
    derivar(otra, operador)

    entrar(cliente, agente_fibra)
    cuerpo = texto(cliente, "/fibra/?q=Palmas")
    assert una.folio in cuerpo
    assert otra.folio not in cuerpo

    # Tambien por folio e identificador.
    assert una.folio in texto(cliente, f"/fibra/?q={una.folio}")
    assert otra.folio in texto(cliente, "/fibra/?q=FD222222")


def test_la_bandeja_filtra_por_prioridad(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    critica = nueva_interrupcion(
        despachador, asignado_a=operador, prioridad="CRITICA"
    )
    baja = nueva_interrupcion(
        despachador, identificador_externo="FD222222", asignado_a=operador,
        prioridad="BAJA",
    )
    derivar(critica, operador)
    derivar(baja, operador)

    entrar(cliente, agente_fibra)
    cuerpo = texto(cliente, "/fibra/?prioridad=CRITICA")
    assert critica.folio in cuerpo
    assert baja.folio not in cuerpo


def test_los_ordenes_de_la_bandeja(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    derivar(inter, operador)

    entrar(cliente, agente_fibra)
    for orden in ("recientes", "prioridad", "cliente", "antiguas", "inventado"):
        assert inter.folio in texto(cliente, f"/fibra/?orden={orden}"), orden


def test_la_columna_ampliada(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    derivar(inter, operador)

    entrar(cliente, agente_fibra)
    assert "ampliada" in texto(cliente, "/fibra/?ampliada=EN_REVISION")
    # Un valor que no es un estado de fibra se ignora sin romper.
    assert cliente.get("/fibra/?ampliada=LO_QUE_SEA").status_code == 200


def test_el_refresco_parcial_de_la_bandeja(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    derivar(inter, operador)

    entrar(cliente, agente_fibra)
    cuerpo = texto(cliente, "/fibra/columnas")
    assert inter.folio in cuerpo
    assert "<html" not in cuerpo


# ---------------------------------------------------------------------------
# Mover desde la bandeja
# ---------------------------------------------------------------------------
def test_el_agente_responde_y_se_redibuja(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    derivar(inter, operador)

    entrar(cliente, agente_fibra)
    respuesta = cliente.post(
        f"/fibra/mover/{inter.id}",
        data={
            "transicion": "estado_fibra:FIBRA_OK",
            "comentario": "Tramo medido con OTDR sin novedad",
        },
    )
    assert respuesta.status_code == 200
    assert "<html" not in respuesta.get_data(as_text=True)
    db.session.refresh(inter)
    assert inter.estado_fibra is EstadoFibra.FIBRA_OK


def test_sin_comentario_no_se_mueve(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    derivar(inter, operador)

    entrar(cliente, agente_fibra)
    respuesta = cliente.post(
        f"/fibra/mover/{inter.id}", data={"transicion": "estado_fibra:FIBRA_OK"}
    )
    assert "exige un comentario" in respuesta.get_data(as_text=True)
    db.session.refresh(inter)
    assert inter.estado_fibra is EstadoFibra.EN_REVISION


def test_el_agente_corrige_su_respuesta(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    derivar(inter, operador)

    entrar(cliente, agente_fibra)
    for destino, esperado in (
        ("FIBRA_OK", EstadoFibra.FIBRA_OK),
        ("FIBRA_CON_FALLA", EstadoFibra.FIBRA_CON_FALLA),
        ("EN_REVISION", EstadoFibra.EN_REVISION),
    ):
        cliente.post(
            f"/fibra/mover/{inter.id}",
            data={"transicion": f"estado_fibra:{destino}", "comentario": f"paso a {destino}"},
        )
        db.session.refresh(inter)
        assert inter.estado_fibra is esperado
    assert inter.estado is EstadoInterrupcion.DERIVADA_FIBRA, "el estado no lo toca"


def test_el_operador_no_entra_a_la_bandeja(cliente, operador):
    entrar(cliente, operador)
    assert cliente.get("/fibra/").status_code == 403
    assert cliente.get("/fibra/columnas").status_code == 403
    assert cliente.post("/fibra/mover/1", data={}).status_code == 403


def test_sin_sesion_tampoco(cliente, app):
    assert cliente.get("/fibra/").status_code == 302

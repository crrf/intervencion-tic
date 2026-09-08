"""Maquinas de estado: quien puede mover que, y con que datos."""
from __future__ import annotations

import pytest

from app.extensions import db
from app.models.enums import Dependencia, EstadoFibra, EstadoInterrupcion, EstadoOrden
from app.services.estados import (
    TransicionInvalida,
    ejecutar_transicion,
    transiciones_permitidas,
)


def claves(ticket, usuario):
    return {t.clave for t in transiciones_permitidas(ticket, usuario)}


# ---------------------------------------------------------------------------
# Orden de trabajo
# ---------------------------------------------------------------------------
def test_solo_el_despachador_asigna_una_orden_nueva(nueva_orden, despachador, operador, admin):
    orden = nueva_orden(despachador)
    assert "estado:ASIGNADA" in claves(orden, despachador)
    assert "estado:ASIGNADA" in claves(orden, admin)
    assert claves(orden, operador) == set()


def test_flujo_completo_de_una_orden(nueva_orden, despachador, operador):
    orden = nueva_orden(despachador)

    ejecutar_transicion(orden, despachador, "estado:ASIGNADA", asignado_a=operador)
    db.session.commit()
    assert orden.estado is EstadoOrden.ASIGNADA
    assert orden.asignado_a_id == operador.id
    assert orden.asignado_en is not None

    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    db.session.commit()
    assert orden.estado is EstadoOrden.EN_PROCESO

    ejecutar_transicion(orden, operador, "estado:CERRADA", comentario="Trabajo terminado")
    db.session.commit()
    assert orden.estado is EstadoOrden.CERRADA
    assert orden.cerrado_en is not None
    assert orden.comentarios[-1].texto == "Trabajo terminado"


def test_cerrar_sin_comentario_falla(nueva_orden, despachador, operador):
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    db.session.commit()

    with pytest.raises(TransicionInvalida, match="comentario"):
        ejecutar_transicion(orden, operador, "estado:CERRADA")


def test_dejar_abierta_exige_motivo(nueva_orden, despachador, operador):
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    db.session.commit()

    with pytest.raises(TransicionInvalida, match="motivo"):
        ejecutar_transicion(orden, operador, "estado:ABIERTA_CON_MOTIVO", comentario="algo")

    ejecutar_transicion(
        orden, operador, "estado:ABIERTA_CON_MOTIVO",
        comentario="No hubo acceso", motivo="Cliente ausente",
    )
    db.session.commit()
    assert orden.estado is EstadoOrden.ABIERTA_CON_MOTIVO
    assert orden.motivo_apertura == "Cliente ausente"


def test_un_operador_ajeno_no_puede_mover_la_orden(nueva_orden, despachador, operador, operador_b):
    orden = nueva_orden(despachador, asignado_a=operador)
    assert claves(orden, operador_b) == set()
    with pytest.raises(TransicionInvalida):
        ejecutar_transicion(orden, operador_b, "estado:EN_PROCESO")


def test_solo_el_admin_reabre(nueva_orden, despachador, operador, admin):
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:CERRADA", comentario="listo")
    db.session.commit()

    assert claves(orden, operador) == set()
    assert "estado:EN_PROCESO" in claves(orden, admin)

    ejecutar_transicion(orden, admin, "estado:EN_PROCESO", comentario="Se reabre por revision")
    db.session.commit()
    assert orden.estado is EstadoOrden.EN_PROCESO
    assert orden.cerrado_en is None


# ---------------------------------------------------------------------------
# Interrupcion
# ---------------------------------------------------------------------------
def test_no_se_puede_cerrar_sin_clasificar_la_dependencia(
    nueva_interrupcion, despachador, operador
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    db.session.commit()
    assert inter.dependencia is None

    with pytest.raises(TransicionInvalida, match="dependencia"):
        ejecutar_transicion(inter, operador, "estado:CERRADA", comentario="resuelto")


def test_derivar_a_fibra_exige_capa_fisica(nueva_interrupcion, despachador, operador):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    db.session.commit()

    with pytest.raises(TransicionInvalida, match="capa fisica"):
        ejecutar_transicion(
            inter, operador, "estado:DERIVADA_FIBRA",
            comentario="parece fibra", dependencia=Dependencia.CORE_IPMPLS,
        )

    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="Se descarto equipo activo", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()
    assert inter.estado is EstadoInterrupcion.DERIVADA_FIBRA
    assert inter.estado_fibra is EstadoFibra.EN_REVISION
    assert inter.derivado_fibra_en is not None


def test_el_agente_de_fibra_solo_mueve_estado_fibra(
    nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="posible corte", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()

    permitidas = claves(inter, agente_fibra)
    assert permitidas == {"estado_fibra:FIBRA_OK", "estado_fibra:FIBRA_CON_FALLA"}

    # No puede cerrar la interrupcion ni devolverla al operador.
    with pytest.raises(TransicionInvalida):
        ejecutar_transicion(inter, agente_fibra, "estado:CERRADA", comentario="ya")

    ejecutar_transicion(
        inter, agente_fibra, "estado_fibra:FIBRA_CON_FALLA",
        comentario="Corte confirmado en el tramo aereo",
    )
    db.session.commit()
    assert inter.estado_fibra is EstadoFibra.FIBRA_CON_FALLA
    assert inter.agente_fibra_id == agente_fibra.id
    assert inter.respuesta_fibra_en is not None
    assert inter.estado is EstadoInterrupcion.DERIVADA_FIBRA  # el estado no lo toca


def test_el_agente_de_fibra_no_ve_ordenes(nueva_orden, despachador, agente_fibra):
    orden = nueva_orden(despachador)
    assert claves(orden, agente_fibra) == set()


def test_la_respuesta_de_fibra_exige_comentario(
    nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="posible corte", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()

    with pytest.raises(TransicionInvalida, match="comentario"):
        ejecutar_transicion(inter, agente_fibra, "estado_fibra:FIBRA_OK")


def test_el_operador_cierra_tras_la_respuesta_de_fibra(
    nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="posible corte", dependencia=Dependencia.CAPA_FISICA,
    )
    ejecutar_transicion(
        inter, agente_fibra, "estado_fibra:FIBRA_OK", comentario="Tramo medido sin novedad"
    )
    db.session.commit()

    assert "estado:CERRADA" in claves(inter, operador)
    ejecutar_transicion(inter, operador, "estado:CERRADA", comentario="Se corrigio en el equipo")
    db.session.commit()
    assert inter.estado is EstadoInterrupcion.CERRADA
    assert inter.cerrado_en is not None


def test_transicion_inexistente_es_rechazada(nueva_orden, despachador):
    orden = nueva_orden(despachador)
    with pytest.raises(TransicionInvalida):
        ejecutar_transicion(orden, despachador, "estado:CERRADA", comentario="x")

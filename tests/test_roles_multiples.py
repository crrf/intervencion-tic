"""Un mismo usuario con varios roles: los permisos son la UNION."""
from __future__ import annotations

import pytest

from app.extensions import db
from app.models.enums import Dependencia, EstadoOrden, RolUsuario
from app.security.decoradores import filtro_interrupciones, filtro_ordenes, puede_ver
from app.services.estados import (
    TransicionInvalida,
    ejecutar_transicion,
    transiciones_permitidas,
)


def claves(ticket, usuario):
    return {t.clave for t in transiciones_permitidas(ticket, usuario)}


def test_el_usuario_mixto_tiene_los_dos_roles(mixto):
    assert mixto.tiene_rol(RolUsuario.DESPACHADOR)
    assert mixto.tiene_rol(RolUsuario.OPERADOR)
    assert not mixto.tiene_rol(RolUsuario.ADMIN)
    assert mixto.tiene_alguno(RolUsuario.ADMIN, RolUsuario.OPERADOR)


def test_se_asigna_a_si_mismo_y_cierra(nueva_orden, mixto):
    orden = nueva_orden(mixto)

    # Como despachador puede asignar; se elige a si mismo porque es operador.
    ejecutar_transicion(orden, mixto, "estado:ASIGNADA", asignado_a=mixto)
    db.session.commit()
    assert orden.asignado_a_id == mixto.id

    # Como operador asignado la trabaja y da el OK...
    ejecutar_transicion(orden, mixto, "estado:EN_PROCESO")
    ejecutar_transicion(orden, mixto, "estado:OK_OPERADOR", comentario="Resuelto en sitio")
    db.session.commit()
    assert orden.estado is EstadoOrden.OK_OPERADOR

    # ...y como despachador la marca cerrada en SIPREC.
    ejecutar_transicion(orden, mixto, "estado:CERRADA", comentario="Cerrada en SIPREC")
    db.session.commit()
    assert orden.estado is EstadoOrden.CERRADA


def test_ve_todo_pero_solo_trabaja_lo_suyo(nueva_orden, mixto, despachador, operador):
    ajena = nueva_orden(despachador, asignado_a=operador)
    propia = nueva_orden(despachador, asignado_a=mixto)

    # Ve ambas por su rol de despachador...
    assert puede_ver(ajena, mixto) is True
    assert puede_ver(propia, mixto) is True

    # ...pero las transiciones de operador solo aplican sobre la suya.
    assert "estado:EN_PROCESO" in claves(propia, mixto)
    assert "estado:EN_PROCESO" not in claves(ajena, mixto)


def test_no_gana_los_permisos_de_fibra(nueva_interrupcion, mixto, despachador, operador):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="corte probable", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()

    assert not any(c.startswith("estado_fibra:") for c in claves(inter, mixto))
    with pytest.raises(TransicionInvalida):
        ejecutar_transicion(inter, mixto, "estado_fibra:FIBRA_OK", comentario="x")


def test_la_visibilidad_del_mixto_no_tiene_restriccion(app, mixto):
    # Al ser despachador, sus consultas no llevan filtro.
    assert filtro_ordenes(mixto) is None
    assert filtro_interrupciones(mixto) is None


def test_operador_puro_si_tiene_filtro(app, operador):
    assert filtro_ordenes(operador) is not None
    assert filtro_interrupciones(operador) is not None


def test_el_mixto_entra_a_la_gestion(cliente, mixto):
    cliente.post("/login", data={"usuario": mixto.usuario, "password": "Clave.2026"})
    assert cliente.get("/dashboard/").status_code == 200
    assert cliente.get("/buscar/").status_code == 200
    assert cliente.get("/ordenes/nueva").status_code == 200


def test_el_selector_de_operadores_incluye_al_mixto(app, mixto, operador):
    from app.blueprints._acciones import operadores_activos

    ids = {u.id for u in operadores_activos()}
    assert mixto.id in ids
    assert operador.id in ids


def test_no_se_puede_asignar_a_quien_no_es_operador(nueva_orden, despachador, agente_fibra):
    orden = nueva_orden(despachador)
    with pytest.raises(TransicionInvalida, match="operador activo"):
        ejecutar_transicion(orden, despachador, "estado:ASIGNADA", asignado_a=agente_fibra)

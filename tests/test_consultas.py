"""Busqueda unificada sobre las dos tablas de ticket."""
from __future__ import annotations

from datetime import timedelta

from app.extensions import db
from app.models.base import ahora
from app.services.consultas import Filtros, buscar, resolver_rango


def hacer(nueva_orden, nueva_interrupcion, despachador, operador):
    orden = nueva_orden(
        despachador, identificador_externo="ED123456", nombre_cliente="Clinica San Rafael"
    )
    inter = nueva_interrupcion(
        despachador, identificador_externo="ED123999", nombre_cliente="Hotel Mirador",
        asignado_a=operador,
    )
    otra = nueva_interrupcion(
        despachador, identificador_externo="FD777777", nombre_cliente="Banco del Sur"
    )
    return orden, inter, otra


def test_busca_por_identificador_parcial_en_ambos_tipos(
    nueva_orden, nueva_interrupcion, despachador, operador, admin
):
    orden, inter, otra = hacer(nueva_orden, nueva_interrupcion, despachador, operador)

    datos = buscar(Filtros(texto="ED123"), admin)
    folios = {f["folio"] for f in datos["filas"]}
    assert folios == {orden.folio, inter.folio}
    assert datos["total"] == 2


def test_busca_por_folio_completo(nueva_orden, despachador, admin):
    orden = nueva_orden(despachador)
    datos = buscar(Filtros(texto=orden.folio), admin)
    assert datos["total"] == 1
    assert datos["filas"][0]["folio"] == orden.folio


def test_busca_en_los_comentarios(nueva_orden, despachador, operador, admin):
    from app.services.tickets import comentar

    orden = nueva_orden(despachador, asignado_a=operador)
    comentar(orden, operador, "Se reemplazo el conector SC/APC del ODF")

    datos = buscar(Filtros(texto="SC/APC"), admin)
    assert datos["total"] == 1
    assert datos["filas"][0]["folio"] == orden.folio


def test_filtra_por_tipo(nueva_orden, nueva_interrupcion, despachador, operador, admin):
    hacer(nueva_orden, nueva_interrupcion, despachador, operador)

    assert buscar(Filtros(tipo="ORDEN"), admin)["total"] == 1
    assert buscar(Filtros(tipo="INTERRUPCION"), admin)["total"] == 2


def test_filtra_por_operador_asignado(
    nueva_orden, nueva_interrupcion, despachador, operador, admin
):
    _, inter, _ = hacer(nueva_orden, nueva_interrupcion, despachador, operador)
    datos = buscar(Filtros(asignado_a_id=operador.id), admin)
    assert datos["total"] == 1
    assert datos["filas"][0]["folio"] == inter.folio


def test_el_rango_de_fechas_excluye_lo_de_fuera(nueva_orden, despachador, admin):
    viejo = nueva_orden(despachador)
    viejo.creado_en = ahora() - timedelta(days=200)
    db.session.commit()
    reciente = nueva_orden(despachador, identificador_externo="ED000111")

    filtros = Filtros(preset="30d")
    filtros.rango = resolver_rango("30d")[:2]
    datos = buscar(filtros, admin)

    folios = {f["folio"] for f in datos["filas"]}
    assert reciente.folio in folios
    assert viejo.folio not in folios


def test_la_paginacion_no_repite_ni_omite(nueva_orden, despachador, admin):
    creados = {nueva_orden(despachador).folio for _ in range(12)}

    vistos = []
    for pagina in (1, 2, 3):
        datos = buscar(Filtros(), admin, pagina=pagina, por_pagina=5)
        vistos.extend(f["folio"] for f in datos["filas"])
        assert datos["total"] == 12
        assert datos["paginas"] == 3

    assert len(vistos) == 12
    assert set(vistos) == creados


def test_el_operador_solo_ve_lo_suyo(
    nueva_orden, nueva_interrupcion, despachador, operador, operador_b
):
    hacer(nueva_orden, nueva_interrupcion, despachador, operador)

    assert buscar(Filtros(), operador)["total"] == 1
    assert buscar(Filtros(), operador_b)["total"] == 0


def test_las_filas_traen_etiquetas_listas_para_mostrar(nueva_orden, despachador, admin):
    orden = nueva_orden(despachador)
    fila = buscar(Filtros(), admin)["filas"][0]

    assert fila["tipo_etiqueta"] == "Orden de trabajo"
    assert fila["estado_etiqueta"] == "Nueva"
    assert fila["url"].endswith(str(orden.id))
    assert fila["minutos_resolucion"] is None

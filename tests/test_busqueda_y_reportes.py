"""Buscador, reportes y dashboard: filtros, orden, paginacion y parciales."""
from __future__ import annotations

from datetime import timedelta

from app.extensions import db
from app.models.base import ahora
from app.models.enums import Dependencia, EstadoFibra
from app.services.consultas import Filtros, buscar, iterar_todo, resolver_rango
from app.services.estados import ejecutar_transicion

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    return cliente.post("/login", data={"usuario": usuario.usuario, "password": CLAVE})


def texto(cliente, ruta, **kwargs):
    respuesta = cliente.get(ruta, **kwargs)
    assert respuesta.status_code == 200, ruta
    return respuesta.get_data(as_text=True)


def resultados(cliente, ruta):
    """Solo la tabla de resultados.

    La pagina completa del buscador trae un placeholder de ejemplo con un
    folio dentro, asi que comprobar "este folio NO aparece" sobre el HTML
    entero da falsos negativos. El parcial de HTMX es solo la tabla.
    """
    return texto(cliente, ruta, headers={"HX-Request": "true"})


# ---------------------------------------------------------------------------
# Buscador: filtros
# ---------------------------------------------------------------------------
def test_busca_por_texto_libre(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador, nombre_cliente="Ferreteria El Tornillo")
    otra = nueva_orden(
        despachador, identificador_externo="ED222222", nombre_cliente="Panaderia"
    )
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = resultados(cliente, "/buscar/?texto=Tornillo")
    assert orden.folio in cuerpo
    assert otra.folio not in cuerpo


def test_busca_en_los_comentarios(cliente, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador, asignado_a=operador)
    from app.services.tickets import comentar

    comentar(orden, operador, "Se cambio el conector SC/APC")
    db.session.commit()

    entrar(cliente, despachador)
    assert orden.folio in resultados(cliente, "/buscar/?texto=SC/APC")


def test_filtra_por_tipo_estado_y_prioridad(
    cliente, nueva_orden, nueva_interrupcion, despachador, operador
):
    orden = nueva_orden(despachador, prioridad="CRITICA")
    inter = nueva_interrupcion(despachador, prioridad="BAJA", asignado_a=operador)
    db.session.commit()

    entrar(cliente, despachador)
    solo_ordenes = resultados(cliente, "/buscar/?tipo=ORDEN")
    assert orden.folio in solo_ordenes and inter.folio not in solo_ordenes

    criticas = resultados(cliente, "/buscar/?prioridad=CRITICA")
    assert orden.folio in criticas and inter.folio not in criticas

    asignadas = resultados(cliente, "/buscar/?estado=ASIGNADA")
    assert inter.folio in asignadas and orden.folio not in asignadas


def test_filtra_por_dependencia_y_estado_de_fibra(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    otra = nueva_interrupcion(
        despachador, identificador_externo="FD222222", asignado_a=operador
    )
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="corte", dependencia=Dependencia.CAPA_FISICA,
    )
    ejecutar_transicion(
        inter, agente_fibra, "estado_fibra:FIBRA_CON_FALLA", comentario="confirmado"
    )
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = resultados(cliente, "/buscar/?dependencia=CAPA_FISICA")
    assert inter.folio in cuerpo and otra.folio not in cuerpo

    cuerpo = resultados(
        cliente, f"/buscar/?estado_fibra={EstadoFibra.FIBRA_CON_FALLA.name}"
    )
    assert inter.folio in cuerpo and otra.folio not in cuerpo


def test_filtra_por_personas(
    cliente, nueva_orden, despachador, operador, operador_b, admin
):
    mia = nueva_orden(despachador, asignado_a=operador)
    suya = nueva_orden(
        despachador, identificador_externo="ED222222", asignado_a=operador_b
    )
    del_admin = nueva_orden(admin, identificador_externo="ED333333")
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = resultados(cliente, f"/buscar/?asignado_a_id={operador.id}")
    assert mia.folio in cuerpo and suya.folio not in cuerpo

    cuerpo = resultados(cliente, f"/buscar/?creado_por_id={admin.id}")
    assert del_admin.folio in cuerpo and mia.folio not in cuerpo


def test_filtra_por_rango_de_fechas(cliente, nueva_orden, despachador):
    vieja = nueva_orden(despachador)
    vieja.creado_en = ahora() - timedelta(days=200)
    nueva = nueva_orden(despachador, identificador_externo="ED222222")
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = resultados(cliente, "/buscar/?preset=30d")
    assert nueva.folio in cuerpo
    assert vieja.folio not in cuerpo


def test_sin_filtros_invita_a_buscar(cliente, despachador):
    entrar(cliente, despachador)
    assert "para empezar" in texto(cliente, "/buscar/")


def test_el_parcial_de_htmx_solo_trae_la_tabla(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = texto(cliente, "/buscar/?texto=ED", headers={"HX-Request": "true"})
    assert orden.folio in cuerpo
    assert "<html" not in cuerpo


# ---------------------------------------------------------------------------
# Buscador: orden y paginacion (a nivel de servicio, mas barato)
# ---------------------------------------------------------------------------
def test_la_paginacion_reparte_las_filas(app, nueva_orden, despachador, admin):
    for i in range(7):
        nueva_orden(despachador, identificador_externo=f"ED10000{i}")
    db.session.commit()

    primera = buscar(Filtros(), admin, pagina=1, por_pagina=3)
    assert primera["total"] == 7
    assert primera["paginas"] == 3
    assert len(primera["filas"]) == 3

    ultima = buscar(Filtros(), admin, pagina=3, por_pagina=3)
    assert len(ultima["filas"]) == 1

    # Una pagina fuera de rango no revienta.
    vacia = buscar(Filtros(), admin, pagina=99, por_pagina=3)
    assert vacia["filas"] == []


def test_se_ordena_por_la_columna_pedida(app, nueva_orden, despachador, admin):
    a = nueva_orden(despachador, identificador_externo="ED100001", nombre_cliente="Ana")
    z = nueva_orden(despachador, identificador_externo="ED100002", nombre_cliente="Zoe")
    db.session.commit()

    ascendente = buscar(
        Filtros(ordenar_por="nombre_cliente", direccion="asc"), admin
    )["filas"]
    assert [f["folio"] for f in ascendente] == [a.folio, z.folio]

    descendente = buscar(
        Filtros(ordenar_por="nombre_cliente", direccion="desc"), admin
    )["filas"]
    assert [f["folio"] for f in descendente] == [z.folio, a.folio]


def test_un_orden_inventado_cae_en_el_de_siempre(app):
    f = Filtros.desde_request({"ordenar_por": "lo_que_sea", "direccion": "arriba"})
    assert f.ordenar_por == "creado_en"
    assert f.direccion == "desc"


def test_iterar_todo_recorre_todas_las_paginas(app, nueva_orden, despachador, admin):
    for i in range(5):
        nueva_orden(despachador, identificador_externo=f"ED10000{i}")
    db.session.commit()

    folios = [f["folio"] for f in iterar_todo(Filtros(), admin, lote=2)]
    assert len(folios) == 5
    assert len(set(folios)) == 5


def test_el_operador_solo_busca_lo_suyo_en_el_servicio(
    app, nueva_orden, despachador, operador, operador_b
):
    """El filtro de visibilidad va en la consulta, no en la plantilla."""
    mia = nueva_orden(despachador, asignado_a=operador)
    nueva_orden(despachador, identificador_externo="ED222222", asignado_a=operador_b)
    db.session.commit()

    folios = [f["folio"] for f in buscar(Filtros(), operador)["filas"]]
    assert folios == [mia.folio]


# ---------------------------------------------------------------------------
# Reportes
# ---------------------------------------------------------------------------
def test_el_historico_resume_el_periodo(
    cliente, nueva_orden, despachador, operador
):
    abierta = nueva_orden(despachador, asignado_a=operador)
    cerrada = nueva_orden(
        despachador, identificador_externo="ED222222", asignado_a=operador
    )
    ejecutar_transicion(cerrada, operador, "estado:EN_PROCESO")
    ejecutar_transicion(cerrada, operador, "estado:OK_OPERADOR", comentario="listo")
    ejecutar_transicion(cerrada, despachador, "estado:CERRADA", comentario="en SIPREC")
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = texto(cliente, "/reportes/historico?preset=30d")
    assert abierta.folio in cuerpo
    assert cerrada.folio in cuerpo


def test_el_historico_tiene_parcial_htmx(cliente, nueva_orden, despachador):
    nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = texto(
        cliente, "/reportes/historico?preset=30d", headers={"HX-Request": "true"}
    )
    assert "<html" not in cuerpo


def test_la_bitacora_lista_los_eventos(
    cliente, nueva_orden, despachador, operador
):
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = texto(cliente, "/reportes/auditoria?preset=30d")
    assert orden.folio in cuerpo
    assert "Cambio de estado" in cuerpo
    assert operador.nombre_completo in cuerpo


def test_la_bitacora_tiene_parcial_htmx(cliente, nueva_orden, despachador):
    nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = texto(
        cliente, "/reportes/auditoria?preset=30d", headers={"HX-Request": "true"}
    )
    assert "<html" not in cuerpo


def test_un_preset_inventado_no_rompe_los_reportes(cliente, despachador):
    entrar(cliente, despachador)
    assert cliente.get("/reportes/historico?preset=siempre").status_code == 200
    assert cliente.get("/reportes/auditoria?preset=siempre").status_code == 200


def test_el_rango_a_medida(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    db.session.commit()
    hoy = ahora().date().isoformat()

    entrar(cliente, despachador)
    cuerpo = texto(
        cliente, f"/reportes/historico?preset=personalizado&desde={hoy}&hasta={hoy}"
    )
    assert orden.folio in cuerpo


def test_las_fechas_al_reves_se_ordenan_solas(app):
    inicio, fin, _ = resolver_rango("personalizado", "2026-10-05", "2026-10-01")
    assert inicio < fin


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def test_el_dashboard_pinta_las_tarjetas_y_la_tabla(
    cliente, nueva_orden, despachador, operador
):
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:OK_OPERADOR", comentario="listo")
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = texto(cliente, "/dashboard/")
    assert "Abiertos ahora" in cuerpo
    assert "por cerrar en SIPREC" in cuerpo
    assert operador.nombre_completo in cuerpo


def test_el_dashboard_sin_datos_no_falla(cliente, despachador):
    entrar(cliente, despachador)
    assert "Dashboard" in texto(cliente, "/dashboard/")

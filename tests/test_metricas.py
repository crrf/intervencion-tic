"""Metricas del dashboard."""
from __future__ import annotations

from datetime import timedelta

from app.extensions import db
from app.models.base import ahora
from app.models.enums import Dependencia
from app.services import metricas
from app.services.consultas import resolver_rango
from app.services.estados import ejecutar_transicion


def rango():
    return resolver_rango("30d")[:2]


def fila_de(filas, usuario):
    return next(f for f in filas if f["operador"].id == usuario.id)


def test_las_soluciones_se_atribuyen_a_quien_cerro(
    nueva_orden, despachador, operador, operador_b, admin
):
    """El ticket lo cierra el operador B tras una reasignacion: la solucion es suya."""
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    db.session.commit()

    from app.services.tickets import reasignar

    reasignar(orden, despachador, operador_b)
    ejecutar_transicion(orden, operador_b, "estado:CERRADA", comentario="cerrado por B")
    db.session.commit()

    filas = metricas.por_operador(rango(), admin)
    assert fila_de(filas, operador_b)["soluciones"] == 1
    assert fila_de(filas, operador)["soluciones"] == 0


def test_pendientes_es_un_corte_actual(nueva_orden, despachador, operador, admin):
    abierta = nueva_orden(despachador, asignado_a=operador)
    cerrada = nueva_orden(despachador, asignado_a=operador, identificador_externo="ED222222")

    ejecutar_transicion(cerrada, operador, "estado:EN_PROCESO")
    ejecutar_transicion(cerrada, operador, "estado:CERRADA", comentario="listo")
    db.session.commit()

    fila = fila_de(metricas.por_operador(rango(), admin), operador)
    assert fila["pendientes"] == 1
    assert fila["soluciones"] == 1
    assert fila["asignados"] == 2
    assert fila["porcentaje_cierre"] == 50
    assert abierta.abierto


def test_resumen_general(nueva_orden, nueva_interrupcion, despachador, operador, admin):
    nueva_orden(despachador)
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="corte", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()

    r = metricas.resumen(rango(), admin)
    assert r["abiertos"] == 2
    assert r["creados_periodo"] == 2
    assert r["cerrados_periodo"] == 0
    assert r["en_fibra"] == 1
    assert r["fibra_sin_respuesta"] == 1


def test_metricas_de_fibra(nueva_interrupcion, despachador, operador, agente_fibra):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="corte", dependencia=Dependencia.CAPA_FISICA,
    )
    ejecutar_transicion(
        inter, agente_fibra, "estado_fibra:FIBRA_CON_FALLA", comentario="corte confirmado"
    )
    db.session.commit()

    f = metricas.por_agente_fibra(rango())
    assert f["recibidas"] == 1
    assert f["con_falla"] == 1
    assert f["ok"] == 0
    assert f["agentes"][0]["agente"] == agente_fibra.nombre_completo


def test_serie_diaria_cubre_todo_el_rango(nueva_orden, despachador, admin):
    nueva_orden(despachador)
    serie = metricas.serie_diaria(rango(), admin)

    assert len(serie["etiquetas"]) == 30
    assert sum(serie["creados"]) == 1
    assert sum(serie["cerrados"]) == 0


def test_por_dependencia_cuenta_las_sin_clasificar(
    nueva_interrupcion, despachador, operador, admin
):
    nueva_interrupcion(despachador)
    clasificada = nueva_interrupcion(
        despachador, asignado_a=operador, identificador_externo="FD999999"
    )
    ejecutar_transicion(clasificada, operador, "estado:EN_PROCESO")
    from app.services.tickets import clasificar_dependencia

    clasificar_dependencia(clasificada, operador, Dependencia.CORE_IPMPLS)

    datos = {d["etiqueta"]: d["n"] for d in metricas.por_dependencia(rango(), admin)}
    assert datos["Por diagnosticar"] == 1
    assert datos["Core (IPMPLS)"] == 1


def test_el_periodo_acota_las_cifras(nueva_orden, despachador, operador, admin):
    vieja = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(vieja, operador, "estado:EN_PROCESO")
    ejecutar_transicion(vieja, operador, "estado:CERRADA", comentario="listo")
    db.session.commit()

    # Se envejece el cierre: queda fuera de la ventana de 30 dias pero dentro
    # de la de 90 (que abarca los ultimos 89 dias).
    vieja.cerrado_en = ahora() - timedelta(days=60)
    db.session.commit()

    assert metricas.resumen(rango(), admin)["cerrados_periodo"] == 0
    assert metricas.resumen(resolver_rango("90d")[:2], admin)["cerrados_periodo"] == 1


def test_panel_completo_no_falla_sin_datos(app, admin):
    panel = metricas.panel_completo(rango(), admin)
    assert panel["resumen"]["abiertos"] == 0
    assert panel["operadores"] == []
    assert panel["dependencias"] == []

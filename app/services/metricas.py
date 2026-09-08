"""Agregados del dashboard de desempeno.

Todas las cifras se calculan sobre la CTE unificada de `consultas.py`, salvo
las "soluciones", que se atribuyen desde el historial: cuenta quien ejecuto
realmente la transicion a Cerrada, no a quien figuraba como asignado. Asi un
ticket que cambio de manos se le acredita a quien lo resolvio.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import Date, cast, func, select

from app.extensions import db
from app.models.enums import (
    Dependencia,
    EstadoFibra,
    EstadoInterrupcion,
    EstadoOrden,
    RolUsuario,
    TipoTicket,
)
from app.models.historial import Historial
from app.models.interrupcion import Interrupcion
from app.models.usuario import Usuario, UsuarioRol
from app.services.consultas import cte_tickets, zona_app

#: Etiqueta que la maquina de estados escribe en el historial al cerrar.
#: Se deriva del enum para que renombrar el estado no rompa las metricas.
ETIQUETA_CERRADA = EstadoOrden.CERRADA.etiqueta
ETIQUETA_DERIVADA = EstadoInterrupcion.DERIVADA_FIBRA.etiqueta

ESTADOS_ABIERTOS_CON_MOTIVO = (
    EstadoOrden.ABIERTA_CON_MOTIVO.name,
    EstadoInterrupcion.ABIERTA_OTRO_MOTIVO.name,
)


def _minutos(inicio, fin):
    return func.extract("epoch", fin - inicio) / 60.0


# ---------------------------------------------------------------------------
# Tarjetas superiores
# ---------------------------------------------------------------------------
def resumen(rango, usuario=None) -> dict:
    inicio, fin = rango
    t = cte_tickets(usuario)

    fila = db.session.execute(
        select(
            func.count().filter(t.c.estado != EstadoOrden.CERRADA.name).label("abiertos"),
            func.count()
            .filter(t.c.cerrado_en.is_not(None), t.c.cerrado_en.between(inicio, fin))
            .label("cerrados_periodo"),
            func.count()
            .filter(t.c.creado_en.between(inicio, fin))
            .label("creados_periodo"),
            func.count()
            .filter(t.c.estado == EstadoInterrupcion.DERIVADA_FIBRA.name)
            .label("en_fibra"),
            func.count()
            .filter(
                t.c.estado == EstadoInterrupcion.DERIVADA_FIBRA.name,
                t.c.estado_fibra == EstadoFibra.EN_REVISION.name,
            )
            .label("fibra_sin_respuesta"),
            func.count()
            .filter(t.c.estado.in_(ESTADOS_ABIERTOS_CON_MOTIVO))
            .label("abiertos_con_motivo"),
            func.avg(_minutos(t.c.creado_en, t.c.cerrado_en))
            .filter(t.c.cerrado_en.is_not(None), t.c.cerrado_en.between(inicio, fin))
            .label("prom_resolucion"),
        ).select_from(t)
    ).mappings().one()

    datos = dict(fila)
    datos["prom_resolucion"] = (
        int(datos["prom_resolucion"]) if datos["prom_resolucion"] is not None else None
    )
    return datos


# ---------------------------------------------------------------------------
# Desempeno por operador
# ---------------------------------------------------------------------------
def por_operador(rango, usuario=None) -> list[dict]:
    inicio, fin = rango
    t = cte_tickets(usuario)

    # Corte actual y actividad del periodo, agrupados por el operador asignado.
    agregados = db.session.execute(
        select(
            t.c.asignado_a_id.label("operador_id"),
            func.count()
            .filter(t.c.asignado_en.is_not(None), t.c.asignado_en.between(inicio, fin))
            .label("asignados"),
            func.count().filter(t.c.estado != EstadoOrden.CERRADA.name).label("pendientes"),
            func.count()
            .filter(t.c.estado.in_(ESTADOS_ABIERTOS_CON_MOTIVO))
            .label("abiertos_con_motivo"),
            func.count()
            .filter(t.c.estado == EstadoInterrupcion.DERIVADA_FIBRA.name)
            .label("en_fibra"),
            func.avg(_minutos(t.c.creado_en, t.c.cerrado_en))
            .filter(t.c.cerrado_en.is_not(None), t.c.cerrado_en.between(inicio, fin))
            .label("prom_cierre"),
        )
        .select_from(t)
        .where(t.c.asignado_a_id.is_not(None))
        .group_by(t.c.asignado_a_id)
    ).mappings().all()
    por_id = {f["operador_id"]: dict(f) for f in agregados}

    # "Soluciones": quien ejecuto la transicion a Cerrada dentro del periodo.
    cierres = db.session.execute(
        select(Historial.usuario_id, func.count().label("n"))
        .where(
            Historial.campo == "estado",
            Historial.valor_nuevo == ETIQUETA_CERRADA,
            Historial.creado_en.between(inicio, fin),
        )
        .group_by(Historial.usuario_id)
    ).all()
    soluciones = {uid: n for uid, n in cierres}

    # Derivaciones a fibra hechas por cada operador en el periodo.
    derivaciones = db.session.execute(
        select(Historial.usuario_id, func.count().label("n"))
        .where(
            Historial.campo == "estado",
            Historial.valor_nuevo == ETIQUETA_DERIVADA,
            Historial.creado_en.between(inicio, fin),
        )
        .group_by(Historial.usuario_id)
    ).all()
    derivados = {uid: n for uid, n in derivaciones}

    operadores = (
        db.session.execute(
            select(Usuario)
            .join(UsuarioRol, UsuarioRol.usuario_id == Usuario.id)
            .where(UsuarioRol.rol == RolUsuario.OPERADOR)
            .order_by(Usuario.nombre_completo)
        )
        .scalars()
        .unique()
        .all()
    )

    filas = []
    for op in operadores:
        base = por_id.get(op.id, {})
        asignados = base.get("asignados", 0) or 0
        resueltos = soluciones.get(op.id, 0)
        prom = base.get("prom_cierre")
        filas.append(
            {
                "operador": op,
                "asignados": asignados,
                "soluciones": resueltos,
                "pendientes": base.get("pendientes", 0) or 0,
                "abiertos_con_motivo": base.get("abiertos_con_motivo", 0) or 0,
                "derivados_fibra": derivados.get(op.id, 0),
                "en_fibra": base.get("en_fibra", 0) or 0,
                "prom_cierre": int(prom) if prom is not None else None,
                "porcentaje_cierre": round(resueltos * 100 / asignados) if asignados else None,
                "activo": op.activo,
            }
        )
    filas.sort(key=lambda f: (-f["soluciones"], f["operador"].nombre_completo))
    return filas


# ---------------------------------------------------------------------------
# Desempeno del agente de fibra
# ---------------------------------------------------------------------------
def por_agente_fibra(rango) -> dict:
    inicio, fin = rango

    global_ = db.session.execute(
        select(
            func.count()
            .filter(Interrupcion.derivado_fibra_en.between(inicio, fin))
            .label("recibidas"),
            func.count()
            .filter(
                Interrupcion.respuesta_fibra_en.between(inicio, fin),
                Interrupcion.estado_fibra == EstadoFibra.FIBRA_OK,
            )
            .label("ok"),
            func.count()
            .filter(
                Interrupcion.respuesta_fibra_en.between(inicio, fin),
                Interrupcion.estado_fibra == EstadoFibra.FIBRA_CON_FALLA,
            )
            .label("con_falla"),
            func.count()
            .filter(
                Interrupcion.estado == EstadoInterrupcion.DERIVADA_FIBRA,
                Interrupcion.estado_fibra == EstadoFibra.EN_REVISION,
            )
            .label("en_revision"),
            func.avg(
                _minutos(Interrupcion.derivado_fibra_en, Interrupcion.respuesta_fibra_en)
            )
            .filter(Interrupcion.respuesta_fibra_en.between(inicio, fin))
            .label("prom_respuesta"),
        ).select_from(Interrupcion)
    ).mappings().one()

    detalle = db.session.execute(
        select(
            Usuario.nombre_completo.label("agente"),
            func.count().label("atendidas"),
            func.count()
            .filter(Interrupcion.estado_fibra == EstadoFibra.FIBRA_OK)
            .label("ok"),
            func.count()
            .filter(Interrupcion.estado_fibra == EstadoFibra.FIBRA_CON_FALLA)
            .label("con_falla"),
            func.avg(
                _minutos(Interrupcion.derivado_fibra_en, Interrupcion.respuesta_fibra_en)
            ).label("prom_respuesta"),
        )
        .select_from(Interrupcion)
        .join(Usuario, Usuario.id == Interrupcion.agente_fibra_id)
        .where(Interrupcion.respuesta_fibra_en.between(inicio, fin))
        .group_by(Usuario.nombre_completo)
        .order_by(func.count().desc())
    ).mappings().all()

    datos = dict(global_)
    datos["prom_respuesta"] = (
        int(datos["prom_respuesta"]) if datos["prom_respuesta"] is not None else None
    )
    datos["agentes"] = [
        {**dict(d), "prom_respuesta": int(d["prom_respuesta"]) if d["prom_respuesta"] else None}
        for d in detalle
    ]
    return datos


# ---------------------------------------------------------------------------
# Series para los graficos
# ---------------------------------------------------------------------------
def serie_diaria(rango, usuario=None) -> dict:
    """Creados y cerrados por dia, en la zona horaria de la aplicacion."""
    inicio, fin = rango
    tz = str(zona_app())
    t = cte_tickets(usuario)

    creados = dict(
        db.session.execute(
            select(
                cast(func.timezone(tz, t.c.creado_en), Date).label("dia"),
                func.count().label("n"),
            )
            .select_from(t)
            .where(t.c.creado_en.between(inicio, fin))
            .group_by("dia")
        ).all()
    )
    cerrados = dict(
        db.session.execute(
            select(
                cast(func.timezone(tz, t.c.cerrado_en), Date).label("dia"),
                func.count().label("n"),
            )
            .select_from(t)
            .where(t.c.cerrado_en.is_not(None), t.c.cerrado_en.between(inicio, fin))
            .group_by("dia")
        ).all()
    )

    dia = inicio.astimezone(zona_app()).date()
    ultimo = fin.astimezone(zona_app()).date()
    etiquetas, serie_creados, serie_cerrados = [], [], []
    while dia <= ultimo and len(etiquetas) < 400:
        etiquetas.append(dia.isoformat())
        serie_creados.append(creados.get(dia, 0))
        serie_cerrados.append(cerrados.get(dia, 0))
        dia += timedelta(days=1)

    return {"etiquetas": etiquetas, "creados": serie_creados, "cerrados": serie_cerrados}


def por_dependencia(rango, usuario=None) -> list[dict]:
    inicio, fin = rango
    t = cte_tickets(usuario)
    filas = db.session.execute(
        select(t.c.dependencia, func.count().label("n"))
        .select_from(t)
        .where(t.c.tipo == TipoTicket.INTERRUPCION.name, t.c.creado_en.between(inicio, fin))
        .group_by(t.c.dependencia)
    ).all()

    salida = []
    for nombre, n in filas:
        miembro = Dependencia.desde_nombre(nombre) if nombre else None
        salida.append({"etiqueta": miembro.etiqueta if miembro else "Por diagnosticar", "n": n})
    salida.sort(key=lambda d: -d["n"])
    return salida


def pendientes_por_estado(usuario=None) -> list[dict]:
    """Corte actual de tickets abiertos, agrupados por estado."""
    t = cte_tickets(usuario)
    filas = db.session.execute(
        select(t.c.tipo, t.c.estado, func.count().label("n"))
        .select_from(t)
        .where(t.c.estado != EstadoOrden.CERRADA.name)
        .group_by(t.c.tipo, t.c.estado)
    ).all()

    acumulado: dict[str, int] = {}
    for tipo, estado, n in filas:
        enum_clase = EstadoOrden if tipo == TipoTicket.ORDEN.name else EstadoInterrupcion
        miembro = enum_clase.desde_nombre(estado)
        etiqueta = miembro.etiqueta if miembro else estado
        acumulado[etiqueta] = acumulado.get(etiqueta, 0) + n
    return [{"etiqueta": k, "n": v} for k, v in sorted(acumulado.items(), key=lambda x: -x[1])]


def prioridad_abiertos(usuario=None) -> list[dict]:
    from app.models.enums import Prioridad

    t = cte_tickets(usuario)
    filas = db.session.execute(
        select(t.c.prioridad, func.count().label("n"))
        .select_from(t)
        .where(t.c.estado != EstadoOrden.CERRADA.name)
        .group_by(t.c.prioridad)
    ).all()
    salida = []
    for nombre, n in filas:
        miembro = Prioridad.desde_nombre(nombre)
        salida.append(
            {"etiqueta": miembro.etiqueta if miembro else nombre, "n": n, "nombre": nombre}
        )
    salida.sort(key=lambda d: -(Prioridad.desde_nombre(d["nombre"]).peso if d["nombre"] else 0))
    return salida


def panel_completo(rango, usuario=None) -> dict:
    return {
        "resumen": resumen(rango, usuario),
        "operadores": por_operador(rango, usuario),
        "fibra": por_agente_fibra(rango),
        "serie": serie_diaria(rango, usuario),
        "dependencias": por_dependencia(rango, usuario),
        "pendientes_estado": pendientes_por_estado(usuario),
        "prioridades": prioridad_abiertos(usuario),
    }


__all__ = [
    "ETIQUETA_CERRADA",
    "ETIQUETA_DERIVADA",
    "panel_completo",
    "por_agente_fibra",
    "por_dependencia",
    "por_operador",
    "pendientes_por_estado",
    "prioridad_abiertos",
    "resumen",
    "serie_diaria",
]

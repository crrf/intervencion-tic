"""Consultas que cruzan los dos tipos de ticket.

`orden_trabajo` e `interrupcion` son tablas separadas a proposito, pero la
busqueda, los reportes y las metricas necesitan tratarlas como una sola lista.
Todo eso pasa por `cte_tickets()`, que arma un UNION ALL de las columnas
comunes. Ningun otro modulo debe volver a escribir ese UNION.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import (
    String,
    and_,
    cast,
    exists,
    func,
    literal,
    null,
    or_,
    select,
)
from sqlalchemy.orm import aliased

from app.extensions import db
from app.models.comentario import Comentario
from app.models.enums import (
    Dependencia,
    EstadoFibra,
    EstadoInterrupcion,
    EstadoOrden,
    Prioridad,
    TipoTicket,
)
from app.models.interrupcion import Interrupcion
from app.models.orden import OrdenTrabajo
from app.models.usuario import Usuario
from app.security.decoradores import filtro_interrupciones, filtro_ordenes


# ---------------------------------------------------------------------------
# Rangos de fecha
# ---------------------------------------------------------------------------
PRESETS = {
    "hoy": "Hoy",
    "7d": "Ultimos 7 dias",
    "30d": "Ultimos 30 dias",
    "mes_actual": "Mes actual",
    "mes_anterior": "Mes anterior",
    "90d": "Ultimos 90 dias",
    "personalizado": "Personalizado",
}


def zona_app():
    from app.config import Config

    return Config.zona_horaria()


def resolver_rango(
    preset: str | None, desde: str | date | None = None, hasta: str | date | None = None
) -> tuple[datetime, datetime, str]:
    """Devuelve (inicio_utc, fin_utc, preset_efectivo).

    Las fechas se interpretan en la zona horaria de la aplicacion y se
    convierten a UTC, que es como se almacena todo.
    """
    tz = zona_app()
    hoy = datetime.now(tz).date()
    preset = preset or "30d"

    def _fecha(valor, defecto):
        if isinstance(valor, date):
            return valor
        if isinstance(valor, str) and valor.strip():
            try:
                return date.fromisoformat(valor.strip())
            except ValueError:
                return defecto
        return defecto

    if preset == "hoy":
        ini, fin = hoy, hoy
    elif preset == "7d":
        ini, fin = hoy - timedelta(days=6), hoy
    elif preset == "90d":
        ini, fin = hoy - timedelta(days=89), hoy
    elif preset == "mes_actual":
        ini, fin = hoy.replace(day=1), hoy
    elif preset == "mes_anterior":
        primero_actual = hoy.replace(day=1)
        fin = primero_actual - timedelta(days=1)
        ini = fin.replace(day=1)
    elif preset == "personalizado":
        ini = _fecha(desde, hoy - timedelta(days=29))
        fin = _fecha(hasta, hoy)
        if ini > fin:
            ini, fin = fin, ini
    else:
        preset = "30d"
        ini, fin = hoy - timedelta(days=29), hoy

    inicio_utc = datetime.combine(ini, time.min, tzinfo=tz).astimezone(timezone.utc)
    fin_utc = datetime.combine(fin, time.max, tzinfo=tz).astimezone(timezone.utc)
    return inicio_utc, fin_utc, preset


# ---------------------------------------------------------------------------
# CTE unificada
# ---------------------------------------------------------------------------
def cte_tickets(usuario=None, aplicar_visibilidad: bool = True):
    """UNION ALL de las columnas comunes a los dos tipos de ticket.

    El filtro de visibilidad se aplica a cada rama ANTES de unir, para que
    PostgreSQL pueda usar los indices de cada tabla.
    """
    txt = lambda col: cast(col, String)  # noqa: E731

    q_ordenes = select(
        literal(TipoTicket.ORDEN.name).label("tipo"),
        OrdenTrabajo.id.label("id"),
        OrdenTrabajo.folio.label("folio"),
        OrdenTrabajo.identificador_externo.label("identificador_externo"),
        OrdenTrabajo.nombre_cliente.label("nombre_cliente"),
        OrdenTrabajo.telefono_contacto.label("telefono_contacto"),
        OrdenTrabajo.titulo.label("titulo"),
        OrdenTrabajo.descripcion.label("descripcion"),
        txt(OrdenTrabajo.prioridad).label("prioridad"),
        txt(OrdenTrabajo.estado).label("estado"),
        cast(null(), String).label("dependencia"),
        cast(null(), String).label("estado_fibra"),
        OrdenTrabajo.asignado_a_id.label("asignado_a_id"),
        OrdenTrabajo.creado_por_id.label("creado_por_id"),
        cast(null(), db.Integer).label("agente_fibra_id"),
        OrdenTrabajo.creado_en.label("creado_en"),
        OrdenTrabajo.asignado_en.label("asignado_en"),
        OrdenTrabajo.cerrado_en.label("cerrado_en"),
        OrdenTrabajo.motivo_apertura.label("motivo_apertura"),
    )
    q_inter = select(
        literal(TipoTicket.INTERRUPCION.name),
        Interrupcion.id,
        Interrupcion.folio,
        Interrupcion.identificador_externo,
        Interrupcion.nombre_cliente,
        Interrupcion.telefono_contacto,
        Interrupcion.titulo,
        Interrupcion.descripcion,
        txt(Interrupcion.prioridad),
        txt(Interrupcion.estado),
        txt(Interrupcion.dependencia),
        txt(Interrupcion.estado_fibra),
        Interrupcion.asignado_a_id,
        Interrupcion.creado_por_id,
        Interrupcion.agente_fibra_id,
        Interrupcion.creado_en,
        Interrupcion.asignado_en,
        Interrupcion.cerrado_en,
        Interrupcion.motivo_apertura,
    )

    if aplicar_visibilidad:
        cond_o = filtro_ordenes(usuario)
        cond_i = filtro_interrupciones(usuario)
        if cond_o is not None:
            q_ordenes = q_ordenes.where(cond_o)
        if cond_i is not None:
            q_inter = q_inter.where(cond_i)

    return q_ordenes.union_all(q_inter).cte("tickets")


# ---------------------------------------------------------------------------
# Filtros de busqueda
# ---------------------------------------------------------------------------
ORDENABLES = {
    "creado_en": "Creado",
    "cerrado_en": "Cerrado",
    "folio": "Folio",
    "identificador_externo": "Identificador",
    "nombre_cliente": "Cliente",
    "prioridad": "Prioridad",
    "estado": "Estado",
}


@dataclass
class Filtros:
    texto: str = ""
    tipo: str = ""
    estado: str = ""
    estado_fibra: str = ""
    dependencia: str = ""
    prioridad: str = ""
    asignado_a_id: int | None = None
    creado_por_id: int | None = None
    agente_fibra_id: int | None = None
    campo_fecha: str = "creado_en"
    preset: str = ""
    desde: str = ""
    hasta: str = ""
    ordenar_por: str = "creado_en"
    direccion: str = "desc"
    rango: tuple[datetime, datetime] | None = field(default=None, repr=False)

    @classmethod
    def desde_request(cls, args) -> "Filtros":
        def _int(nombre):
            valor = (args.get(nombre) or "").strip()
            return int(valor) if valor.isdigit() else None

        f = cls(
            texto=(args.get("texto") or "").strip(),
            tipo=(args.get("tipo") or "").strip().upper(),
            estado=(args.get("estado") or "").strip().upper(),
            estado_fibra=(args.get("estado_fibra") or "").strip().upper(),
            dependencia=(args.get("dependencia") or "").strip().upper(),
            prioridad=(args.get("prioridad") or "").strip().upper(),
            asignado_a_id=_int("asignado_a_id"),
            creado_por_id=_int("creado_por_id"),
            agente_fibra_id=_int("agente_fibra_id"),
            campo_fecha=(args.get("campo_fecha") or "creado_en").strip(),
            preset=(args.get("preset") or "").strip(),
            desde=(args.get("desde") or "").strip(),
            hasta=(args.get("hasta") or "").strip(),
            ordenar_por=(args.get("ordenar_por") or "creado_en").strip(),
            direccion=(args.get("direccion") or "desc").strip().lower(),
        )
        if f.campo_fecha not in {"creado_en", "cerrado_en"}:
            f.campo_fecha = "creado_en"
        if f.ordenar_por not in ORDENABLES:
            f.ordenar_por = "creado_en"
        if f.direccion not in {"asc", "desc"}:
            f.direccion = "desc"
        if f.preset:
            f.rango = resolver_rango(f.preset, f.desde, f.hasta)[:2]
        return f

    @property
    def hay_filtros(self) -> bool:
        return any(
            [
                self.texto,
                self.tipo,
                self.estado,
                self.estado_fibra,
                self.dependencia,
                self.prioridad,
                self.asignado_a_id,
                self.creado_por_id,
                self.agente_fibra_id,
                self.preset,
            ]
        )

    def como_dict(self) -> dict:
        return {
            k: v
            for k, v in {
                "texto": self.texto,
                "tipo": self.tipo,
                "estado": self.estado,
                "estado_fibra": self.estado_fibra,
                "dependencia": self.dependencia,
                "prioridad": self.prioridad,
                "asignado_a_id": self.asignado_a_id,
                "creado_por_id": self.creado_por_id,
                "agente_fibra_id": self.agente_fibra_id,
                "campo_fecha": self.campo_fecha,
                "preset": self.preset,
                "desde": self.desde,
                "hasta": self.hasta,
                "ordenar_por": self.ordenar_por,
                "direccion": self.direccion,
            }.items()
            if v not in (None, "")
        }


def _condiciones(t, f: Filtros) -> list:
    cond = []
    if f.texto:
        patron = f"%{f.texto.strip()}%"
        cond.append(
            or_(
                t.c.identificador_externo.ilike(patron),
                t.c.folio.ilike(patron),
                t.c.nombre_cliente.ilike(patron),
                t.c.telefono_contacto.ilike(patron),
                t.c.titulo.ilike(patron),
                t.c.descripcion.ilike(patron),
                exists(
                    select(literal(1))
                    .select_from(Comentario)
                    .where(
                        or_(
                            and_(
                                t.c.tipo == TipoTicket.ORDEN.name,
                                Comentario.orden_id == t.c.id,
                            ),
                            and_(
                                t.c.tipo == TipoTicket.INTERRUPCION.name,
                                Comentario.interrupcion_id == t.c.id,
                            ),
                        ),
                        Comentario.texto.ilike(patron),
                    )
                ),
            )
        )
    if f.tipo in {TipoTicket.ORDEN.name, TipoTicket.INTERRUPCION.name}:
        cond.append(t.c.tipo == f.tipo)
    if f.estado:
        cond.append(t.c.estado == f.estado)
    if f.estado_fibra:
        cond.append(t.c.estado_fibra == f.estado_fibra)
    if f.dependencia:
        cond.append(t.c.dependencia == f.dependencia)
    if f.prioridad:
        cond.append(t.c.prioridad == f.prioridad)
    if f.asignado_a_id:
        cond.append(t.c.asignado_a_id == f.asignado_a_id)
    if f.creado_por_id:
        cond.append(t.c.creado_por_id == f.creado_por_id)
    if f.agente_fibra_id:
        cond.append(t.c.agente_fibra_id == f.agente_fibra_id)
    if f.rango:
        columna = t.c.cerrado_en if f.campo_fecha == "cerrado_en" else t.c.creado_en
        cond.append(columna.is_not(None))
        cond.append(columna >= f.rango[0])
        cond.append(columna <= f.rango[1])
    return cond


def buscar(f: Filtros, usuario=None, pagina: int = 1, por_pagina: int = 25) -> dict:
    """Ejecuta la busqueda paginada. Devuelve filas ya enriquecidas."""
    t = cte_tickets(usuario)
    asignado = aliased(Usuario)
    creador = aliased(Usuario)
    agente = aliased(Usuario)

    base = (
        select(
            t,
            asignado.nombre_completo.label("asignado_nombre"),
            creador.nombre_completo.label("creador_nombre"),
            agente.nombre_completo.label("agente_nombre"),
        )
        .select_from(t)
        .outerjoin(asignado, asignado.id == t.c.asignado_a_id)
        .outerjoin(creador, creador.id == t.c.creado_por_id)
        .outerjoin(agente, agente.id == t.c.agente_fibra_id)
    )
    cond = _condiciones(t, f)
    if cond:
        base = base.where(*cond)

    total = db.session.execute(
        select(func.count()).select_from(
            select(t.c.id).select_from(t).where(*cond).subquery()
            if cond
            else select(t.c.id).select_from(t).subquery()
        )
    ).scalar_one()

    columna = t.c[f.ordenar_por]
    # NULLS LAST para que los tickets abiertos no encabecen un orden por cierre.
    orden = columna.desc().nullslast() if f.direccion == "desc" else columna.asc().nullslast()
    filas = db.session.execute(
        base.order_by(orden, t.c.creado_en.desc()).limit(por_pagina).offset((pagina - 1) * por_pagina)
    ).mappings().all()

    paginas = max(1, -(-total // por_pagina))
    return {
        "filas": [enriquecer(fila) for fila in filas],
        "total": total,
        "pagina": min(pagina, paginas),
        "paginas": paginas,
        "por_pagina": por_pagina,
    }


def iterar_todo(f: Filtros, usuario=None, lote: int = 500):
    """Itera el resultado completo sin paginar (para exportar a CSV)."""
    pagina = 1
    while True:
        datos = buscar(f, usuario, pagina=pagina, por_pagina=lote)
        if not datos["filas"]:
            return
        yield from datos["filas"]
        if pagina >= datos["paginas"]:
            return
        pagina += 1


# ---------------------------------------------------------------------------
# Presentacion
# ---------------------------------------------------------------------------
_ESTADOS = {
    TipoTicket.ORDEN.name: EstadoOrden,
    TipoTicket.INTERRUPCION.name: EstadoInterrupcion,
}


def etiqueta_estado(tipo: str, nombre: str | None) -> str:
    if not nombre:
        return "-"
    enum_clase = _ESTADOS.get(tipo)
    miembro = enum_clase.desde_nombre(nombre) if enum_clase else None
    return miembro.etiqueta if miembro else nombre


def _etiqueta(enum_clase, nombre):
    miembro = enum_clase.desde_nombre(nombre) if nombre else None
    return miembro.etiqueta if miembro else None


def enriquecer(fila) -> dict:
    d = dict(fila)
    d["tipo_etiqueta"] = TipoTicket.desde_nombre(d["tipo"]).etiqueta
    d["estado_etiqueta"] = etiqueta_estado(d["tipo"], d["estado"])
    d["prioridad_etiqueta"] = _etiqueta(Prioridad, d["prioridad"]) or "-"
    d["dependencia_etiqueta"] = _etiqueta(Dependencia, d["dependencia"]) or "Por diagnosticar"
    d["estado_fibra_etiqueta"] = _etiqueta(EstadoFibra, d["estado_fibra"])
    d["url"] = (
        f"/ordenes/{d['id']}"
        if d["tipo"] == TipoTicket.ORDEN.name
        else f"/interrupciones/{d['id']}"
    )
    if d["cerrado_en"]:
        d["minutos_resolucion"] = int(
            (d["cerrado_en"] - d["creado_en"]).total_seconds() // 60
        )
    else:
        d["minutos_resolucion"] = None
    return d


def formatear_duracion(minutos: int | None) -> str:
    if minutos is None:
        return "-"
    if minutos < 60:
        return f"{minutos} min"
    horas, resto = divmod(minutos, 60)
    if horas < 24:
        return f"{horas} h {resto:02d} min"
    dias, horas = divmod(horas, 24)
    return f"{dias} d {horas} h"

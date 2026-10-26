"""Bitacora de auditoria: historial y comentarios de los dos tipos de ticket,
mezclados en un solo feed cronologico.
"""
from __future__ import annotations

from sqlalchemy import String, and_, cast, func, literal, or_, select

from app.extensions import db
from app.models.comentario import Comentario
from app.models.enums import TipoTicket
from app.models.historial import Historial
from app.models.usuario import Usuario
from app.services.consultas import cte_tickets

#: Nombre legible de cada campo auditado.
NOMBRES_EVENTO = {
    "estado": "Cambio de estado",
    "estado_fibra": "Revision de fibra",
    "asignado_a": "Asignacion",
    "dependencia": "Clasificacion de dependencia",
    "foto_anverso": "Cambio de foto (anverso)",
    "foto_reverso": "Cambio de foto (reverso)",
    "foto": "Cambio de foto",
    "telefono_contacto": "Telefono de contacto",
    "direccion": "Direccion",
    "categoria": "Categoria",
}

CLASES = {"cambio": "Cambio", "comentario": "Comentario"}


def _consulta(rango, usuario=None, usuario_id=None, folio=None, clase=None):
    inicio, fin = rango
    t = cte_tickets(usuario)

    def _union_ticket(columna_orden, columna_inter):
        return or_(
            and_(t.c.tipo == TipoTicket.ORDEN.name, t.c.id == columna_orden),
            and_(t.c.tipo == TipoTicket.INTERRUPCION.name, t.c.id == columna_inter),
        )

    cambios = (
        select(
            Historial.creado_en.label("cuando"),
            Historial.id.label("evento_id"),
            literal("cambio").label("clase"),
            t.c.folio.label("folio"),
            t.c.tipo.label("tipo"),
            t.c.nombre_cliente.label("nombre_cliente"),
            t.c.id.label("ticket_id"),
            Usuario.nombre_completo.label("usuario"),
            Historial.campo.label("campo"),
            Historial.valor_anterior.label("anterior"),
            Historial.valor_nuevo.label("nuevo"),
            cast(literal(None), String).label("texto"),
        )
        .select_from(Historial)
        .join(t, _union_ticket(Historial.orden_id, Historial.interrupcion_id))
        .join(Usuario, Usuario.id == Historial.usuario_id)
        .where(Historial.creado_en.between(inicio, fin))
    )

    # Las etiquetas van tambien en esta rama, no solo en la primera: cuando se
    # filtra por clase se devuelve una sola de las dos, sin pasar por el UNION
    # (que es el que normalmente impone los nombres de la primera).
    comentarios = (
        select(
            Comentario.creado_en.label("cuando"),
            Comentario.id.label("evento_id"),
            literal("comentario").label("clase"),
            t.c.folio.label("folio"),
            t.c.tipo.label("tipo"),
            t.c.nombre_cliente.label("nombre_cliente"),
            t.c.id.label("ticket_id"),
            Usuario.nombre_completo.label("usuario"),
            cast(literal(None), String).label("campo"),
            cast(literal(None), String).label("anterior"),
            cast(literal(None), String).label("nuevo"),
            Comentario.texto.label("texto"),
        )
        .select_from(Comentario)
        .join(t, _union_ticket(Comentario.orden_id, Comentario.interrupcion_id))
        .join(Usuario, Usuario.id == Comentario.autor_id)
        .where(Comentario.creado_en.between(inicio, fin))
    )

    if usuario_id:
        cambios = cambios.where(Historial.usuario_id == usuario_id)
        comentarios = comentarios.where(Comentario.autor_id == usuario_id)
    if folio:
        patron = f"%{folio.strip()}%"
        cambios = cambios.where(t.c.folio.ilike(patron))
        comentarios = comentarios.where(t.c.folio.ilike(patron))

    if clase == "cambio":
        return cambios.subquery()
    if clase == "comentario":
        return comentarios.subquery()
    return cambios.union_all(comentarios).subquery()


def _presentar(fila) -> dict:
    d = dict(fila)
    tipo = TipoTicket.desde_nombre(d["tipo"])
    d["tipo_etiqueta"] = tipo.etiqueta if tipo else d["tipo"]
    d["evento"] = (
        NOMBRES_EVENTO.get(d["campo"], d["campo"])
        if d["clase"] == "cambio"
        else "Comentario"
    )
    d["url"] = (
        f"/ordenes/{d['ticket_id']}"
        if d["tipo"] == TipoTicket.ORDEN.name
        else f"/interrupciones/{d['ticket_id']}"
    )
    return d


def listar(
    rango, usuario=None, *, usuario_id=None, folio=None, clase=None, pagina=1, por_pagina=60
) -> dict:
    sub = _consulta(rango, usuario, usuario_id, folio, clase)
    total = db.session.execute(select(func.count()).select_from(sub)).scalar_one()
    filas = (
        db.session.execute(
            select(sub)
            .order_by(sub.c.cuando.desc(), sub.c.evento_id.desc())
            .limit(por_pagina)
            .offset((pagina - 1) * por_pagina)
        )
        .mappings()
        .all()
    )
    paginas = max(1, -(-total // por_pagina))
    return {
        "eventos": [_presentar(f) for f in filas],
        "total": total,
        "pagina": min(pagina, paginas),
        "paginas": paginas,
    }


def iterar_todo(rango, usuario=None, *, usuario_id=None, folio=None, clase=None, lote=500):
    pagina = 1
    while True:
        datos = listar(
            rango,
            usuario,
            usuario_id=usuario_id,
            folio=folio,
            clase=clase,
            pagina=pagina,
            por_pagina=lote,
        )
        if not datos["eventos"]:
            return
        yield from datos["eventos"]
        if pagina >= datos["paginas"]:
            return
        pagina += 1

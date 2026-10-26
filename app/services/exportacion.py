"""Exportacion a CSV en streaming.

Se genera fila por fila para que un reporte de miles de tickets no tenga que
materializarse entero en memoria antes de empezar a descargarse.
"""
from __future__ import annotations

import csv
from datetime import datetime

from flask import Response, stream_with_context

from app.services.consultas import formatear_duracion, iterar_todo

#: BOM para que Excel en Windows reconozca el UTF-8 sin ayuda.
BOM = "﻿"


class _Buffer:
    """Objeto tipo fichero que devuelve lo escrito, para csv.writer."""

    def __init__(self) -> None:
        self._valor = ""

    def write(self, texto: str) -> None:
        self._valor += texto

    def extraer(self) -> str:
        valor, self._valor = self._valor, ""
        return valor


def _escritor():
    buffer = _Buffer()
    return buffer, csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")


def _fecha(valor, tz) -> str:
    if not valor:
        return ""
    return valor.astimezone(tz).strftime("%Y-%m-%d %H:%M")


CABECERA_TICKETS = [
    "Folio",
    "Identificador",
    "Tipo",
    "Cliente",
    "Telefono de contacto",
    "Direccion",
    "Titulo",
    "Prioridad",
    "Categoria",
    "Dependencia",
    "Estado",
    "Estado fibra",
    "Creado por",
    "Asignado a",
    "Agente de fibra",
    "Creado",
    "Asignado",
    "Cerrado",
    "Tiempo de resolucion",
    "Motivo de apertura",
]


def filas_tickets(filtros, usuario, tz):
    buffer, escritor = _escritor()
    escritor.writerow(CABECERA_TICKETS)
    yield BOM + buffer.extraer()

    for t in iterar_todo(filtros, usuario):
        escritor.writerow(
            [
                t["folio"],
                t["identificador_externo"] or "",
                t["tipo_etiqueta"],
                t["nombre_cliente"],
                t["telefono_contacto"] or "",
                t["direccion"] or "",
                t["titulo"],
                t["prioridad_etiqueta"],
                t["categoria_etiqueta"] or "",
                t["dependencia_etiqueta"] if t["tipo"] == "INTERRUPCION" else "",
                t["estado_etiqueta"],
                t["estado_fibra_etiqueta"] or "",
                t["creador_nombre"] or "",
                t["asignado_nombre"] or "Sin asignar",
                t["agente_nombre"] or "",
                _fecha(t["creado_en"], tz),
                _fecha(t["asignado_en"], tz),
                _fecha(t["cerrado_en"], tz),
                formatear_duracion(t["minutos_resolucion"]),
                (t["motivo_apertura"] or "").replace("\n", " "),
            ]
        )
        yield buffer.extraer()


CABECERA_AUDITORIA = [
    "Fecha",
    "Ticket",
    "Tipo",
    "Cliente",
    "Usuario",
    "Evento",
    "Valor anterior",
    "Valor nuevo",
    "Texto",
]


def filas_auditoria(eventos, tz):
    buffer, escritor = _escritor()
    escritor.writerow(CABECERA_AUDITORIA)
    yield BOM + buffer.extraer()

    for e in eventos:
        escritor.writerow(
            [
                _fecha(e["cuando"], tz),
                e["folio"],
                e["tipo_etiqueta"],
                e["nombre_cliente"],
                e["usuario"],
                e["evento"],
                e.get("anterior") or "",
                e.get("nuevo") or "",
                (e.get("texto") or "").replace("\n", " "),
            ]
        )
        yield buffer.extraer()


def respuesta_csv(generador, prefijo: str) -> Response:
    """Envuelve el generador en el contexto de la peticion.

    Sin `stream_with_context`, el generador seguiria produciendo filas despues
    de que Flask desmonta el contexto: la sesion de SQLAlchemy ya no estaria
    disponible y la descarga se cortaria a mitad.
    """
    sello = datetime.now().strftime("%Y%m%d-%H%M")
    nombre = f"{prefijo}-{sello}.csv"
    return Response(
        stream_with_context(generador),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )



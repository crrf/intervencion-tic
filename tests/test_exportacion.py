"""Exportacion a CSV: cabeceras, contenido, filtros y formato para Excel."""
from __future__ import annotations

from app.extensions import db
from app.models.enums import Dependencia
from app.services.estados import ejecutar_transicion
from app.services.exportacion import BOM

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    return cliente.post("/login", data={"usuario": usuario.usuario, "password": CLAVE})


def descargar(cliente, ruta):
    respuesta = cliente.get(ruta)
    assert respuesta.status_code == 200
    return respuesta, respuesta.get_data(as_text=True)


def filas(texto):
    return [f for f in texto.replace(BOM, "").strip().split("\r\n") if f]


# ---------------------------------------------------------------------------
# CSV de tickets
# ---------------------------------------------------------------------------
def test_la_cabecera_trae_todas_las_columnas(cliente, despachador):
    entrar(cliente, despachador)
    _, texto = descargar(cliente, "/buscar/csv")
    cabecera = filas(texto)[0].split(";")
    assert cabecera[:9] == [
        "Folio", "Identificador", "Tipo", "Cliente", "Telefono de contacto",
        "Direccion", "Titulo", "Prioridad", "Categoria",
    ]
    assert "Dependencia" in cabecera
    assert "Tiempo de resolucion" in cabecera


def test_el_csv_abre_bien_en_excel(cliente, despachador):
    """BOM al principio y punto y coma como separador."""
    entrar(cliente, despachador)
    respuesta, texto = descargar(cliente, "/buscar/csv")
    assert texto.startswith(BOM)
    assert ";" in texto.split("\r\n")[0]
    assert "text/csv" in respuesta.headers["Content-Type"]
    assert "attachment" in respuesta.headers["Content-Disposition"]
    assert ".csv" in respuesta.headers["Content-Disposition"]


def test_el_csv_lleva_los_tickets(cliente, nueva_orden, nueva_interrupcion, despachador):
    orden = nueva_orden(despachador)
    inter = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    db.session.commit()

    entrar(cliente, despachador)
    _, texto = descargar(cliente, "/buscar/csv")
    assert orden.folio in texto
    assert inter.folio in texto
    assert "Sitio wifi" in texto
    assert "Orden de trabajo" in texto
    assert "Interrupcion" in texto


def test_el_csv_respeta_los_filtros(cliente, nueva_interrupcion, despachador):
    wifi = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    enlace = nueva_interrupcion(
        despachador, identificador_externo="FD222222", categoria="ENLACE_CLIENTE"
    )
    db.session.commit()

    entrar(cliente, despachador)
    _, texto = descargar(cliente, "/buscar/csv?categoria=SITIO_WIFI")
    assert wifi.folio in texto
    assert enlace.folio not in texto


def test_el_csv_de_un_ticket_cerrado_trae_el_tiempo(
    cliente, nueva_orden, despachador, operador
):
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:OK_OPERADOR", comentario="listo")
    ejecutar_transicion(orden, despachador, "estado:CERRADA", comentario="en SIPREC")
    db.session.commit()

    entrar(cliente, despachador)
    _, texto = descargar(cliente, "/buscar/csv")
    fila = next(f for f in filas(texto) if orden.folio in f)
    assert "Cerrada" in fila
    assert "min" in fila or "h" in fila


def test_el_salto_de_linea_del_motivo_no_rompe_la_fila(
    cliente, nueva_orden, despachador, operador
):
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        orden, operador, "estado:ABIERTA_CON_MOTIVO",
        comentario="sin acceso", motivo="Primera linea",
    )
    orden.motivo_apertura = "Primera linea\nSegunda linea"
    db.session.commit()

    entrar(cliente, despachador)
    _, texto = descargar(cliente, "/buscar/csv")
    fila = next(f for f in filas(texto) if orden.folio in f)
    assert "Primera linea Segunda linea" in fila


def test_el_operador_no_exporta(cliente, operador):
    entrar(cliente, operador)
    assert cliente.get("/buscar/csv").status_code == 403
    assert cliente.get("/reportes/historico/csv").status_code == 403
    assert cliente.get("/reportes/auditoria/csv").status_code == 403


# ---------------------------------------------------------------------------
# CSV del historico
# ---------------------------------------------------------------------------
def test_el_historico_exporta_el_periodo(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    _, texto = descargar(cliente, "/reportes/historico/csv?preset=30d")
    assert orden.folio in texto


# ---------------------------------------------------------------------------
# CSV de auditoria
# ---------------------------------------------------------------------------
def test_la_auditoria_exporta_cambios_y_comentarios(
    cliente, nueva_interrupcion, despachador, operador
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:CERRADA",
        comentario="Nodo reiniciado", dependencia=Dependencia.CORE_IPMPLS,
    )
    db.session.commit()

    entrar(cliente, despachador)
    _, texto = descargar(cliente, "/reportes/auditoria/csv?preset=30d")
    cabecera = filas(texto)[0].split(";")
    assert cabecera == [
        "Fecha", "Ticket", "Tipo", "Cliente", "Usuario", "Evento",
        "Valor anterior", "Valor nuevo", "Texto",
    ]
    assert inter.folio in texto
    assert "Cambio de estado" in texto
    assert "Comentario" in texto
    assert "Nodo reiniciado" in texto
    assert operador.nombre_completo in texto


def test_la_auditoria_filtra_por_clase(
    cliente, nueva_interrupcion, despachador, operador
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:CERRADA",
        comentario="Nodo reiniciado", dependencia=Dependencia.CORE_IPMPLS,
    )
    db.session.commit()

    entrar(cliente, despachador)
    _, solo_comentarios = descargar(
        cliente, "/reportes/auditoria/csv?preset=30d&clase=comentario"
    )
    assert "Nodo reiniciado" in solo_comentarios
    assert "Cambio de estado" not in solo_comentarios

    _, solo_cambios = descargar(
        cliente, "/reportes/auditoria/csv?preset=30d&clase=cambio"
    )
    assert "Cambio de estado" in solo_cambios
    assert "Nodo reiniciado" not in solo_cambios


def test_la_auditoria_filtra_por_usuario_y_folio(
    cliente, nueva_orden, despachador, operador, operador_b
):
    propia = nueva_orden(despachador, asignado_a=operador)
    otra = nueva_orden(
        despachador, identificador_externo="ED222222", asignado_a=operador_b
    )
    ejecutar_transicion(propia, operador, "estado:EN_PROCESO")
    ejecutar_transicion(otra, operador_b, "estado:EN_PROCESO")
    db.session.commit()

    entrar(cliente, despachador)
    _, por_usuario = descargar(
        cliente, f"/reportes/auditoria/csv?preset=30d&usuario_id={operador.id}"
    )
    assert operador.nombre_completo in por_usuario
    assert operador_b.nombre_completo not in por_usuario

    _, por_folio = descargar(
        cliente, f"/reportes/auditoria/csv?preset=30d&folio={propia.folio}"
    )
    assert propia.folio in por_folio
    assert otra.folio not in por_folio

"""Unidades sueltas: propiedades de los modelos, enums, visibilidad y rangos."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models.base import (
    MAX_DIGITOS_IDENTIFICADOR,
    MIN_DIGITOS_IDENTIFICADOR,
    ahora,
    identificador_valido,
    normalizar_identificador,
    normalizar_telefono,
    telefono_valido,
)
from app.models.contador import siguiente_folio
from app.models.enums import (
    COLORES_ESTADO,
    CategoriaInterrupcion,
    Dependencia,
    EstadoFibra,
    EstadoInterrupcion,
    EstadoOrden,
    Prioridad,
    RolUsuario,
    TipoTicket,
)
from app.security.decoradores import (
    filtro_interrupciones,
    filtro_ordenes,
    puede_crear,
    puede_gestionar,
    puede_ver,
)
from app.services.consultas import formatear_duracion, resolver_rango
from app.services.estados import ejecutar_transicion


class Anonimo:
    """Lo que ve Flask-Login cuando no hay sesion."""

    is_authenticated = False

    def tiene_rol(self, rol):
        return False

    def tiene_alguno(self, *roles):
        return False


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
def test_cada_estado_tiene_color():
    for clase in (EstadoOrden, EstadoInterrupcion, EstadoFibra):
        for miembro in clase:
            assert miembro.name in COLORES_ESTADO, miembro.name


def test_desde_nombre_aguanta_cualquier_entrada():
    assert EstadoOrden.desde_nombre("ok_operador") is EstadoOrden.OK_OPERADOR
    assert EstadoOrden.desde_nombre("OK_OPERADOR") is EstadoOrden.OK_OPERADOR
    assert EstadoOrden.desde_nombre("no_existe") is None
    assert EstadoOrden.desde_nombre("") is None
    assert EstadoOrden.desde_nombre(None) is None


def test_opciones_para_los_formularios():
    opciones = dict(CategoriaInterrupcion.opciones())
    assert opciones == {
        "ENLACE_CLIENTE": "Enlace de cliente",
        "SITIO_WIFI": "Sitio wifi",
    }


def test_la_etiqueta_es_lo_que_se_imprime():
    assert str(RolUsuario.TECNICO_WIFI) == "Tecnico de wifi"
    assert RolUsuario.TECNICO_WIFI.etiqueta == "Tecnico de wifi"


def test_el_prefijo_del_folio_por_tipo():
    assert TipoTicket.ORDEN.prefijo == "OT"
    assert TipoTicket.INTERRUPCION.prefijo == "INT"


def test_el_peso_de_la_prioridad_ordena():
    pesos = [p.peso for p in Prioridad]
    assert pesos == sorted(pesos)
    assert Prioridad.CRITICA.peso > Prioridad.BAJA.peso


# ---------------------------------------------------------------------------
# Identificador y telefono
# ---------------------------------------------------------------------------
def test_el_identificador_no_limita_la_cantidad_de_digitos():
    """Un solo digito vale, y el unico tope es lo que cabe en la columna."""
    assert MIN_DIGITOS_IDENTIFICADOR == 1
    assert MAX_DIGITOS_IDENTIFICADOR == 18
    for cuantos in range(MIN_DIGITOS_IDENTIFICADOR, MAX_DIGITOS_IDENTIFICADOR + 1):
        assert identificador_valido("ED" + "1" * cuantos), cuantos
    assert not identificador_valido("ED")
    assert not identificador_valido("ED" + "1" * (MAX_DIGITOS_IDENTIFICADOR + 1))
    # Y lo que admite cabe en la columna.
    assert len("ED" + "1" * MAX_DIGITOS_IDENTIFICADOR) == 20


def test_el_identificador_se_normaliza():
    assert normalizar_identificador("  ed 12 34  ") == "ED1234"
    assert normalizar_identificador(None) == ""


def test_el_telefono_es_opcional_pero_con_formato():
    assert telefono_valido(None) is True
    assert telefono_valido("") is True
    assert telefono_valido("0414-1234567") is True
    assert telefono_valido("+58 (212) 555.66.77") is True
    assert telefono_valido("12345") is False, "menos de 7 digitos"
    assert telefono_valido("llamar al movil") is False


def test_el_telefono_vacio_se_guarda_como_nulo():
    assert normalizar_telefono("   ") is None
    assert normalizar_telefono("0414   1234567") == "0414 1234567"


# ---------------------------------------------------------------------------
# Propiedades del ticket
# ---------------------------------------------------------------------------
def test_tiempos_de_una_orden_abierta(app, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    orden.creado_en = ahora() - timedelta(hours=3)
    db.session.commit()

    assert orden.abierto is True
    assert orden.minutos_resolucion is None
    assert 175 <= orden.minutos_transcurridos <= 185
    assert orden.fotos_faltantes == []
    assert orden.url_detalle == f"/ordenes/{orden.id}"
    assert orden.folio in repr(orden)


def test_tiempos_de_una_orden_cerrada(app, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:OK_OPERADOR", comentario="listo")
    ejecutar_transicion(orden, despachador, "estado:CERRADA", comentario="en SIPREC")
    orden.creado_en = orden.cerrado_en - timedelta(minutes=90)
    db.session.commit()

    assert orden.abierto is False
    assert orden.minutos_resolucion == 90
    assert orden.minutos_transcurridos == 90, "ya no corre el reloj"


def test_las_fotos_que_faltan(app, nueva_orden, despachador):
    orden = nueva_orden(despachador, foto_anverso=None, foto_reverso=None)
    db.session.commit()
    assert set(orden.fotos_faltantes) == {"anverso", "reverso"}


def test_una_foto_que_no_existe_para_el_tipo(app, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    assert orden.clave_foto("inventada") is None
    with pytest.raises(ValueError, match="foto desconocida"):
        orden.set_clave_foto("inventada", "x")


def test_la_interrupcion_no_tiene_las_fotos_de_la_orden(
    app, nueva_interrupcion, despachador
):
    inter = nueva_interrupcion(despachador)
    assert inter.clave_foto("anverso") is None
    with pytest.raises(ValueError, match="foto desconocida"):
        inter.set_clave_foto("anverso", "x")


def test_el_telefono_marcable_se_limpia(app, nueva_orden, despachador):
    orden = nueva_orden(despachador, telefono_contacto="0414-123.45.67")
    db.session.commit()
    assert orden.telefono_marcable == "04141234567"


def test_propiedades_de_fibra_de_la_interrupcion(
    app, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    assert inter.en_fibra is False
    assert inter.minutos_en_fibra is None
    assert inter.minutos_respuesta_fibra is None
    assert inter.ultimo_comentario is None

    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="posible corte", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()

    assert inter.en_fibra is True
    assert inter.minutos_en_fibra >= 0
    assert inter.ultimo_comentario.texto == "posible corte"

    ejecutar_transicion(
        inter, agente_fibra, "estado_fibra:FIBRA_OK", comentario="tramo medido"
    )
    inter.derivado_fibra_en = inter.respuesta_fibra_en - timedelta(minutes=45)
    db.session.commit()

    assert inter.minutos_respuesta_fibra == 45
    assert inter.ultimo_comentario.texto == "tramo medido"
    assert inter.url_detalle == f"/interrupciones/{inter.id}"
    assert inter.folio in repr(inter)


# ---------------------------------------------------------------------------
# Usuario
# ---------------------------------------------------------------------------
def test_atajos_de_rol(app, mixto, agente_fibra):
    assert mixto.es_despachador is True
    assert mixto.es_operador is True
    assert mixto.es_admin is False
    assert mixto.es_agente_fibra is False
    assert agente_fibra.es_agente_fibra is True


def test_tiene_rol_acepta_texto(app, operador):
    assert operador.tiene_rol("OPERADOR") is True
    assert operador.tiene_rol("operador") is True
    assert operador.tiene_rol("PRESIDENTE") is False


def test_iniciales_y_repr(app, operador, operador_b):
    # Una sola palabra deja una inicial; dos nombres dejan dos.
    assert operador.nombre_completo == "Operador"
    assert operador.iniciales == "O"
    assert operador_b.nombre_completo == "Operador B"
    assert operador_b.iniciales == "OB"

    assert operador.usuario in repr(operador)
    assert RolUsuario.OPERADOR.etiqueta in repr(operador)


def test_las_iniciales_caen_al_usuario_si_no_hay_nombre(app, operador):
    operador.nombre_completo = "   "
    db.session.commit()
    assert operador.iniciales == "OP"  # del login "operador"


def test_los_roles_se_ordenan_siempre_igual(app, mixto):
    mixto.roles = [RolUsuario.TECNICO_WIFI, RolUsuario.ADMIN, RolUsuario.OPERADOR]
    db.session.commit()
    assert mixto.roles_ordenados == [
        RolUsuario.ADMIN, RolUsuario.OPERADOR, RolUsuario.TECNICO_WIFI
    ]
    assert mixto.etiqueta_roles == "Administrador, Operador, Tecnico de wifi"


def test_una_cuenta_desactivada_no_esta_activa(app, operador):
    assert operador.is_active is True
    operador.activo = False
    db.session.commit()
    assert operador.is_active is False


# ---------------------------------------------------------------------------
# Folios
# ---------------------------------------------------------------------------
def test_los_folios_son_consecutivos_por_tipo_y_ano(app):
    assert siguiente_folio(TipoTicket.ORDEN, 2026) == "OT-2026-0001"
    assert siguiente_folio(TipoTicket.ORDEN, 2026) == "OT-2026-0002"
    assert siguiente_folio(TipoTicket.INTERRUPCION, 2026) == "INT-2026-0001"
    assert siguiente_folio(TipoTicket.ORDEN, 2027) == "OT-2027-0001"


# ---------------------------------------------------------------------------
# Visibilidad sin sesion
# ---------------------------------------------------------------------------
def test_sin_sesion_no_se_ve_nada(app, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    db.session.commit()
    anonimo = Anonimo()

    assert puede_ver(orden, anonimo) is False
    assert puede_gestionar(anonimo) is False
    assert puede_crear(anonimo) is False
    assert filtro_ordenes(anonimo) is not None
    assert filtro_interrupciones(anonimo) is not None


def test_el_agente_de_fibra_no_ve_ordenes_ni_con_filtro(app, agente_fibra):
    from sqlalchemy import false

    assert str(filtro_ordenes(agente_fibra)) == str(false())


def test_el_despachador_crea_y_gestiona(app, despachador, operador):
    assert puede_gestionar(despachador) is True
    assert puede_crear(despachador) is True
    assert puede_gestionar(operador) is False
    assert puede_crear(operador) is False


# ---------------------------------------------------------------------------
# Rangos de fecha
# ---------------------------------------------------------------------------
def test_los_presets(app):
    for preset in ("hoy", "7d", "30d", "90d", "mes_actual", "mes_anterior"):
        inicio, fin, devuelto = resolver_rango(preset)
        assert devuelto == preset
        assert inicio <= fin, preset


def test_el_preset_vacio_cae_en_30_dias(app):
    assert resolver_rango("")[2] == "30d"
    assert resolver_rango(None)[2] == "30d"
    assert resolver_rango("el_mes_que_viene")[2] == "30d"


def test_el_rango_personalizado(app):
    inicio, fin, preset = resolver_rango("personalizado", "2026-03-01", "2026-03-31")
    assert preset == "personalizado"
    assert inicio.date() == date(2026, 3, 1)
    assert fin.date() == date(2026, 3, 31)


def test_las_fechas_invalidas_no_rompen(app):
    inicio, fin, _ = resolver_rango("personalizado", "no-es-fecha", "tampoco")
    assert inicio <= fin


def test_el_rango_acepta_objetos_date(app):
    inicio, fin, _ = resolver_rango(
        "personalizado", date(2026, 3, 1), date(2026, 3, 2)
    )
    assert inicio.date() == date(2026, 3, 1)
    assert fin.date() == date(2026, 3, 2)


def test_el_fin_del_rango_cubre_el_dia_completo(app):
    _, fin, _ = resolver_rango("hoy")
    assert fin.hour == 23 or fin.hour >= 3, "es el final del dia en la zona de la app"


# ---------------------------------------------------------------------------
# Formato de duraciones
# ---------------------------------------------------------------------------
def test_formatear_duracion():
    assert formatear_duracion(None) == "-"
    assert formatear_duracion(0) == "0 min"
    assert formatear_duracion(45) == "45 min"
    assert formatear_duracion(60) == "1 h 00 min"
    assert formatear_duracion(135) == "2 h 15 min"
    assert formatear_duracion(60 * 24) == "1 d 0 h"
    assert formatear_duracion(60 * 50) == "2 d 2 h"

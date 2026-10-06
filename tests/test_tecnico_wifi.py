"""El tecnico de wifi: solo recibe interrupciones de sitio wifi, y las trabaja
igual que un operador."""
from __future__ import annotations

import pytest

from app.extensions import db
from app.models.enums import (
    CategoriaInterrupcion,
    Dependencia,
    EstadoFibra,
    EstadoInterrupcion,
    RolUsuario,
)
from app.security.decoradores import filtro_interrupciones, filtro_ordenes, puede_ver
from app.services import tickets as servicio
from app.services.estados import (
    TransicionInvalida,
    ejecutar_transicion,
    transiciones_permitidas,
)
from tests.conftest import crear_usuario


def claves(ticket, usuario):
    return {t.clave for t in transiciones_permitidas(ticket, usuario)}


def entrar(cliente, usuario):
    return cliente.post(
        "/login", data={"usuario": usuario.usuario, "password": "Clave.2026"}
    )


@pytest.fixture
def tecnico_wifi(app):
    return crear_usuario("wifi", RolUsuario.TECNICO_WIFI)


# ---------------------------------------------------------------------------
# Categoria de la interrupcion
# ---------------------------------------------------------------------------
def test_la_interrupcion_nace_como_enlace_de_cliente(nueva_interrupcion, despachador):
    inter = nueva_interrupcion(despachador)
    assert inter.categoria is CategoriaInterrupcion.ENLACE_CLIENTE
    assert inter.es_sitio_wifi is False


def test_el_despachador_la_crea_como_sitio_wifi(nueva_interrupcion, despachador):
    inter = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    assert inter.categoria is CategoriaInterrupcion.SITIO_WIFI
    assert inter.es_sitio_wifi is True


def test_el_despachador_corrige_la_categoria(nueva_interrupcion, despachador, operador):
    inter = nueva_interrupcion(despachador)
    servicio.actualizar_categoria(inter, despachador, "SITIO_WIFI")
    assert inter.es_sitio_wifi is True

    # Queda en el historial, como cualquier otro cambio.
    assert any(
        h.campo == "categoria" and h.valor_nuevo == "Sitio wifi" for h in inter.historial
    )

    # Pero no cualquiera: el operador no toca la categoria.
    with pytest.raises(TransicionInvalida, match="despachador"):
        servicio.actualizar_categoria(inter, operador, "ENLACE_CLIENTE")


def test_no_se_le_quita_el_sitio_wifi_a_quien_la_tiene(
    nueva_interrupcion, despachador, tecnico_wifi
):
    """Cambiar la categoria dejaria al tecnico con un ticket que no le toca."""
    inter = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    ejecutar_transicion(inter, despachador, "estado:ASIGNADA", asignado_a=tecnico_wifi)
    db.session.commit()

    with pytest.raises(TransicionInvalida, match="reasignala"):
        servicio.actualizar_categoria(inter, despachador, "ENLACE_CLIENTE")
    assert inter.es_sitio_wifi is True


# ---------------------------------------------------------------------------
# A quien se le entrega
# ---------------------------------------------------------------------------
def test_al_tecnico_de_wifi_solo_se_le_dan_las_de_sitio_wifi(
    nueva_interrupcion, despachador, tecnico_wifi
):
    enlace = nueva_interrupcion(despachador)
    with pytest.raises(TransicionInvalida, match="sitio wifi"):
        ejecutar_transicion(enlace, despachador, "estado:ASIGNADA", asignado_a=tecnico_wifi)

    wifi = nueva_interrupcion(
        despachador, identificador_externo="FD111111", categoria="SITIO_WIFI"
    )
    ejecutar_transicion(wifi, despachador, "estado:ASIGNADA", asignado_a=tecnico_wifi)
    db.session.commit()
    assert wifi.estado is EstadoInterrupcion.ASIGNADA
    assert wifi.asignado_a_id == tecnico_wifi.id


def test_se_le_puede_asignar_al_crearla(nueva_interrupcion, despachador, tecnico_wifi):
    """El caso del formulario: categoria y destinatario en el mismo envio."""
    inter = nueva_interrupcion(
        despachador, categoria="SITIO_WIFI", asignado_a=tecnico_wifi
    )
    db.session.commit()
    assert inter.asignado_a_id == tecnico_wifi.id
    assert inter.estado is EstadoInterrupcion.ASIGNADA


def test_al_crearla_tambien_se_revisa_la_categoria(
    nueva_interrupcion, despachador, tecnico_wifi
):
    with pytest.raises(servicio.DatosInvalidos, match="sitio wifi"):
        nueva_interrupcion(despachador, asignado_a=tecnico_wifi)


def test_la_orden_no_se_le_puede_asignar_al_crearla(
    nueva_orden, despachador, tecnico_wifi
):
    with pytest.raises(servicio.DatosInvalidos, match="operador activo"):
        nueva_orden(despachador, asignado_a=tecnico_wifi)


def test_el_formulario_de_creacion_asigna_al_tecnico(
    cliente, despachador, tecnico_wifi
):
    """De punta a punta por HTTP, como lo hace el despachador en pantalla."""
    entrar(cliente, despachador)
    respuesta = cliente.post(
        "/interrupciones/nueva-wifi",
        data={
            "identificador_externo": "WF4321",
            "nombre_cliente": "Plaza central",
            "titulo": "El sitio wifi no da servicio",
            "descripcion": "Reportado por la alcaldia.",
            "prioridad": "ALTA",
            "asignado_a_id": str(tecnico_wifi.id),
        },
        follow_redirects=True,
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.get_data(as_text=True)
    assert "operador activo" not in cuerpo
    assert tecnico_wifi.nombre_completo in cuerpo

    from sqlalchemy import select

    from app.models.interrupcion import Interrupcion

    inter = db.session.execute(
        select(Interrupcion).where(Interrupcion.identificador_externo == "WF4321")
    ).scalar_one()
    assert inter.asignado_a_id == tecnico_wifi.id
    assert inter.es_sitio_wifi is True


def test_al_tecnico_de_wifi_no_se_le_dan_ordenes_de_trabajo(
    nueva_orden, despachador, tecnico_wifi
):
    orden = nueva_orden(despachador)
    with pytest.raises(TransicionInvalida, match="operador activo"):
        ejecutar_transicion(orden, despachador, "estado:ASIGNADA", asignado_a=tecnico_wifi)


def test_una_de_sitio_wifi_tambien_se_le_puede_dar_a_un_operador(
    nueva_interrupcion, despachador, operador
):
    wifi = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    ejecutar_transicion(wifi, despachador, "estado:ASIGNADA", asignado_a=operador)
    db.session.commit()
    assert wifi.asignado_a_id == operador.id


def test_la_reasignacion_respeta_la_misma_regla(
    nueva_interrupcion, despachador, operador, tecnico_wifi
):
    enlace = nueva_interrupcion(despachador, asignado_a=operador)
    with pytest.raises(TransicionInvalida, match="sitio wifi"):
        servicio.reasignar(enlace, despachador, tecnico_wifi)

    wifi = nueva_interrupcion(
        despachador,
        identificador_externo="FD222222",
        categoria="SITIO_WIFI",
        asignado_a=operador,
    )
    servicio.reasignar(wifi, despachador, tecnico_wifi)
    assert wifi.asignado_a_id == tecnico_wifi.id


def test_un_tecnico_inactivo_no_recibe_nada(nueva_interrupcion, despachador, tecnico_wifi):
    tecnico_wifi.activo = False
    db.session.commit()
    wifi = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    with pytest.raises(TransicionInvalida, match="activo"):
        ejecutar_transicion(wifi, despachador, "estado:ASIGNADA", asignado_a=tecnico_wifi)


def test_el_selector_ofrece_al_tecnico_solo_en_las_de_sitio_wifi(
    nueva_interrupcion, nueva_orden, despachador, operador, tecnico_wifi
):
    from app.blueprints._acciones import destinatarios_para

    enlace = nueva_interrupcion(despachador)
    wifi = nueva_interrupcion(
        despachador, identificador_externo="FD333333", categoria="SITIO_WIFI"
    )
    orden = nueva_orden(despachador)

    assert tecnico_wifi.id not in {u.id for u in destinatarios_para(enlace)}
    assert tecnico_wifi.id not in {u.id for u in destinatarios_para(orden)}

    candidatos = {u.id for u in destinatarios_para(wifi)}
    assert tecnico_wifi.id in candidatos
    assert operador.id in candidatos


def test_el_selector_aclara_quien_es_tecnico_de_wifi(tecnico_wifi, operador, mixto):
    assert tecnico_wifi.etiqueta_asignacion.endswith("(tecnico de wifi)")
    assert operador.etiqueta_asignacion == operador.nombre_completo
    # Quien ademas es operador recibe cualquier cosa: no hace falta la nota.
    mixto.roles = [RolUsuario.OPERADOR, RolUsuario.TECNICO_WIFI]
    db.session.commit()
    assert mixto.etiqueta_asignacion == mixto.nombre_completo


# ---------------------------------------------------------------------------
# Trabaja igual que un operador
# ---------------------------------------------------------------------------
def test_el_tecnico_trabaja_y_cierra_su_interrupcion(
    nueva_interrupcion, despachador, tecnico_wifi
):
    inter = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    ejecutar_transicion(inter, despachador, "estado:ASIGNADA", asignado_a=tecnico_wifi)
    db.session.commit()

    assert claves(inter, tecnico_wifi) == {"estado:EN_PROCESO"}
    ejecutar_transicion(inter, tecnico_wifi, "estado:EN_PROCESO")
    db.session.commit()

    # Clasifica la dependencia, como el operador.
    servicio.clasificar_dependencia(inter, tecnico_wifi, Dependencia.DISTRIBUCION)
    assert inter.dependencia is Dependencia.DISTRIBUCION

    ejecutar_transicion(
        inter, tecnico_wifi, "estado:CERRADA", comentario="Se reinicio el AP del sitio"
    )
    db.session.commit()
    assert inter.estado is EstadoInterrupcion.CERRADA
    assert inter.cerrado_en is not None


def test_el_tecnico_puede_derivar_a_fibra(
    nueva_interrupcion, despachador, tecnico_wifi, agente_fibra
):
    inter = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    ejecutar_transicion(inter, despachador, "estado:ASIGNADA", asignado_a=tecnico_wifi)
    ejecutar_transicion(inter, tecnico_wifi, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, tecnico_wifi, "estado:DERIVADA_FIBRA",
        comentario="El enlace del sitio no levanta", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()

    assert inter.estado is EstadoInterrupcion.DERIVADA_FIBRA
    assert inter.estado_fibra is EstadoFibra.EN_REVISION
    # Y el aviso de la respuesta de fibra le llega a el.
    from app.services import notificaciones as notif

    ejecutar_transicion(
        inter, agente_fibra, "estado_fibra:FIBRA_OK", comentario="Tramo sin novedad"
    )
    db.session.commit()
    assert notif.contar_no_leidas(tecnico_wifi.id) >= 1


def test_el_tecnico_deja_abierta_con_motivo(nueva_interrupcion, despachador, tecnico_wifi):
    inter = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    ejecutar_transicion(inter, despachador, "estado:ASIGNADA", asignado_a=tecnico_wifi)
    ejecutar_transicion(inter, tecnico_wifi, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, tecnico_wifi, "estado:ABIERTA_OTRO_MOTIVO",
        comentario="Sin acceso al techo", motivo="No hay llaves del local",
        dependencia=Dependencia.DISTRIBUCION,
    )
    db.session.commit()
    assert inter.estado is EstadoInterrupcion.ABIERTA_OTRO_MOTIVO
    assert inter.motivo_apertura == "No hay llaves del local"


# ---------------------------------------------------------------------------
# Lo que NO puede
# ---------------------------------------------------------------------------
def test_no_mueve_interrupciones_ajenas(
    nueva_interrupcion, despachador, operador, tecnico_wifi
):
    ajena = nueva_interrupcion(despachador, categoria="SITIO_WIFI", asignado_a=operador)
    assert claves(ajena, tecnico_wifi) == set()
    with pytest.raises(TransicionInvalida):
        ejecutar_transicion(ajena, tecnico_wifi, "estado:EN_PROCESO")


def test_no_ve_ordenes_ni_interrupciones_ajenas(
    cliente, nueva_orden, nueva_interrupcion, despachador, operador, tecnico_wifi
):
    orden = nueva_orden(despachador, asignado_a=operador)
    ajena = nueva_interrupcion(despachador, asignado_a=operador)
    propia = nueva_interrupcion(
        despachador, identificador_externo="FD444444", categoria="SITIO_WIFI"
    )
    ejecutar_transicion(propia, despachador, "estado:ASIGNADA", asignado_a=tecnico_wifi)
    db.session.commit()

    assert puede_ver(orden, tecnico_wifi) is False
    assert puede_ver(ajena, tecnico_wifi) is False
    assert puede_ver(propia, tecnico_wifi) is True

    entrar(cliente, tecnico_wifi)
    assert cliente.get(orden.url_detalle).status_code == 403
    assert cliente.get(ajena.url_detalle).status_code == 403
    assert cliente.get(propia.url_detalle).status_code == 200


def test_sus_consultas_van_filtradas(app, tecnico_wifi):
    from sqlalchemy import false

    assert filtro_interrupciones(tecnico_wifi) is not None
    assert str(filtro_ordenes(tecnico_wifi)) == str(false())


def test_no_entra_a_la_gestion_ni_crea_tickets(cliente, tecnico_wifi):
    entrar(cliente, tecnico_wifi)
    for ruta in (
        "/buscar/",
        "/reportes/historico",
        "/dashboard/",
        "/interrupciones/nueva",
        "/ordenes/nueva",
        "/admin/usuarios",
    ):
        assert cliente.get(ruta).status_code == 403, ruta


def test_tampoco_hace_de_agente_de_fibra(
    cliente, nueva_interrupcion, despachador, tecnico_wifi
):
    inter = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    ejecutar_transicion(inter, despachador, "estado:ASIGNADA", asignado_a=tecnico_wifi)
    ejecutar_transicion(inter, tecnico_wifi, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, tecnico_wifi, "estado:DERIVADA_FIBRA",
        comentario="posible corte", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()

    assert not any(c.startswith("estado_fibra:") for c in claves(inter, tecnico_wifi))
    with pytest.raises(TransicionInvalida):
        ejecutar_transicion(inter, tecnico_wifi, "estado_fibra:FIBRA_OK", comentario="x")

    entrar(cliente, tecnico_wifi)
    assert cliente.get("/fibra/").status_code == 403


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------
def test_entra_directo_al_tablero_de_interrupciones(
    cliente, nueva_interrupcion, despachador, tecnico_wifi
):
    inter = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    ejecutar_transicion(inter, despachador, "estado:ASIGNADA", asignado_a=tecnico_wifi)
    db.session.commit()

    entrar(cliente, tecnico_wifi)
    cuerpo = cliente.get("/tablero").get_data(as_text=True)
    assert inter.folio in cuerpo  # el tablero por defecto es el de interrupciones
    assert "Sitio wifi" in cuerpo


def test_el_despachador_filtra_por_categoria(
    cliente, nueva_interrupcion, despachador, operador
):
    enlace = nueva_interrupcion(despachador)
    wifi = nueva_interrupcion(
        despachador, identificador_externo="FD555555", categoria="SITIO_WIFI"
    )
    entrar(cliente, despachador)

    resultado = cliente.get("/buscar/?categoria=SITIO_WIFI").get_data(as_text=True)
    assert wifi.folio in resultado
    assert enlace.folio not in resultado


def test_el_tecnico_aparece_en_el_dashboard(
    nueva_interrupcion, despachador, tecnico_wifi, admin
):
    from app.services import metricas
    from app.services.consultas import resolver_rango

    inter = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    ejecutar_transicion(inter, despachador, "estado:ASIGNADA", asignado_a=tecnico_wifi)
    ejecutar_transicion(inter, tecnico_wifi, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, tecnico_wifi, "estado:CERRADA",
        comentario="resuelto en sitio", dependencia=Dependencia.DISTRIBUCION,
    )
    db.session.commit()

    filas = metricas.por_operador(resolver_rango("30d")[:2], admin)
    fila = next(f for f in filas if f["operador"].id == tecnico_wifi.id)
    assert fila["soluciones"] == 1
    assert fila["asignados"] == 1

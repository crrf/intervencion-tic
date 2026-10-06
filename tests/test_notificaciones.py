"""Notificaciones in-app en los eventos clave del flujo."""
from __future__ import annotations

from app.extensions import db
from app.models.enums import Dependencia
from app.services import notificaciones as notif
from app.services.estados import ejecutar_transicion


def titulos(usuario):
    return [n.titulo for n in notif.listar(usuario.id)]


def test_asignar_notifica_al_operador(nueva_orden, despachador, operador):
    orden = nueva_orden(despachador)
    ejecutar_transicion(orden, despachador, "estado:ASIGNADA", asignado_a=operador)
    db.session.commit()

    assert notif.contar_no_leidas(operador.id) == 1
    assert orden.folio in titulos(operador)[0]


def test_derivar_a_fibra_avisa_a_los_agentes(
    nueva_interrupcion, despachador, operador, agente_fibra
):
    from tests.conftest import crear_usuario
    from app.models.enums import RolUsuario

    segundo = crear_usuario("fibra_b", RolUsuario.AGENTE_FIBRA)
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="corte probable", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()

    assert notif.contar_no_leidas(agente_fibra.id) == 1
    assert notif.contar_no_leidas(segundo.id) == 1
    assert "fibra" in titulos(agente_fibra)[0].lower()


def test_la_respuesta_de_fibra_avisa_al_operador(
    nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="corte probable", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()
    notif.marcar_todas_leidas(operador.id)

    ejecutar_transicion(
        inter, agente_fibra, "estado_fibra:FIBRA_CON_FALLA", comentario="Corte confirmado"
    )
    db.session.commit()

    assert notif.contar_no_leidas(operador.id) == 1
    assert "Fibra con falla" in titulos(operador)[0]


def test_el_ok_del_operador_avisa_a_los_despachadores(
    nueva_orden, despachador, operador
):
    from tests.conftest import crear_usuario
    from app.models.enums import RolUsuario

    segundo = crear_usuario("despachador_b", RolUsuario.DESPACHADOR)
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:OK_OPERADOR", comentario="terminado")
    db.session.commit()

    assert notif.contar_no_leidas(despachador.id) == 1
    assert notif.contar_no_leidas(segundo.id) == 1
    assert "OK del operador" in titulos(despachador)[0]


def test_devolver_el_ok_avisa_al_operador(nueva_orden, despachador, operador):
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:OK_OPERADOR", comentario="terminado")
    db.session.commit()
    notif.marcar_todas_leidas(operador.id)

    ejecutar_transicion(orden, despachador, "estado:EN_PROCESO", comentario="falta la foto")
    db.session.commit()

    assert notif.contar_no_leidas(operador.id) == 1
    assert "bandeja" in titulos(operador)[0]


def test_el_cierre_avisa_a_quien_creo_el_ticket(
    nueva_orden, despachador, operador, admin
):
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:OK_OPERADOR", comentario="listo")
    db.session.commit()
    notif.marcar_todas_leidas(despachador.id)

    # Cierra el admin para que el aviso de cierre le llegue al despachador,
    # que es quien creo la orden.
    ejecutar_transicion(orden, admin, "estado:CERRADA", comentario="en SIPREC")
    db.session.commit()

    assert notif.contar_no_leidas(despachador.id) == 1
    assert "cerrado" in titulos(despachador)[0].lower()


def test_cerrar_en_siprec_no_avisa_de_una_devolucion(
    nueva_orden, despachador, operador
):
    """Cerrar y devolver salen las dos del mismo estado: no se pueden confundir.

    El operador solo debe enterarse si la orden vuelve a su bandeja; si se
    cerro, el aviso seria falso.
    """
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:OK_OPERADOR", comentario="terminado")
    db.session.commit()
    notif.marcar_todas_leidas(operador.id)

    ejecutar_transicion(orden, despachador, "estado:CERRADA", comentario="en SIPREC")
    db.session.commit()

    assert notif.contar_no_leidas(operador.id) == 0
    assert not any("bandeja" in t for t in titulos(operador))


def test_reabrir_una_cerrada_tampoco_avisa_de_devolucion(
    nueva_orden, despachador, operador, admin
):
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:OK_OPERADOR", comentario="terminado")
    ejecutar_transicion(orden, despachador, "estado:CERRADA", comentario="en SIPREC")
    db.session.commit()
    notif.marcar_todas_leidas(operador.id)

    ejecutar_transicion(orden, admin, "estado:EN_PROCESO", comentario="se revisa")
    db.session.commit()
    assert not any("bandeja" in t for t in titulos(operador))


def test_no_se_notifica_a_uno_mismo(nueva_orden, mixto):
    orden = nueva_orden(mixto)
    ejecutar_transicion(orden, mixto, "estado:ASIGNADA", asignado_a=mixto)
    ejecutar_transicion(orden, mixto, "estado:EN_PROCESO")
    ejecutar_transicion(orden, mixto, "estado:OK_OPERADOR", comentario="hecho")
    ejecutar_transicion(orden, mixto, "estado:CERRADA", comentario="en SIPREC")
    db.session.commit()

    assert notif.contar_no_leidas(mixto.id) == 0


def test_marcar_todas_leidas(nueva_orden, despachador, operador):
    orden = nueva_orden(despachador)
    ejecutar_transicion(orden, despachador, "estado:ASIGNADA", asignado_a=operador)
    db.session.commit()

    assert notif.marcar_todas_leidas(operador.id) == 1
    assert notif.contar_no_leidas(operador.id) == 0

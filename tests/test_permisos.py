"""Visibilidad y acceso a las secciones, con la aplicacion real."""
from __future__ import annotations

from app.extensions import db
from app.models.enums import Dependencia
from app.security.decoradores import puede_ver
from app.services.estados import ejecutar_transicion


def entrar(cliente, usuario):
    return cliente.post(
        "/login",
        data={"usuario": usuario.usuario, "password": "Clave.2026"},
        follow_redirects=False,
    )


def test_un_operador_no_ve_el_ticket_de_otro(
    cliente, nueva_orden, despachador, operador, operador_b
):
    orden = nueva_orden(despachador, asignado_a=operador)
    assert puede_ver(orden, operador) is True
    assert puede_ver(orden, operador_b) is False

    entrar(cliente, operador_b)
    assert cliente.get(orden.url_detalle).status_code == 403


def test_el_agente_de_fibra_no_ve_ordenes_ni_interrupciones_sin_derivar(
    cliente, nueva_orden, nueva_interrupcion, despachador, operador, agente_fibra
):
    orden = nueva_orden(despachador, asignado_a=operador)
    inter = nueva_interrupcion(despachador, asignado_a=operador)

    assert puede_ver(orden, agente_fibra) is False
    assert puede_ver(inter, agente_fibra) is False

    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="corte probable", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()
    assert puede_ver(inter, agente_fibra) is True

    entrar(cliente, agente_fibra)
    assert cliente.get(orden.url_detalle).status_code == 403
    assert cliente.get(inter.url_detalle).status_code == 200


def test_el_despachador_ve_en_el_tablero_las_ordenes_con_ok(
    cliente, nueva_orden, despachador, operador
):
    """El OK del operador tiene que llegarle a la vista al despachador."""
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:OK_OPERADOR", comentario="terminado")
    db.session.commit()

    entrar(cliente, despachador)
    tablero = cliente.get("/tablero?tipo=ordenes")
    assert tablero.status_code == 200
    cuerpo = tablero.get_data(as_text=True)
    assert "OK del operador" in cuerpo
    assert "Cerrada en SIPREC" in cuerpo

    # Y el dashboard le dice cuantas esperan ese cierre.
    assert "por cerrar en SIPREC" in cliente.get("/dashboard/").get_data(as_text=True)


def test_gestion_cerrada_a_operadores(cliente, operador):
    entrar(cliente, operador)
    for ruta in ("/buscar/", "/reportes/historico", "/reportes/auditoria", "/dashboard/"):
        assert cliente.get(ruta).status_code == 403, ruta


def test_gestion_abierta_a_despachador_y_admin(cliente, despachador, admin):
    entrar(cliente, despachador)
    for ruta in ("/buscar/", "/reportes/historico", "/reportes/auditoria", "/dashboard/"):
        assert cliente.get(ruta).status_code == 200, ruta

    cliente.get("/logout")
    entrar(cliente, admin)
    assert cliente.get("/dashboard/").status_code == 200


def test_solo_el_admin_administra_usuarios(cliente, despachador, admin):
    entrar(cliente, despachador)
    assert cliente.get("/admin/usuarios").status_code == 403
    cliente.get("/logout")

    entrar(cliente, admin)
    assert cliente.get("/admin/usuarios").status_code == 200


def test_crear_tickets_exige_despachador(cliente, operador, despachador):
    entrar(cliente, operador)
    assert cliente.get("/ordenes/nueva").status_code == 403
    assert cliente.get("/interrupciones/nueva").status_code == 403
    cliente.get("/logout")

    entrar(cliente, despachador)
    assert cliente.get("/ordenes/nueva").status_code == 200
    assert cliente.get("/interrupciones/nueva").status_code == 200


def test_sin_sesion_redirige_al_login(cliente):
    respuesta = cliente.get("/tablero")
    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]


def test_usuario_desactivado_no_entra(cliente, operador):
    operador.activo = False
    db.session.commit()
    respuesta = entrar(cliente, operador)
    assert respuesta.status_code == 403

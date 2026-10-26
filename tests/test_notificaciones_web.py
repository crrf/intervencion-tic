"""La campana de notificaciones: contador, panel y marcado de leidas."""
from __future__ import annotations

from app.extensions import db
from app.models.notificacion import Notificacion
from app.services import notificaciones as servicio
from app.services.estados import ejecutar_transicion

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    return cliente.post("/login", data={"usuario": usuario.usuario, "password": CLAVE})


def asignar(orden, despachador, operador):
    ejecutar_transicion(orden, despachador, "estado:ASIGNADA", asignado_a=operador)
    db.session.commit()


# ---------------------------------------------------------------------------
# Contador
# ---------------------------------------------------------------------------
def test_el_badge_cuenta_las_no_leidas(cliente, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador)
    asignar(orden, despachador, operador)

    entrar(cliente, operador)
    cuerpo = cliente.get("/notificaciones/badge").get_data(as_text=True)
    assert "1" in cuerpo


def test_el_badge_vacio_no_pinta_nada(cliente, operador):
    entrar(cliente, operador)
    assert cliente.get("/notificaciones/badge").get_data(as_text=True).strip() == ""


def test_el_badge_corta_en_99(cliente, operador):
    for i in range(101):
        servicio.crear(operador.id, f"Aviso {i}")
    db.session.commit()

    entrar(cliente, operador)
    assert "99+" in cliente.get("/notificaciones/badge").get_data(as_text=True)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------
def test_el_panel_lista_las_notificaciones(cliente, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador)
    asignar(orden, despachador, operador)

    entrar(cliente, operador)
    cuerpo = cliente.get("/notificaciones/panel").get_data(as_text=True)
    assert orden.folio in cuerpo
    assert "<html" not in cuerpo, "es un parcial para HTMX"


def test_el_panel_sin_nada_lo_dice(cliente, operador):
    entrar(cliente, operador)
    cuerpo = cliente.get("/notificaciones/panel").get_data(as_text=True)
    assert "No tienes" in cuerpo or "sin" in cuerpo.lower()


def test_cada_uno_ve_solo_las_suyas(cliente, nueva_orden, despachador, operador, operador_b):
    orden = nueva_orden(despachador)
    asignar(orden, despachador, operador)

    entrar(cliente, operador_b)
    assert orden.folio not in cliente.get("/notificaciones/panel").get_data(as_text=True)
    assert servicio.contar_no_leidas(operador_b.id) == 0


def test_el_panel_solo_trae_las_ultimas_quince(cliente, operador):
    for i in range(20):
        servicio.crear(operador.id, f"Aviso numero {i}")
    db.session.commit()

    entrar(cliente, operador)
    cuerpo = cliente.get("/notificaciones/panel").get_data(as_text=True)
    assert "Aviso numero 19" in cuerpo
    assert "Aviso numero 0" not in cuerpo


# ---------------------------------------------------------------------------
# Marcar leidas
# ---------------------------------------------------------------------------
def test_leer_todas(cliente, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador)
    asignar(orden, despachador, operador)
    assert servicio.contar_no_leidas(operador.id) == 1

    entrar(cliente, operador)
    respuesta = cliente.post("/notificaciones/leer-todas")
    assert respuesta.status_code == 200
    assert servicio.contar_no_leidas(operador.id) == 0


def test_leer_todas_no_toca_las_de_otros(
    cliente, nueva_orden, despachador, operador, operador_b
):
    servicio.crear(operador.id, "Para el primero")
    servicio.crear(operador_b.id, "Para el segundo")
    db.session.commit()

    entrar(cliente, operador)
    cliente.post("/notificaciones/leer-todas")
    assert servicio.contar_no_leidas(operador.id) == 0
    assert servicio.contar_no_leidas(operador_b.id) == 1


def test_abrir_una_notificacion_la_marca_y_redirige(
    cliente, nueva_orden, despachador, operador
):
    orden = nueva_orden(despachador)
    asignar(orden, despachador, operador)
    aviso = servicio.listar(operador.id)[0]

    entrar(cliente, operador)
    respuesta = cliente.get(f"/notificaciones/abrir/{aviso.id}?url={orden.url_detalle}")
    assert respuesta.status_code == 302
    assert respuesta.headers["Location"] == orden.url_detalle
    assert servicio.contar_no_leidas(operador.id) == 0


def test_abrir_con_un_destino_externo_va_al_inicio(cliente, operador):
    servicio.crear(operador.id, "Aviso")
    db.session.commit()
    aviso = servicio.listar(operador.id)[0]

    entrar(cliente, operador)
    respuesta = cliente.get(
        f"/notificaciones/abrir/{aviso.id}?url=https://malo.example"
    )
    assert "malo.example" not in respuesta.headers["Location"]


def test_no_se_marca_la_notificacion_de_otro(cliente, operador, operador_b):
    servicio.crear(operador_b.id, "Para el segundo")
    db.session.commit()
    ajena = servicio.listar(operador_b.id)[0]

    entrar(cliente, operador)
    cliente.get(f"/notificaciones/abrir/{ajena.id}")
    assert servicio.contar_no_leidas(operador_b.id) == 1, "sigue sin leer"


def test_las_notificaciones_exigen_sesion(cliente, app):
    for ruta in ("/notificaciones/badge", "/notificaciones/panel"):
        assert cliente.get(ruta).status_code == 302
    assert cliente.post("/notificaciones/leer-todas").status_code == 302


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------
def test_el_mensaje_se_recorta_a_400(app, operador):
    servicio.crear(operador.id, "Titulo", "x" * 900)
    db.session.commit()
    guardada = db.session.get(Notificacion, servicio.listar(operador.id)[0].id)
    assert len(guardada.mensaje) == 400

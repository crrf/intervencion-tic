"""Paginas de error, salud y proteccion CSRF."""
from __future__ import annotations

import io

from app.extensions import db

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    return cliente.post("/login", data={"usuario": usuario.usuario, "password": CLAVE})


# ---------------------------------------------------------------------------
# Salud
# ---------------------------------------------------------------------------
def test_salud_responde_sin_sesion(cliente, app):
    respuesta = cliente.get("/salud")
    assert respuesta.status_code == 200
    assert respuesta.get_json() == {"estado": "ok"}


# ---------------------------------------------------------------------------
# 404
# ---------------------------------------------------------------------------
def test_una_ruta_que_no_existe_muestra_la_pagina_de_error(cliente, despachador):
    entrar(cliente, despachador)
    respuesta = cliente.get("/una-ruta-inventada")
    assert respuesta.status_code == 404
    cuerpo = respuesta.get_data(as_text=True)
    assert "404" in cuerpo
    assert "no existe" in cuerpo


def test_el_404_de_htmx_es_texto_plano(cliente, despachador):
    entrar(cliente, despachador)
    respuesta = cliente.get("/una-ruta-inventada", headers={"HX-Request": "true"})
    assert respuesta.status_code == 404
    cuerpo = respuesta.get_data(as_text=True)
    assert "<html" not in cuerpo
    assert "No se encontro" in cuerpo


# ---------------------------------------------------------------------------
# 403
# ---------------------------------------------------------------------------
def test_el_403_muestra_la_pagina_de_error(cliente, operador):
    entrar(cliente, operador)
    respuesta = cliente.get("/dashboard/")
    assert respuesta.status_code == 403
    cuerpo = respuesta.get_data(as_text=True)
    assert "403" in cuerpo
    assert "Sin permiso" in cuerpo


def test_el_403_de_htmx_es_texto_plano(cliente, operador):
    entrar(cliente, operador)
    respuesta = cliente.get("/dashboard/", headers={"HX-Request": "true"})
    assert respuesta.status_code == 403
    assert "<html" not in respuesta.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 413: archivo demasiado grande
# ---------------------------------------------------------------------------
def test_un_archivo_enorme_da_413(cliente, despachador, monkeypatch, app):
    monkeypatch.setitem(app.config, "MAX_CONTENT_LENGTH", 2048)
    entrar(cliente, despachador)

    respuesta = cliente.post(
        "/ordenes/nueva",
        data={
            "identificador_externo": "ED123456",
            "nombre_cliente": "Cliente",
            "titulo": "Titulo",
            "foto_anverso": (io.BytesIO(b"x" * 50_000), "grande.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert respuesta.status_code == 413
    assert "tamano maximo" in respuesta.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 500
# ---------------------------------------------------------------------------
def test_un_error_inesperado_muestra_la_pagina_y_deshace_la_sesion(
    cliente, admin, monkeypatch, app
):
    """El manejador del 500 tiene que hacer rollback: si no, la sesion de
    SQLAlchemy queda envenenada para la peticion siguiente."""
    from app.services import metricas

    def explotar(*args, **kwargs):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(metricas, "panel_completo", explotar)
    # En pruebas Flask propaga las excepciones; aqui se quiere el manejador.
    monkeypatch.setitem(app.config, "PROPAGATE_EXCEPTIONS", False)

    entrar(cliente, admin)
    respuesta = cliente.get("/dashboard/")
    assert respuesta.status_code == 500
    cuerpo = respuesta.get_data(as_text=True)
    assert "500" in cuerpo
    assert "fallo simulado" not in cuerpo, "no se filtran detalles internos"

    # La aplicacion sigue respondiendo despues del error.
    assert cliente.get("/salud").status_code == 200


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def test_sin_token_csrf_el_post_se_rechaza(cliente, despachador, monkeypatch, app):
    """Las pruebas corren con CSRF desactivado; aqui se enciende a proposito."""
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)
    entrar(cliente, despachador)

    respuesta = cliente.post(
        "/ordenes/nueva",
        data={
            "identificador_externo": "ED123456",
            "nombre_cliente": "Cliente",
            "titulo": "Titulo",
        },
    )
    assert respuesta.status_code == 400


# ---------------------------------------------------------------------------
# Guardia de cambio de contrasena obligatorio
# ---------------------------------------------------------------------------
def test_con_la_clave_restablecida_solo_se_llega_a_mi_cuenta(cliente, operador):
    operador.debe_cambiar_password = True
    db.session.commit()

    entrar(cliente, operador)
    respuesta = cliente.get("/tablero", follow_redirects=True)
    assert "/mi-cuenta" in respuesta.request.path
    assert "Fija una nueva" in respuesta.get_data(as_text=True)

    assert cliente.get("/mi-cuenta").status_code == 200
    assert cliente.get("/salud").status_code == 200


def test_el_guardia_responde_403_a_htmx(cliente, operador):
    operador.debe_cambiar_password = True
    db.session.commit()

    entrar(cliente, operador)
    respuesta = cliente.get(
        "/tablero/columnas?tipo=interrupciones", headers={"HX-Request": "true"}
    )
    assert respuesta.status_code == 403
    assert "contrasena nueva" in respuesta.get_data(as_text=True)

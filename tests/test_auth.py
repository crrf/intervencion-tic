"""Inicio de sesion, cierre y cambio de contrasena propia."""
from __future__ import annotations

from app.extensions import db
from app.models.enums import RolUsuario
from tests.conftest import crear_usuario

CLAVE = "Clave.2026"


def login(cliente, usuario, password=CLAVE, **extra):
    return cliente.post(
        "/login", data={"usuario": usuario, "password": password, **extra}
    )


# ---------------------------------------------------------------------------
# Entrar
# ---------------------------------------------------------------------------
def test_entra_con_sus_credenciales(cliente, operador):
    respuesta = login(cliente, operador.usuario)
    assert respuesta.status_code == 302
    assert cliente.get("/tablero").status_code == 200


def test_la_clave_incorrecta_devuelve_401(cliente, operador):
    respuesta = login(cliente, operador.usuario, password="otra-cosa")
    assert respuesta.status_code == 401
    assert "incorrectos" in respuesta.get_data(as_text=True)


def test_un_usuario_que_no_existe_da_el_mismo_mensaje(cliente, app):
    respuesta = login(cliente, "fantasma")
    assert respuesta.status_code == 401
    cuerpo = respuesta.get_data(as_text=True)
    assert "incorrectos" in cuerpo
    assert "no existe" not in cuerpo, "no se revela si la cuenta existe"


def test_una_cuenta_desactivada_no_entra(cliente, operador):
    operador.activo = False
    db.session.commit()
    respuesta = login(cliente, operador.usuario)
    assert respuesta.status_code == 403
    assert "desactivada" in respuesta.get_data(as_text=True)


def test_una_cuenta_sin_roles_no_entra(cliente, app):
    huerfano = crear_usuario("huerfano")
    assert huerfano.roles == set()
    respuesta = login(cliente, "huerfano")
    assert respuesta.status_code == 403
    assert "rol" in respuesta.get_data(as_text=True)


def test_el_login_respeta_el_destino_interno(cliente, despachador):
    respuesta = cliente.post(
        "/login?next=/buscar/",
        data={"usuario": despachador.usuario, "password": CLAVE},
    )
    assert respuesta.headers["Location"] == "/buscar/"


def test_el_login_ignora_un_destino_externo(cliente, despachador):
    """Si no se filtrara, seria una redireccion abierta."""
    for destino in ("https://malo.example/phishing", "//malo.example", "javascript:alert(1)"):
        cliente.get("/logout")
        respuesta = cliente.post(
            f"/login?next={destino}",
            data={"usuario": despachador.usuario, "password": CLAVE},
        )
        assert "malo.example" not in respuesta.headers["Location"], destino
        assert "javascript" not in respuesta.headers["Location"], destino


def test_quien_ya_entro_no_vuelve_al_login(cliente, operador):
    login(cliente, operador.usuario)
    respuesta = cliente.get("/login")
    assert respuesta.status_code == 302


def test_el_formulario_de_login_se_ve_sin_sesion(cliente, app):
    respuesta = cliente.get("/login")
    assert respuesta.status_code == 200
    assert 'name="password"' in respuesta.get_data(as_text=True)


def test_recordarme_no_rompe_el_login(cliente, operador):
    respuesta = login(cliente, operador.usuario, recordarme="1")
    assert respuesta.status_code == 302


# ---------------------------------------------------------------------------
# Salir
# ---------------------------------------------------------------------------
def test_cerrar_sesion(cliente, operador):
    login(cliente, operador.usuario)
    respuesta = cliente.get("/logout", follow_redirects=True)
    assert "Sesion cerrada" in respuesta.get_data(as_text=True)
    assert cliente.get("/tablero").status_code == 302


def test_salir_sin_sesion_redirige_al_login(cliente, app):
    assert cliente.get("/logout").status_code == 302


# ---------------------------------------------------------------------------
# Mi cuenta: cambio de contrasena
# ---------------------------------------------------------------------------
def test_cambia_su_propia_contrasena(cliente, operador):
    login(cliente, operador.usuario)
    respuesta = cliente.post(
        "/mi-cuenta",
        data={"actual": CLAVE, "nueva": "ClaveNueva.9", "repetir": "ClaveNueva.9"},
        follow_redirects=True,
    )
    assert "actualizada" in respuesta.get_data(as_text=True)

    cliente.get("/logout")
    assert login(cliente, operador.usuario, password=CLAVE).status_code == 401
    assert login(cliente, operador.usuario, password="ClaveNueva.9").status_code == 302


def test_la_actual_tiene_que_ser_correcta(cliente, operador):
    login(cliente, operador.usuario)
    respuesta = cliente.post(
        "/mi-cuenta",
        data={"actual": "me-la-invente", "nueva": "ClaveNueva.9", "repetir": "ClaveNueva.9"},
        follow_redirects=True,
    )
    assert "actual no es correcta" in respuesta.get_data(as_text=True)
    assert operador.check_password(CLAVE)


def test_las_nuevas_tienen_que_coincidir(cliente, operador):
    login(cliente, operador.usuario)
    respuesta = cliente.post(
        "/mi-cuenta",
        data={"actual": CLAVE, "nueva": "ClaveNueva.9", "repetir": "OtraCosa.9"},
        follow_redirects=True,
    )
    assert "no coinciden" in respuesta.get_data(as_text=True)
    assert operador.check_password(CLAVE)


def test_la_nueva_tiene_largo_minimo(cliente, operador):
    login(cliente, operador.usuario)
    respuesta = cliente.post(
        "/mi-cuenta",
        data={"actual": CLAVE, "nueva": "corta", "repetir": "corta"},
        follow_redirects=True,
    )
    assert "al menos 8" in respuesta.get_data(as_text=True)
    assert operador.check_password(CLAVE)


def test_la_nueva_no_puede_ser_la_misma(cliente, operador):
    login(cliente, operador.usuario)
    respuesta = cliente.post(
        "/mi-cuenta",
        data={"actual": CLAVE, "nueva": CLAVE, "repetir": CLAVE},
        follow_redirects=True,
    )
    assert "distinta de la anterior" in respuesta.get_data(as_text=True)


def test_mi_cuenta_exige_sesion(cliente, app):
    assert cliente.get("/mi-cuenta").status_code == 302


def test_la_pagina_de_cuenta_muestra_los_roles(cliente, mixto):
    login(cliente, mixto.usuario)
    cuerpo = cliente.get("/mi-cuenta").get_data(as_text=True)
    assert RolUsuario.DESPACHADOR.etiqueta in cuerpo
    assert RolUsuario.OPERADOR.etiqueta in cuerpo

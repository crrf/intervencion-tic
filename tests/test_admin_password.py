"""Restablecimiento de contrasenas por el administrador."""
from __future__ import annotations

import pytest

from app.extensions import db
from app.models.enums import RolUsuario
from app.services import usuarios as servicio
from tests.conftest import crear_usuario

CLAVE = "Clave.2026"


def entrar(cliente, usuario, password=CLAVE):
    return cliente.post(
        "/login", data={"usuario": usuario.usuario, "password": password}, follow_redirects=False
    )


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------
def test_el_admin_restablece_la_clave_de_cualquier_usuario(app, admin, operador):
    nueva = servicio.restablecer_password(operador, admin, "OtraClave.99")

    assert nueva == "OtraClave.99"
    assert operador.check_password("OtraClave.99")
    assert not operador.check_password(CLAVE), "la clave anterior debe dejar de servir"
    assert operador.debe_cambiar_password is True


def test_sin_clave_se_genera_una_temporal(app, admin, agente_fibra):
    generada = servicio.restablecer_password(agente_fibra, admin)

    assert len(generada) >= 12
    assert agente_fibra.check_password(generada)
    # Alfabeto sin caracteres que se confundan al dictarla.
    assert not set(generada) & set("0O1lI")


def test_dos_generadas_no_se_repiten(app, admin, operador, operador_b):
    a = servicio.restablecer_password(operador, admin)
    b = servicio.restablecer_password(operador_b, admin)
    assert a != b


def test_quien_no_es_admin_no_puede_restablecer(app, despachador, operador):
    with pytest.raises(servicio.ErrorUsuario, match="administrador"):
        servicio.restablecer_password(operador, despachador, "LoQueSea.99")
    assert operador.check_password(CLAVE), "la clave no debio cambiar"


def test_clave_demasiado_corta(app, admin, operador):
    with pytest.raises(servicio.ErrorUsuario, match="al menos 8"):
        servicio.restablecer_password(operador, admin, "corta")


def test_el_admin_que_cambia_la_suya_no_queda_marcado(app, admin):
    servicio.restablecer_password(admin, admin, "MiClaveNueva.1")
    assert admin.debe_cambiar_password is False


def test_al_cambiarla_el_titular_se_limpia_la_marca(app, admin, operador):
    servicio.restablecer_password(operador, admin, "Temporal.123")
    servicio.cambiar_password_propia(operador, None, "LaMiaPropia.9", "LaMiaPropia.9")

    assert operador.debe_cambiar_password is False
    assert operador.check_password("LaMiaPropia.9")


def test_el_cambio_normal_sigue_pidiendo_la_actual(app, operador):
    with pytest.raises(servicio.ErrorUsuario, match="actual no es correcta"):
        servicio.cambiar_password_propia(operador, "equivocada", "NuevaClave.1", "NuevaClave.1")


def test_no_se_admite_repetir_la_misma(app, operador):
    with pytest.raises(servicio.ErrorUsuario, match="distinta"):
        servicio.cambiar_password_propia(operador, CLAVE, CLAVE, CLAVE)


def test_las_nuevas_deben_coincidir(app, operador):
    with pytest.raises(servicio.ErrorUsuario, match="no coinciden"):
        servicio.cambiar_password_propia(operador, CLAVE, "NuevaClave.1", "OtraCosa.2")


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
def test_el_admin_restablece_desde_la_web(cliente, admin, operador):
    entrar(cliente, admin)
    respuesta = cliente.post(
        f"/admin/usuarios/{operador.id}/restablecer-password",
        data={"password": "DesdeLaWeb.9"},
        follow_redirects=True,
    )
    assert respuesta.status_code == 200
    assert operador.check_password("DesdeLaWeb.9")
    assert operador.debe_cambiar_password is True


def test_la_clave_generada_se_muestra_una_vez(cliente, admin, operador):
    entrar(cliente, admin)
    respuesta = cliente.post(
        f"/admin/usuarios/{operador.id}/restablecer-password",
        data={"generar": "1"},
        follow_redirects=True,
    )
    html = respuesta.get_data(as_text=True)
    assert "Contrasena temporal" in html
    assert "no se vuelve a mostrar" in html


def test_un_despachador_no_puede_restablecer_por_la_web(cliente, despachador, operador):
    entrar(cliente, despachador)
    respuesta = cliente.post(
        f"/admin/usuarios/{operador.id}/restablecer-password", data={"password": "Intruso.99"}
    )
    assert respuesta.status_code == 403
    assert operador.check_password(CLAVE)


def test_el_usuario_entra_con_la_clave_nueva(cliente, admin, operador):
    servicio.restablecer_password(operador, admin, "ClaveFresca.1")

    assert entrar(cliente, operador, CLAVE).status_code == 401
    assert entrar(cliente, operador, "ClaveFresca.1").status_code == 302


def test_tras_el_restablecimiento_se_obliga_a_cambiarla(cliente, admin, operador):
    servicio.restablecer_password(operador, admin, "ClaveFresca.1")
    entrar(cliente, operador, "ClaveFresca.1")

    # Cualquier pantalla redirige a /mi-cuenta hasta que fije una nueva.
    respuesta = cliente.get("/tablero")
    assert respuesta.status_code == 302
    assert "/mi-cuenta" in respuesta.headers["Location"]

    # Y /mi-cuenta si es accesible, sin pedir la contrasena actual.
    pagina = cliente.get("/mi-cuenta")
    assert pagina.status_code == 200
    html = pagina.get_data(as_text=True)
    assert "restablecio tu contrasena" in html
    assert 'name="actual"' not in html

    cliente.post(
        "/mi-cuenta",
        data={"nueva": "YaEsMia.2026", "repetir": "YaEsMia.2026"},
        follow_redirects=False,
    )
    assert operador.debe_cambiar_password is False
    assert cliente.get("/tablero").status_code == 200


def test_puede_cerrar_sesion_aunque_deba_cambiarla(cliente, admin, operador):
    servicio.restablecer_password(operador, admin, "ClaveFresca.1")
    entrar(cliente, operador, "ClaveFresca.1")
    assert cliente.get("/logout").status_code == 302


def test_un_usuario_sin_marca_navega_normal(cliente, operador):
    entrar(cliente, operador)
    assert cliente.get("/tablero").status_code == 200


def test_el_admin_puede_restablecer_a_otro_admin(app, admin):
    otro = crear_usuario("admin_b", RolUsuario.ADMIN)
    servicio.restablecer_password(otro, admin, "EntreAdmins.1")
    assert otro.check_password("EntreAdmins.1")
    assert otro.debe_cambiar_password is True


def test_la_lista_marca_a_quien_tiene_restablecimiento_pendiente(cliente, admin, operador):
    servicio.restablecer_password(operador, admin, "Pendiente.123")
    entrar(cliente, admin)
    html = cliente.get("/admin/usuarios").get_data(as_text=True)
    assert "Clave por cambiar" in html


def test_editar_ya_no_cambia_la_clave(cliente, admin, operador):
    """El formulario de datos no debe tocar la contrasena: eso es del bloque
    de restablecimiento."""
    entrar(cliente, admin)
    cliente.post(
        f"/admin/usuarios/{operador.id}",
        data={"nombre_completo": "Nombre Cambiado", "roles": ["OPERADOR"],
              "password": "Colada.9999"},
        follow_redirects=True,
    )
    db.session.refresh(operador)
    assert operador.nombre_completo == "Nombre Cambiado"
    assert operador.check_password(CLAVE), "la clave no debio cambiar por este formulario"

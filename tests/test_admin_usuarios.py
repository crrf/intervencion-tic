"""Administracion de usuarios: alta, edicion de roles y activacion."""
from __future__ import annotations

from sqlalchemy import select

from app.extensions import db
from app.models.enums import RolUsuario
from app.models.usuario import Usuario
from tests.conftest import crear_usuario

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    return cliente.post("/login", data={"usuario": usuario.usuario, "password": CLAVE})


def buscar(login) -> Usuario | None:
    return db.session.execute(
        select(Usuario).where(Usuario.usuario == login)
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Permisos de la seccion
# ---------------------------------------------------------------------------
def test_solo_el_admin_entra(cliente, admin, despachador, operador):
    for usuario, esperado in ((despachador, 403), (operador, 403), (admin, 200)):
        cliente.get("/logout")
        entrar(cliente, usuario)
        assert cliente.get("/admin/usuarios").status_code == esperado, usuario.usuario
        assert cliente.get("/admin/usuarios/nuevo").status_code == esperado


def test_sin_sesion_redirige(cliente, app):
    assert cliente.get("/admin/usuarios").status_code == 302


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------
def test_crea_un_usuario_con_varios_roles(cliente, admin):
    entrar(cliente, admin)
    respuesta = cliente.post(
        "/admin/usuarios/nuevo",
        data={
            "usuario": "nuevo1",
            "nombre_completo": "Persona Nueva",
            "email": "nueva@empresa.com",
            "password": "ClaveInicial.1",
            "roles": ["DESPACHADOR", "OPERADOR"],
        },
        follow_redirects=True,
    )
    assert "creado" in respuesta.get_data(as_text=True)

    u = buscar("nuevo1")
    assert u is not None
    assert u.activo is True
    assert u.roles == {RolUsuario.DESPACHADOR, RolUsuario.OPERADOR}
    assert u.check_password("ClaveInicial.1")
    assert u.email == "nueva@empresa.com"


def test_crea_un_tecnico_de_wifi(cliente, admin):
    """El rol nuevo tiene que estar disponible en el formulario."""
    entrar(cliente, admin)
    formulario = cliente.get("/admin/usuarios/nuevo").get_data(as_text=True)
    assert 'value="TECNICO_WIFI"' in formulario
    assert RolUsuario.TECNICO_WIFI.etiqueta in formulario

    cliente.post(
        "/admin/usuarios/nuevo",
        data={
            "usuario": "wifi9",
            "nombre_completo": "Tecnico De Wifi",
            "password": "ClaveInicial.1",
            "roles": ["TECNICO_WIFI"],
        },
        follow_redirects=True,
    )
    assert buscar("wifi9").roles == {RolUsuario.TECNICO_WIFI}


def test_el_alta_valida_los_datos(cliente, admin):
    entrar(cliente, admin)
    casos = [
        ({"usuario": "", "nombre_completo": "X", "password": "ClaveInicial.1",
          "roles": ["OPERADOR"]}, "obligatorios"),
        ({"usuario": "x1", "nombre_completo": "", "password": "ClaveInicial.1",
          "roles": ["OPERADOR"]}, "obligatorios"),
        ({"usuario": "x2", "nombre_completo": "X", "password": "corta",
          "roles": ["OPERADOR"]}, "al menos 8"),
        ({"usuario": "x3", "nombre_completo": "X", "password": "ClaveInicial.1",
          "roles": []}, "al menos un rol"),
    ]
    for datos, esperado in casos:
        respuesta = cliente.post("/admin/usuarios/nuevo", data=datos)
        assert esperado in respuesta.get_data(as_text=True), datos
        assert buscar(datos["usuario"]) is None


def test_no_se_repite_el_nombre_de_usuario(cliente, admin, operador):
    entrar(cliente, admin)
    respuesta = cliente.post(
        "/admin/usuarios/nuevo",
        data={
            "usuario": operador.usuario,
            "nombre_completo": "Otro",
            "password": "ClaveInicial.1",
            "roles": ["OPERADOR"],
        },
    )
    assert "ya existe" in respuesta.get_data(as_text=True)


def test_un_rol_inventado_se_ignora(cliente, admin):
    entrar(cliente, admin)
    cliente.post(
        "/admin/usuarios/nuevo",
        data={
            "usuario": "raro",
            "nombre_completo": "Rol Raro",
            "password": "ClaveInicial.1",
            "roles": ["PRESIDENTE", "OPERADOR"],
        },
        follow_redirects=True,
    )
    assert buscar("raro").roles == {RolUsuario.OPERADOR}


# ---------------------------------------------------------------------------
# Edicion
# ---------------------------------------------------------------------------
def test_edita_nombre_y_roles(cliente, admin, operador):
    entrar(cliente, admin)
    cliente.post(
        f"/admin/usuarios/{operador.id}",
        data={
            "nombre_completo": "Nombre Corregido",
            "email": "corregido@empresa.com",
            "roles": ["OPERADOR", "AGENTE_FIBRA"],
        },
        follow_redirects=True,
    )
    db.session.refresh(operador)
    assert operador.nombre_completo == "Nombre Corregido"
    assert operador.email == "corregido@empresa.com"
    assert operador.roles == {RolUsuario.OPERADOR, RolUsuario.AGENTE_FIBRA}


def test_no_se_queda_sin_roles(cliente, admin, operador):
    entrar(cliente, admin)
    respuesta = cliente.post(
        f"/admin/usuarios/{operador.id}",
        data={"nombre_completo": "Operador", "roles": []},
    )
    assert "al menos un rol" in respuesta.get_data(as_text=True)
    db.session.refresh(operador)
    assert operador.roles == {RolUsuario.OPERADOR}


def test_el_nombre_sigue_siendo_obligatorio(cliente, admin, operador):
    entrar(cliente, admin)
    respuesta = cliente.post(
        f"/admin/usuarios/{operador.id}",
        data={"nombre_completo": "   ", "roles": ["OPERADOR"]},
    )
    assert "obligatorio" in respuesta.get_data(as_text=True)


def test_no_se_desadministra_al_ultimo_admin(cliente, admin):
    entrar(cliente, admin)
    respuesta = cliente.post(
        f"/admin/usuarios/{admin.id}",
        data={"nombre_completo": admin.nombre_completo, "roles": ["OPERADOR"]},
    )
    assert "ultimo admin activo" in respuesta.get_data(as_text=True)
    db.session.refresh(admin)
    assert RolUsuario.ADMIN in admin.roles


def test_con_dos_admins_si_se_puede(cliente, admin):
    otro = crear_usuario("admin2", RolUsuario.ADMIN)
    entrar(cliente, admin)
    cliente.post(
        f"/admin/usuarios/{otro.id}",
        data={"nombre_completo": otro.nombre_completo, "roles": ["OPERADOR"]},
        follow_redirects=True,
    )
    db.session.refresh(otro)
    assert otro.roles == {RolUsuario.OPERADOR}


def test_editar_a_quien_no_existe_da_404(cliente, admin):
    entrar(cliente, admin)
    assert cliente.get("/admin/usuarios/987654").status_code == 404
    assert cliente.post("/admin/usuarios/987654", data={}).status_code == 404


# ---------------------------------------------------------------------------
# Activar y desactivar
# ---------------------------------------------------------------------------
def test_desactiva_y_reactiva(cliente, admin, operador):
    entrar(cliente, admin)
    cliente.post(f"/admin/usuarios/{operador.id}/activar", follow_redirects=True)
    db.session.refresh(operador)
    assert operador.activo is False

    cliente.post(f"/admin/usuarios/{operador.id}/activar", follow_redirects=True)
    db.session.refresh(operador)
    assert operador.activo is True


def test_no_se_desactiva_a_si_mismo(cliente, admin):
    entrar(cliente, admin)
    respuesta = cliente.post(
        f"/admin/usuarios/{admin.id}/activar", follow_redirects=True
    )
    assert "tu propia cuenta" in respuesta.get_data(as_text=True)
    db.session.refresh(admin)
    assert admin.activo is True


def test_no_se_desactiva_al_ultimo_admin(cliente, admin):
    otro_admin = crear_usuario("admin2", RolUsuario.ADMIN)
    entrar(cliente, otro_admin)

    # Con dos admins activos, desactivar a uno se permite.
    cliente.post(f"/admin/usuarios/{admin.id}/activar", follow_redirects=True)
    db.session.refresh(admin)
    assert admin.activo is False

    # Y ahora el que queda no se puede desactivar ni a si mismo ni por otro.
    respuesta = cliente.post(
        f"/admin/usuarios/{otro_admin.id}/activar", follow_redirects=True
    )
    assert "tu propia cuenta" in respuesta.get_data(as_text=True)
    db.session.refresh(otro_admin)
    assert otro_admin.activo is True


def test_activar_a_quien_no_existe_da_404(cliente, admin):
    entrar(cliente, admin)
    assert cliente.post("/admin/usuarios/987654/activar").status_code == 404


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
def test_el_listado_muestra_roles_y_estado(cliente, admin, operador, agente_fibra):
    operador.activo = False
    db.session.commit()

    entrar(cliente, admin)
    cuerpo = cliente.get("/admin/usuarios").get_data(as_text=True)
    for u in (admin, operador, agente_fibra):
        assert u.nombre_completo in cuerpo
    assert RolUsuario.AGENTE_FIBRA.etiqueta in cuerpo
    assert "Inactivo" in cuerpo or "inactivo" in cuerpo

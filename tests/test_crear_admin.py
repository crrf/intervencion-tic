"""`flask crear-admin`: la unica siembra que corresponde en produccion."""
from __future__ import annotations

from app.cli import crear_admin
from app.extensions import db
from app.models.enums import RolUsuario
from app.models.usuario import Usuario
from tests.conftest import crear_usuario

ENTORNO = {
    "ADMIN_USUARIO": "jefe",
    "ADMIN_PASSWORD": "ClaveDeProduccion.1",
    "ADMIN_NOMBRE": "Jefa de Intervencion",
    "ADMIN_EMAIL": "jefe@empresa.com",
}


def ejecutar(app, monkeypatch, *args, **entorno):
    for clave, valor in {**ENTORNO, **entorno}.items():
        monkeypatch.setenv(clave, valor)
    return app.test_cli_runner().invoke(crear_admin, list(args))


def buscar(login):
    return db.session.query(Usuario).filter_by(usuario=login).one_or_none()


def test_crea_solo_al_administrador(app, monkeypatch):
    resultado = ejecutar(app, monkeypatch)

    assert resultado.exit_code == 0
    assert "creado" in resultado.output

    usuarios = db.session.query(Usuario).all()
    assert len(usuarios) == 1, "no debe crear ningun otro usuario"

    jefe = usuarios[0]
    assert jefe.usuario == "jefe"
    assert jefe.nombre_completo == "Jefa de Intervencion"
    assert jefe.email == "jefe@empresa.com"
    assert jefe.roles == {RolUsuario.ADMIN}
    assert jefe.activo
    assert jefe.check_password("ClaveDeProduccion.1")


def test_no_siembra_ningun_ticket(app, monkeypatch):
    from app.models.interrupcion import Interrupcion
    from app.models.orden import OrdenTrabajo

    ejecutar(app, monkeypatch)

    assert db.session.query(OrdenTrabajo).count() == 0
    assert db.session.query(Interrupcion).count() == 0


def test_por_defecto_no_obliga_a_cambiar_la_clave(app, monkeypatch):
    ejecutar(app, monkeypatch)
    assert buscar("jefe").debe_cambiar_password is False


def test_con_forzar_cambio_exige_una_propia(app, monkeypatch):
    """Es lo que usa desplegar.sh, porque el script genera la contrasena."""
    ejecutar(app, monkeypatch, "--forzar-cambio")
    assert buscar("jefe").debe_cambiar_password is True


def test_repetirlo_no_toca_la_contrasena(app, monkeypatch):
    ejecutar(app, monkeypatch)
    buscar("jefe").set_password("LaQueYaCambio.9")
    db.session.commit()

    resultado = ejecutar(app, monkeypatch)

    assert resultado.exit_code == 0
    assert "ya existe" in resultado.output
    assert buscar("jefe").check_password("LaQueYaCambio.9")
    assert db.session.query(Usuario).count() == 1


def test_reactiva_una_cuenta_desactivada(app, monkeypatch):
    ejecutar(app, monkeypatch)
    buscar("jefe").activo = False
    db.session.commit()

    resultado = ejecutar(app, monkeypatch)

    assert "reactivada" in resultado.output
    assert buscar("jefe").activo is True


def test_restituye_el_rol_de_administrador(app, monkeypatch):
    """Rescate: si alguien se quedo sin el rol, el arranque lo devuelve."""
    ejecutar(app, monkeypatch)
    jefe = buscar("jefe")
    jefe.roles = [RolUsuario.OPERADOR]
    db.session.commit()

    resultado = ejecutar(app, monkeypatch)

    assert "rol de administrador restituido" in resultado.output
    assert RolUsuario.ADMIN in buscar("jefe").roles
    assert RolUsuario.OPERADOR in buscar("jefe").roles, "no debe quitarle otros roles"


def test_rechaza_una_contrasena_corta(app, monkeypatch):
    resultado = ejecutar(app, monkeypatch, ADMIN_PASSWORD="corta")

    assert resultado.exit_code != 0
    assert "al menos 8 caracteres" in resultado.output
    assert db.session.query(Usuario).count() == 0


def test_convive_con_otros_usuarios_ya_existentes(app, monkeypatch):
    crear_usuario("operador_previo", RolUsuario.OPERADOR)
    ejecutar(app, monkeypatch)

    assert db.session.query(Usuario).count() == 2
    assert buscar("jefe").roles == {RolUsuario.ADMIN}
    assert buscar("operador_previo").roles == {RolUsuario.OPERADOR}


def test_el_admin_creado_puede_entrar_y_administrar(cliente, app, monkeypatch):
    ejecutar(app, monkeypatch)

    respuesta = cliente.post(
        "/login",
        data={"usuario": "jefe", "password": "ClaveDeProduccion.1"},
        follow_redirects=False,
    )
    assert respuesta.status_code == 302
    assert cliente.get("/admin/usuarios").status_code == 200
    assert cliente.get("/dashboard/").status_code == 200

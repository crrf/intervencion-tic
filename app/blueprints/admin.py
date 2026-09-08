"""Administracion de usuarios y sus roles."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, select

from app.extensions import db
from app.models.enums import RolUsuario
from app.models.usuario import Usuario, UsuarioRol
from app.security.decoradores import rol_requerido
from app.services import usuarios as servicio

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _roles_del_form() -> list[RolUsuario]:
    seleccion = request.form.getlist("roles")
    return [RolUsuario[r.upper()] for r in seleccion if r.upper() in RolUsuario.__members__]


def _admins_activos(excluyendo: int | None = None) -> int:
    consulta = (
        select(func.count(Usuario.id))
        .join(UsuarioRol, UsuarioRol.usuario_id == Usuario.id)
        .where(UsuarioRol.rol == RolUsuario.ADMIN, Usuario.activo.is_(True))
    )
    if excluyendo is not None:
        consulta = consulta.where(Usuario.id != excluyendo)
    return db.session.execute(consulta).scalar_one()


@bp.get("/usuarios")
@rol_requerido(RolUsuario.ADMIN)
def usuarios():
    lista = (
        db.session.execute(select(Usuario).order_by(Usuario.activo.desc(), Usuario.nombre_completo))
        .scalars()
        .unique()
        .all()
    )
    return render_template("admin/usuarios.html", usuarios=lista)


@bp.route("/usuarios/nuevo", methods=["GET", "POST"])
@rol_requerido(RolUsuario.ADMIN)
def nuevo():
    if request.method == "POST":
        login = (request.form.get("usuario") or "").strip()
        nombre = (request.form.get("nombre_completo") or "").strip()
        password = request.form.get("password") or ""
        roles = _roles_del_form()

        error = None
        if not login or not nombre:
            error = "El usuario y el nombre completo son obligatorios."
        elif len(password) < 8:
            error = "La contrasena debe tener al menos 8 caracteres."
        elif not roles:
            error = "Asigna al menos un rol."
        elif db.session.execute(
            select(Usuario).where(Usuario.usuario == login)
        ).scalar_one_or_none():
            error = f"El usuario '{login}' ya existe."

        if error:
            flash(error, "error")
        else:
            u = Usuario(
                usuario=login,
                nombre_completo=nombre,
                email=(request.form.get("email") or "").strip() or None,
                activo=True,
            )
            u.set_password(password)
            u.roles = roles
            db.session.add(u)
            db.session.commit()
            flash(f"Usuario '{login}' creado con roles: {u.etiqueta_roles}", "ok")
            return redirect(url_for("admin.usuarios"))

    return render_template("admin/editar.html", usuario=None, datos=request.form)


@bp.route("/usuarios/<int:usuario_id>", methods=["GET", "POST"])
@rol_requerido(RolUsuario.ADMIN)
def editar(usuario_id: int):
    usuario = db.session.get(Usuario, usuario_id)
    if usuario is None:
        abort(404)

    if request.method == "POST":
        roles = _roles_del_form()
        nombre = (request.form.get("nombre_completo") or "").strip()

        error = None
        if not nombre:
            error = "El nombre completo es obligatorio."
        elif not roles:
            error = "El usuario debe conservar al menos un rol."
        elif (
            RolUsuario.ADMIN in usuario.roles
            and RolUsuario.ADMIN not in roles
            and _admins_activos(excluyendo=usuario.id) == 0
        ):
            error = "No puedes quitar el rol de administrador al ultimo admin activo."

        if error:
            flash(error, "error")
        else:
            usuario.nombre_completo = nombre
            usuario.email = (request.form.get("email") or "").strip() or None
            usuario.roles = roles
            db.session.commit()
            flash("Usuario actualizado.", "ok")
            return redirect(url_for("admin.usuarios"))

    return render_template("admin/editar.html", usuario=usuario, datos=request.form)


@bp.post("/usuarios/<int:usuario_id>/restablecer-password")
@rol_requerido(RolUsuario.ADMIN)
def restablecer_password(usuario_id: int):
    """Asigna una contrasena nueva a cualquier usuario.

    O bien la escribe el administrador, o bien se genera una temporal que se
    muestra una sola vez. En ambos casos el titular queda obligado a cambiarla
    la proxima vez que entre.
    """
    usuario = db.session.get(Usuario, usuario_id)
    if usuario is None:
        abort(404)

    escrita = (request.form.get("password") or "").strip()
    generar = request.form.get("generar") == "1"

    try:
        clave = servicio.restablecer_password(
            usuario, current_user, password=None if generar else escrita
        )
    except servicio.ErrorUsuario as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin.editar", usuario_id=usuario_id))

    if generar:
        flash(
            f"Contrasena temporal de '{usuario.usuario}': {clave} "
            f"— anotala ahora, no se vuelve a mostrar.",
            "ok",
        )
    else:
        flash(f"Contrasena de '{usuario.usuario}' restablecida.", "ok")

    if usuario.id != current_user.id:
        flash(
            f"{usuario.nombre_completo} debera fijar una contrasena nueva al entrar.",
            "aviso",
        )
    return redirect(url_for("admin.editar", usuario_id=usuario_id))


@bp.post("/usuarios/<int:usuario_id>/activar")
@rol_requerido(RolUsuario.ADMIN)
def activar(usuario_id: int):
    usuario = db.session.get(Usuario, usuario_id)
    if usuario is None:
        abort(404)
    if usuario.id == current_user.id:
        flash("No puedes desactivar tu propia cuenta.", "error")
        return redirect(url_for("admin.usuarios"))
    if (
        usuario.activo
        and RolUsuario.ADMIN in usuario.roles
        and _admins_activos(excluyendo=usuario.id) == 0
    ):
        flash("No puedes desactivar al ultimo administrador activo.", "error")
        return redirect(url_for("admin.usuarios"))

    usuario.activo = not usuario.activo
    db.session.commit()
    flash(
        f"Usuario '{usuario.usuario}' {'activado' if usuario.activo else 'desactivado'}.", "ok"
    )
    return redirect(url_for("admin.usuarios"))

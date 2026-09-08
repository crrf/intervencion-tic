"""Fabrica de la aplicacion Flask."""
from __future__ import annotations

import logging

from flask import Flask, jsonify, render_template, request
from flask_login import current_user

from app.config import obtener_config
from app.extensions import csrf, db, limiter, login_manager, migrate


def create_app(nombre_config: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(obtener_config(nombre_config))

    _configurar_logging(app)
    _iniciar_extensiones(app)
    _registrar_blueprints(app)
    _registrar_filtros(app)
    _registrar_contexto(app)
    _registrar_guardias(app)
    _registrar_errores(app)

    @app.get("/salud")
    def salud():  # noqa: ANN202
        return jsonify(estado="ok"), 200

    return app


def _configurar_logging(app: Flask) -> None:
    nivel = getattr(logging, app.config["LOG_LEVEL"].upper(), logging.INFO)
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    app.logger.setLevel(nivel)


def _iniciar_extensiones(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from app.models.usuario import Usuario  # noqa: F401  (registra el modelo)

    @login_manager.user_loader
    def cargar_usuario(user_id: str):  # noqa: ANN202
        return db.session.get(Usuario, int(user_id))

    from app import cli

    cli.registrar(app)


def _registrar_blueprints(app: Flask) -> None:
    from app.blueprints.admin import bp as bp_admin
    from app.blueprints.adjuntos import bp as bp_adjuntos
    from app.blueprints.auth import bp as bp_auth
    from app.blueprints.buscar import bp as bp_buscar
    from app.blueprints.dashboard import bp as bp_dashboard
    from app.blueprints.fibra import bp as bp_fibra
    from app.blueprints.interrupciones import bp as bp_interrupciones
    from app.blueprints.notificaciones import bp as bp_notificaciones
    from app.blueprints.ordenes import bp as bp_ordenes
    from app.blueprints.reportes import bp as bp_reportes
    from app.blueprints.tablero import bp as bp_tablero

    for bp in (
        bp_auth,
        bp_tablero,
        bp_ordenes,
        bp_interrupciones,
        bp_fibra,
        bp_adjuntos,
        bp_buscar,
        bp_reportes,
        bp_dashboard,
        bp_notificaciones,
        bp_admin,
    ):
        app.register_blueprint(bp)


def _registrar_filtros(app: Flask) -> None:
    from app.models.enums import COLORES_ESTADO, COLORES_PRIORIDAD
    from app.services.consultas import formatear_duracion, zona_app

    @app.template_filter("fecha")
    def _fecha(valor, formato: str = "%d/%m/%Y %H:%M"):
        if not valor:
            return "-"
        return valor.astimezone(zona_app()).strftime(formato)

    @app.template_filter("fecha_corta")
    def _fecha_corta(valor):
        return _fecha(valor, "%d/%m %H:%M")

    @app.template_filter("duracion")
    def _duracion(minutos):
        return formatear_duracion(minutos)

    @app.template_filter("color_estado")
    def _color_estado(estado):
        nombre = getattr(estado, "name", estado)
        return COLORES_ESTADO.get(nombre, "gris")

    @app.template_filter("color_prioridad")
    def _color_prioridad(prioridad):
        nombre = getattr(prioridad, "name", prioridad)
        return COLORES_PRIORIDAD.get(nombre, "gris")

    @app.template_filter("nl2br")
    def _nl2br(texto):
        from markupsafe import Markup, escape

        if not texto:
            return ""
        return Markup("<br>".join(escape(texto).split("\n")))


def _registrar_contexto(app: Flask) -> None:
    from app.models.enums import (
        Dependencia,
        EstadoFibra,
        EstadoInterrupcion,
        EstadoOrden,
        Prioridad,
        RolUsuario,
        TipoTicket,
    )
    from app.security.decoradores import puede_gestionar
    from app.services import notificaciones as notif

    @app.context_processor
    def _inyectar():
        sin_leer = 0
        solo_fibra = False
        if current_user.is_authenticated:
            sin_leer = notif.contar_no_leidas(current_user.id)
            solo_fibra = current_user.roles == {RolUsuario.AGENTE_FIBRA}
        return {
            "RolUsuario": RolUsuario,
            "TipoTicket": TipoTicket,
            "EstadoOrden": EstadoOrden,
            "EstadoInterrupcion": EstadoInterrupcion,
            "EstadoFibra": EstadoFibra,
            "Dependencia": Dependencia,
            "Prioridad": Prioridad,
            "notificaciones_sin_leer": sin_leer,
            "solo_fibra": solo_fibra,
            "puede_gestionar": puede_gestionar,
        }


def _registrar_guardias(app: Flask) -> None:
    """Quien tiene la contrasena restablecida por un admin no puede navegar
    hasta que fije una nueva."""
    from flask import flash, redirect, request as peticion, url_for

    #: Lo unico accesible mientras la contrasena esta marcada para cambio.
    PERMITIDOS = {"auth.cuenta", "auth.login", "auth.logout", "static", "salud"}

    @app.before_request
    def _exigir_cambio_de_password():  # noqa: ANN202
        if not current_user.is_authenticated:
            return None
        if not getattr(current_user, "debe_cambiar_password", False):
            return None
        if peticion.endpoint in PERMITIDOS or peticion.endpoint is None:
            return None
        if peticion.headers.get("HX-Request") == "true":
            return "Debes fijar una contrasena nueva antes de continuar.", 403
        flash(
            "Un administrador restablecio tu contrasena. Fija una nueva para continuar.",
            "aviso",
        )
        return redirect(url_for("auth.cuenta"))


def _registrar_errores(app: Flask) -> None:
    def _es_htmx() -> bool:
        return request.headers.get("HX-Request") == "true"

    @app.errorhandler(403)
    def _403(error):  # noqa: ANN202
        if _es_htmx():
            return "No tienes permiso para esta accion.", 403
        return render_template("error.html", codigo=403,
                               titulo="Sin permiso",
                               mensaje="Tu perfil no tiene acceso a esta seccion."), 403

    @app.errorhandler(404)
    def _404(error):  # noqa: ANN202
        if _es_htmx():
            return "No se encontro el recurso.", 404
        return render_template("error.html", codigo=404,
                               titulo="No encontrado",
                               mensaje="La pagina o el ticket que buscas no existe."), 404

    @app.errorhandler(413)
    def _413(error):  # noqa: ANN202
        mensaje = "El archivo supera el tamano maximo permitido."
        if _es_htmx():
            return mensaje, 413
        return render_template("error.html", codigo=413,
                               titulo="Archivo demasiado grande",
                               mensaje=mensaje), 413

    @app.errorhandler(500)
    def _500(error):  # noqa: ANN202
        db.session.rollback()
        app.logger.exception("error no controlado")
        if _es_htmx():
            return "Ocurrio un error inesperado.", 500
        return render_template("error.html", codigo=500,
                               titulo="Error interno",
                               mensaje="Ocurrio un error inesperado. Ya quedo registrado."), 500

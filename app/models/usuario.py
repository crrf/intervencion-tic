"""Usuarios y sus roles (un usuario puede tener varios roles a la vez)."""
from __future__ import annotations

from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import Enum as SAEnum
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.enums import RolUsuario


class UsuarioRol(db.Model):
    """Tabla puente usuario <-> rol. Sustituye a una columna `rol` unica."""

    __tablename__ = "usuario_rol"

    usuario_id = db.Column(
        db.Integer, db.ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True
    )
    rol = db.Column(SAEnum(RolUsuario, name="rol_usuario"), primary_key=True)


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuario"

    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(60), unique=True, nullable=False, index=True)
    nombre_completo = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(160))
    password_hash = db.Column(db.String(255), nullable=False)
    activo = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("true"))
    # Lo activa un restablecimiento hecho por un administrador: obliga al
    # titular a fijar una clave nueva antes de poder usar el sistema.
    debe_cambiar_password = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.text("false")
    )
    creado_en = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    _roles = db.relationship(
        "UsuarioRol",
        backref="usuario_obj",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # --- Contrasena --------------------------------------------------------
    def set_password(self, texto: str) -> None:
        self.password_hash = generate_password_hash(texto)

    def check_password(self, texto: str) -> bool:
        return check_password_hash(self.password_hash, texto)

    # --- Roles -------------------------------------------------------------
    @property
    def roles(self) -> set[RolUsuario]:
        return {r.rol for r in self._roles}

    @roles.setter
    def roles(self, nuevos) -> None:
        deseados = {r if isinstance(r, RolUsuario) else RolUsuario[str(r).upper()] for r in nuevos}
        actuales = {r.rol for r in self._roles}
        for fila in list(self._roles):
            if fila.rol not in deseados:
                self._roles.remove(fila)
        for rol in deseados - actuales:
            self._roles.append(UsuarioRol(rol=rol))

    def tiene_rol(self, rol) -> bool:
        if isinstance(rol, str):
            rol = RolUsuario.desde_nombre(rol)
        return rol in self.roles

    def tiene_alguno(self, *roles) -> bool:
        return any(self.tiene_rol(r) for r in roles)

    @property
    def es_admin(self) -> bool:
        return self.tiene_rol(RolUsuario.ADMIN)

    @property
    def es_despachador(self) -> bool:
        return self.tiene_rol(RolUsuario.DESPACHADOR)

    @property
    def es_operador(self) -> bool:
        return self.tiene_rol(RolUsuario.OPERADOR)

    @property
    def es_agente_fibra(self) -> bool:
        return self.tiene_rol(RolUsuario.AGENTE_FIBRA)

    @property
    def roles_ordenados(self) -> list[RolUsuario]:
        orden = list(RolUsuario)
        return sorted(self.roles, key=orden.index)

    @property
    def etiqueta_roles(self) -> str:
        return ", ".join(r.etiqueta for r in self.roles_ordenados)

    @property
    def etiqueta_asignacion(self) -> str:
        """Nombre para los selectores de asignacion.

        Avisa cuando el destinatario es tecnico de wifi y no operador, porque
        a el solo se le pueden entregar interrupciones de sitio wifi.
        """
        if self.tiene_rol(RolUsuario.TECNICO_WIFI) and not self.tiene_rol(RolUsuario.OPERADOR):
            return f"{self.nombre_completo} (tecnico de wifi)"
        return self.nombre_completo

    @property
    def iniciales(self) -> str:
        partes = [p for p in self.nombre_completo.split() if p]
        return "".join(p[0] for p in partes[:2]).upper() or self.usuario[:2].upper()

    # Flask-Login: un usuario desactivado no puede iniciar sesion.
    @property
    def is_active(self) -> bool:  # noqa: D401
        return bool(self.activo)

    def __repr__(self) -> str:
        return f"<Usuario {self.usuario} [{self.etiqueta_roles}]>"

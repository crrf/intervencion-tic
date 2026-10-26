"""Comandos de consola: `flask seed`, `flask crear-usuario`, `flask storage-check`."""
from __future__ import annotations

import io
import os
import random
from datetime import datetime, timedelta, timezone

import click
from flask import Flask
from flask.cli import with_appcontext

from app.extensions import db
from app.models.comentario import Comentario
from app.models.contador import siguiente_folio
from app.models.enums import (
    CategoriaInterrupcion,
    Dependencia,
    EstadoFibra,
    EstadoInterrupcion,
    EstadoOrden,
    Prioridad,
    RolUsuario,
    TipoTicket,
)
from app.models.historial import Historial
from app.models.interrupcion import Interrupcion
from app.models.orden import OrdenTrabajo
from app.models.usuario import Usuario
from app.services import storage

CLIENTES = [
    "Corporacion Andina C.A.", "Clinica San Rafael", "Alcaldia de Valle Verde",
    "Supermercados La Guaira", "Banco del Sur - Agencia Centro", "Liceo Bolivariano Norte",
    "Hotel Mirador", "Distribuidora El Progreso", "Radio Continental FM",
    "Fabrica de Cemento Los Andes", "Universidad Tecnologica", "Farmacias Vida",
    "Terminal de Pasajeros", "Hospital Materno Infantil", "Textiles del Caribe",
]

TITULOS_ORDEN = [
    "Instalacion de nuevo enlace de fibra",
    "Ampliacion de ancho de banda",
    "Migracion de puerto en OLT",
    "Reubicacion de acometida",
    "Cambio de ONT por falla",
    "Tendido de fibra para sede nueva",
    "Certificacion de enlace dedicado",
]

TITULOS_INTERRUPCION = [
    "Perdida total de servicio",
    "Intermitencia en el enlace principal",
    "Alta latencia hacia el core",
    "Caida de enlace redundante",
    "Degradacion de potencia optica",
    "Servicio caido tras corte electrico",
    "Enlace inestable desde la madrugada",
]

TELEFONOS = [
    "0414-1234567", "0412-9876543", "0424-5551234", "0416-3334455",
    "0212-7778899", None, None,  # algunos quedan sin telefono, como en la vida real
]

DIRECCIONES = [
    "Av. Bolivar con calle 5, edificio Centro, piso 2, local 2-A",
    "Calle Sucre, casa 14, frente a la plaza",
    "Urbanizacion El Parral, vereda 3, casa 27",
    "Av. Las Delicias, centro comercial Paseo, local 112",
    "Sector La Romana, calle principal, galpon 8",
    "Carretera nacional km 12, entrada de Tocuyito",
    None, None,  # algunos quedan sin direccion, como en la vida real
]

MOTIVOS = [
    "Cliente no permitio el acceso al sitio.",
    "Falta material en almacen para completar el trabajo.",
    "Se requiere permiso de via para la cuadrilla.",
    "Pendiente energia en el nodo.",
]

COMENTARIOS_CIERRE = [
    "Se realizo empalme y se certifico el enlace. Servicio operativo.",
    "Se reemplazo el equipo terminal y se valido con el cliente.",
    "Se reconfiguro el puerto y el servicio quedo estable.",
    "Se restablecio el servicio tras normalizar la energia del nodo.",
]


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _imagen(texto: str, color: tuple[int, int, int]) -> bytes:
    """Genera una imagen de relleno para los datos semilla."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (900, 600), color)
    dibujo = ImageDraw.Draw(img)
    dibujo.rectangle([20, 20, 880, 580], outline=(255, 255, 255), width=4)
    dibujo.text((60, 280), texto, fill=(255, 255, 255))
    salida = io.BytesIO()
    img.save(salida, format="JPEG", quality=80)
    return salida.getvalue()


def registrar(app: Flask) -> None:
    app.cli.add_command(seed)
    app.cli.add_command(crear_admin)
    app.cli.add_command(crear_usuario)
    app.cli.add_command(storage_check)


# ---------------------------------------------------------------------------
@click.command("crear-admin")
@click.option(
    "--forzar-cambio",
    is_flag=True,
    help="Obliga al administrador a fijar una contrasena propia al entrar.",
)
@with_appcontext
def crear_admin(forzar_cambio: bool) -> None:
    """Crea unicamente la cuenta de administrador, sin datos de ejemplo.

    Es lo que se usa en produccion: la base arranca vacia y el resto de los
    usuarios los crea el propio administrador desde la aplicacion.

    Es idempotente: si la cuenta ya existe no toca su contrasena, solo se
    asegura de que siga activa y con el rol de administrador.
    """
    login = os.environ.get("ADMIN_USUARIO", "admin").strip()
    existente = db.session.query(Usuario).filter_by(usuario=login).one_or_none()

    if existente is not None:
        cambios = []
        if not existente.activo:
            existente.activo = True
            cambios.append("reactivada")
        if RolUsuario.ADMIN not in existente.roles:
            existente.roles = existente.roles | {RolUsuario.ADMIN}
            cambios.append("rol de administrador restituido")
        if cambios:
            db.session.commit()
            click.echo(f"Cuenta '{login}' ya existia: {', '.join(cambios)}.")
        else:
            click.echo(f"Cuenta '{login}' ya existe y esta correcta. No se toca su contrasena.")
        return

    password = os.environ.get("ADMIN_PASSWORD", "")
    if len(password) < 8:
        raise click.ClickException(
            "ADMIN_PASSWORD debe tener al menos 8 caracteres para crear la cuenta."
        )

    u = Usuario(
        usuario=login,
        nombre_completo=os.environ.get("ADMIN_NOMBRE", "Administrador del Sistema"),
        email=os.environ.get("ADMIN_EMAIL") or None,
        activo=True,
        debe_cambiar_password=forzar_cambio,
    )
    u.set_password(password)
    u.roles = [RolUsuario.ADMIN]
    db.session.add(u)
    db.session.commit()

    click.echo(f"Administrador '{login}' creado.")
    if forzar_cambio:
        click.echo("Debera fijar una contrasena propia en su primer ingreso.")


# ---------------------------------------------------------------------------
@click.command("seed")
@with_appcontext
def seed() -> None:
    """Crea usuarios y tickets de ejemplo. Es idempotente."""
    if db.session.query(Usuario.id).first():
        click.echo("Ya existen usuarios: no se siembra nada.")
        return

    random.seed(20260907)
    clave = os.environ.get("SEED_PASSWORD", "Clave.2026")

    def _usuario(login, nombre, roles, password=None):
        u = Usuario(
            usuario=login,
            nombre_completo=nombre,
            email=f"{login}@intervencion.local",
            activo=True,
        )
        u.set_password(password or clave)
        u.roles = roles
        db.session.add(u)
        return u

    admin = _usuario(
        os.environ.get("ADMIN_USUARIO", "admin"),
        os.environ.get("ADMIN_NOMBRE", "Administrador del Sistema"),
        [RolUsuario.ADMIN],
        os.environ.get("ADMIN_PASSWORD", clave),
    )
    admin.email = os.environ.get("ADMIN_EMAIL", "admin@intervencion.local")

    despachador = _usuario("despachador1", "Marisol Peña", [RolUsuario.DESPACHADOR])
    operador1 = _usuario("operador1", "Luis Bermudez", [RolUsuario.OPERADOR])
    operador2 = _usuario("operador2", "Carmen Delgado", [RolUsuario.OPERADOR])
    operador3 = _usuario("operador3", "Jose Ramirez", [RolUsuario.OPERADOR])
    fibra1 = _usuario("fibra1", "Ana Quintero", [RolUsuario.AGENTE_FIBRA])
    fibra2 = _usuario("fibra2", "Pedro Salazar", [RolUsuario.AGENTE_FIBRA])
    wifi1 = _usuario("wifi1", "Daniela Fuentes", [RolUsuario.TECNICO_WIFI])
    # Caso clave: un mismo usuario con dos roles.
    mixto = _usuario(
        "mixto1", "Rafael Ochoa", [RolUsuario.DESPACHADOR, RolUsuario.OPERADOR]
    )
    db.session.flush()

    operadores = [operador1, operador2, operador3, mixto]
    tecnicos_wifi = [wifi1]
    agentes = [fibra1, fibra2]
    despachadores = [despachador, mixto]

    click.echo("Subiendo imagenes de ejemplo al object storage...")
    try:
        storage.asegurar_bucket()
        base = {
            "anverso": _imagen("ORDEN DE TRABAJO - ANVERSO", (31, 78, 121)),
            "reverso": _imagen("ORDEN DE TRABAJO - REVERSO", (68, 114, 196)),
            "foto": _imagen("REPORTE DE INTERRUPCION", (146, 43, 33)),
        }
    except Exception as exc:  # noqa: BLE001
        click.echo(f"AVISO: no se pudo preparar el storage ({exc}). Se siembra sin fotos.")
        base = None

    def _subir(clave_objeto: str, cual: str) -> str:
        if base is None:
            return f"demo/{cual}.jpg"
        storage.subir(clave_objeto, base[cual], "jpg")
        return clave_objeto

    def _hist(ticket, usuario, campo, anterior, nuevo, cuando):
        fk = (
            {"orden_id": ticket.id}
            if isinstance(ticket, OrdenTrabajo)
            else {"interrupcion_id": ticket.id}
        )
        db.session.add(
            Historial(
                usuario_id=usuario.id,
                campo=campo,
                valor_anterior=anterior,
                valor_nuevo=nuevo,
                creado_en=cuando,
                **fk,
            )
        )

    def _coment(ticket, usuario, texto, cuando):
        fk = (
            {"orden_id": ticket.id}
            if isinstance(ticket, OrdenTrabajo)
            else {"interrupcion_id": ticket.id}
        )
        db.session.add(
            Comentario(autor_id=usuario.id, texto=texto, creado_en=cuando, **fk)
        )

    ahora = _ahora()
    total_ordenes, total_inter = 0, 0

    # ---------------- Ordenes de trabajo -----------------------------------
    for i in range(22):
        creado = ahora - timedelta(days=random.randint(0, 59), hours=random.randint(0, 20))
        folio = siguiente_folio(TipoTicket.ORDEN, creado.year)
        creador = random.choice(despachadores)
        orden = OrdenTrabajo(
            folio=folio,
            identificador_externo=f"ED{random.randint(100000, 999999)}",
            nombre_cliente=random.choice(CLIENTES),
            telefono_contacto=random.choice(TELEFONOS),
            direccion=random.choice(DIRECCIONES),
            titulo=random.choice(TITULOS_ORDEN),
            descripcion="Trabajo programado reportado por el centro de gestion.",
            prioridad=random.choice(list(Prioridad)),
            estado=EstadoOrden.NUEVA,
            creado_por_id=creador.id,
            creado_en=creado,
            foto_anverso_key=_subir(f"ordenes/{folio}/anverso.jpg", "anverso"),
            foto_reverso_key=_subir(f"ordenes/{folio}/reverso.jpg", "reverso"),
        )
        db.session.add(orden)
        db.session.flush()
        _hist(orden, creador, "estado", None, EstadoOrden.NUEVA.etiqueta, creado)

        camino = random.choices(
            ["nueva", "asignada", "proceso", "motivo", "ok", "cerrada"],
            weights=[8, 12, 18, 17, 12, 33],
        )[0]
        if camino == "nueva":
            total_ordenes += 1
            continue

        operador = random.choice(operadores)
        t_asig = creado + timedelta(hours=random.randint(1, 8))
        orden.asignado_a_id, orden.asignado_en = operador.id, t_asig
        orden.estado = EstadoOrden.ASIGNADA
        _hist(orden, creador, "asignado_a", None, operador.nombre_completo, t_asig)
        _hist(orden, creador, "estado", EstadoOrden.NUEVA.etiqueta,
              EstadoOrden.ASIGNADA.etiqueta, t_asig)
        if camino == "asignada":
            total_ordenes += 1
            continue

        t_proc = t_asig + timedelta(hours=random.randint(1, 12))
        orden.estado = EstadoOrden.EN_PROCESO
        _hist(orden, operador, "estado", EstadoOrden.ASIGNADA.etiqueta,
              EstadoOrden.EN_PROCESO.etiqueta, t_proc)
        if camino == "proceso":
            total_ordenes += 1
            continue

        t_fin = t_proc + timedelta(hours=random.randint(2, 60))
        if t_fin > ahora:
            t_fin = ahora - timedelta(minutes=30)
        if camino == "motivo":
            orden.estado = EstadoOrden.ABIERTA_CON_MOTIVO
            orden.motivo_apertura = random.choice(MOTIVOS)
            _coment(orden, operador, orden.motivo_apertura, t_fin)
            _hist(orden, operador, "estado", EstadoOrden.EN_PROCESO.etiqueta,
                  EstadoOrden.ABIERTA_CON_MOTIVO.etiqueta, t_fin)
            total_ordenes += 1
            continue

        # El operador solo da su OK; el cierre en SIPREC lo hace despues el
        # despachador.
        orden.estado = EstadoOrden.OK_OPERADOR
        _coment(orden, operador, random.choice(COMENTARIOS_CIERRE), t_fin)
        _hist(orden, operador, "estado", EstadoOrden.EN_PROCESO.etiqueta,
              EstadoOrden.OK_OPERADOR.etiqueta, t_fin)
        if camino == "ok":
            total_ordenes += 1
            continue

        t_cierre = t_fin + timedelta(hours=random.randint(1, 20))
        if t_cierre > ahora:
            t_cierre = ahora - timedelta(minutes=10)
        orden.estado = EstadoOrden.CERRADA
        orden.cerrado_en = t_cierre
        _coment(orden, creador, "Cierre registrado en SIPREC.", t_cierre)
        _hist(orden, creador, "estado", EstadoOrden.OK_OPERADOR.etiqueta,
              EstadoOrden.CERRADA.etiqueta, t_cierre)
        total_ordenes += 1

    # ---------------- Interrupciones ---------------------------------------
    for i in range(26):
        creado = ahora - timedelta(days=random.randint(0, 59), hours=random.randint(0, 20))
        folio = siguiente_folio(TipoTicket.INTERRUPCION, creado.year)
        creador = random.choice(despachadores)
        categoria = random.choices(
            [CategoriaInterrupcion.ENLACE_CLIENTE, CategoriaInterrupcion.SITIO_WIFI],
            weights=[75, 25],
        )[0]
        inter = Interrupcion(
            folio=folio,
            identificador_externo=f"FD{random.randint(100000, 999999)}",
            nombre_cliente=random.choice(CLIENTES),
            telefono_contacto=random.choice(TELEFONOS),
            direccion=random.choice(DIRECCIONES),
            titulo=random.choice(TITULOS_INTERRUPCION),
            descripcion="Reportado por el cliente y confirmado por monitoreo.",
            prioridad=random.choice(list(Prioridad)),
            estado=EstadoInterrupcion.NUEVA,
            categoria=categoria,
            creado_por_id=creador.id,
            creado_en=creado,
            foto_key=_subir(f"interrupciones/{folio}/foto.jpg", "foto"),
        )
        db.session.add(inter)
        db.session.flush()
        _hist(inter, creador, "estado", None, EstadoInterrupcion.NUEVA.etiqueta, creado)

        camino = random.choices(
            ["nueva", "asignada", "proceso", "fibra", "motivo", "cerrada"],
            weights=[7, 10, 13, 22, 12, 36],
        )[0]
        if camino == "nueva":
            total_inter += 1
            continue

        if categoria is CategoriaInterrupcion.SITIO_WIFI and random.random() < 0.75:
            operador = random.choice(tecnicos_wifi)
        else:
            operador = random.choice(operadores)
        t_asig = creado + timedelta(minutes=random.randint(10, 240))
        inter.asignado_a_id, inter.asignado_en = operador.id, t_asig
        inter.estado = EstadoInterrupcion.ASIGNADA
        _hist(inter, creador, "asignado_a", None, operador.nombre_completo, t_asig)
        _hist(inter, creador, "estado", EstadoInterrupcion.NUEVA.etiqueta,
              EstadoInterrupcion.ASIGNADA.etiqueta, t_asig)
        if camino == "asignada":
            total_inter += 1
            continue

        t_proc = t_asig + timedelta(minutes=random.randint(15, 180))
        inter.estado = EstadoInterrupcion.EN_PROCESO
        _hist(inter, operador, "estado", EstadoInterrupcion.ASIGNADA.etiqueta,
              EstadoInterrupcion.EN_PROCESO.etiqueta, t_proc)
        if camino == "proceso":
            total_inter += 1
            continue

        dependencia = (
            Dependencia.CAPA_FISICA
            if camino == "fibra"
            else random.choice([Dependencia.CORE_IPMPLS, Dependencia.DISTRIBUCION,
                                Dependencia.CAPA_FISICA])
        )
        t_diag = t_proc + timedelta(minutes=random.randint(20, 200))
        inter.dependencia = dependencia
        _hist(inter, operador, "dependencia", None, dependencia.etiqueta, t_diag)

        if camino == "fibra":
            inter.estado = EstadoInterrupcion.DERIVADA_FIBRA
            inter.derivado_fibra_en = t_diag
            inter.estado_fibra = EstadoFibra.EN_REVISION
            _coment(inter, operador,
                    "Se descarto equipo activo. Se presume corte en el tramo de fibra.", t_diag)
            _hist(inter, operador, "estado", EstadoInterrupcion.EN_PROCESO.etiqueta,
                  EstadoInterrupcion.DERIVADA_FIBRA.etiqueta, t_diag)

            if random.random() < 0.7:  # la mayoria ya tiene respuesta de fibra
                agente = random.choice(agentes)
                t_fib = t_diag + timedelta(minutes=random.randint(30, 400))
                resultado = random.choice(
                    [EstadoFibra.FIBRA_OK, EstadoFibra.FIBRA_CON_FALLA, EstadoFibra.FIBRA_CON_FALLA]
                )
                inter.estado_fibra = resultado
                inter.agente_fibra_id = agente.id
                inter.respuesta_fibra_en = t_fib
                texto = (
                    "Tramo medido con OTDR sin novedad; la fibra esta en buen estado."
                    if resultado is EstadoFibra.FIBRA_OK
                    else "Corte confirmado en el tramo aereo. Cuadrilla en sitio para el empalme."
                )
                _coment(inter, agente, texto, t_fib)
                _hist(inter, agente, "estado_fibra", EstadoFibra.EN_REVISION.etiqueta,
                      resultado.etiqueta, t_fib)

                if random.random() < 0.5:  # y una parte ya la cerro el operador
                    t_cierre = t_fib + timedelta(minutes=random.randint(20, 300))
                    if t_cierre < ahora:
                        inter.estado = EstadoInterrupcion.CERRADA
                        inter.cerrado_en = t_cierre
                        _coment(inter, operador, random.choice(COMENTARIOS_CIERRE), t_cierre)
                        _hist(inter, operador, "estado",
                              EstadoInterrupcion.DERIVADA_FIBRA.etiqueta,
                              EstadoInterrupcion.CERRADA.etiqueta, t_cierre)
        elif camino == "motivo":
            inter.estado = EstadoInterrupcion.ABIERTA_OTRO_MOTIVO
            inter.motivo_apertura = random.choice(MOTIVOS)
            _coment(inter, operador, inter.motivo_apertura, t_diag)
            _hist(inter, operador, "estado", EstadoInterrupcion.EN_PROCESO.etiqueta,
                  EstadoInterrupcion.ABIERTA_OTRO_MOTIVO.etiqueta, t_diag)
        else:
            t_cierre = min(t_diag + timedelta(minutes=random.randint(30, 500)),
                           ahora - timedelta(minutes=15))
            inter.estado = EstadoInterrupcion.CERRADA
            inter.cerrado_en = t_cierre
            _coment(inter, operador, random.choice(COMENTARIOS_CIERRE), t_cierre)
            _hist(inter, operador, "estado", EstadoInterrupcion.EN_PROCESO.etiqueta,
                  EstadoInterrupcion.CERRADA.etiqueta, t_cierre)
        total_inter += 1

    db.session.commit()
    click.echo(
        f"Sembrados 9 usuarios, {total_ordenes} ordenes y {total_inter} interrupciones."
    )
    click.echo(f"Ingresa como '{admin.usuario}' con la contrasena de ADMIN_PASSWORD.")
    click.echo(f"Los demas usuarios usan la contrasena de SEED_PASSWORD ({clave}).")


# ---------------------------------------------------------------------------
@click.command("crear-usuario")
@click.option("--usuario", prompt=True)
@click.option("--nombre", prompt="Nombre completo")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option(
    "--rol",
    "roles",
    multiple=True,
    required=True,
    type=click.Choice([r.name for r in RolUsuario], case_sensitive=False),
    help="Se puede repetir para asignar varios roles.",
)
@click.option("--email", default=None)
@with_appcontext
def crear_usuario(usuario, nombre, password, roles, email) -> None:
    """Crea un usuario con uno o varios roles."""
    if db.session.query(Usuario).filter_by(usuario=usuario).first():
        raise click.ClickException(f"El usuario '{usuario}' ya existe.")
    u = Usuario(usuario=usuario, nombre_completo=nombre, email=email, activo=True)
    u.set_password(password)
    u.roles = [RolUsuario[r.upper()] for r in roles]
    db.session.add(u)
    db.session.commit()
    click.echo(f"Usuario '{usuario}' creado con roles: {u.etiqueta_roles}")


# ---------------------------------------------------------------------------
@click.command("storage-check")
@with_appcontext
def storage_check() -> None:
    """Verifica de punta a punta el acceso al object storage."""
    clave = "diagnostico/prueba.txt"
    storage.asegurar_bucket()
    storage.subir(clave, b"ok", "txt")
    url = storage.url_prefirmada(clave, 60)
    existe = storage.existe(clave)
    storage.eliminar(clave)
    click.echo(f"bucket accesible: si\nobjeto escrito y leido: {existe}\nURL firmada: {url}")

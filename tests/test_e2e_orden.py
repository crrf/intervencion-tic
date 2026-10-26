"""Recorrido completo de una orden de trabajo por HTTP, como en pantalla.

Nada de llamar a los servicios por dentro: aqui se entra con usuario y
contrasena, se envian los formularios y se comprueba lo que ve cada perfil y
lo que queda en la base. Es la prueba que habria cazado el fallo de la
asignacion al crear.
"""
from __future__ import annotations

import io

from sqlalchemy import select

from app.extensions import db
from app.models.enums import EstadoOrden
from app.models.orden import OrdenTrabajo
from app.services import notificaciones as notif
from tests.conftest import imagen_jpeg

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    respuesta = cliente.post(
        "/login", data={"usuario": usuario.usuario, "password": CLAVE}
    )
    assert respuesta.status_code == 302, "el login deberia redirigir"
    return respuesta


def salir(cliente):
    cliente.get("/logout")


def foto(nombre="a.jpg"):
    return (io.BytesIO(imagen_jpeg()), nombre)


def crear_orden_por_formulario(cliente, **extra):
    datos = {
        "identificador_externo": "ED445566",
        "nombre_cliente": "Panaderia La Espiga",
        "telefono_contacto": "0414-1234567",
        "titulo": "Instalacion de enlace dedicado",
        "descripcion": "El cliente contrato 50 Mbps simetricos.",
        "prioridad": "ALTA",
        "foto_anverso": foto("anverso.jpg"),
        "foto_reverso": foto("reverso.jpg"),
    }
    datos.update(extra)
    return cliente.post(
        "/ordenes/nueva", data=datos, content_type="multipart/form-data",
        follow_redirects=True,
    )


def mover(cliente, orden, clave, **datos):
    return cliente.post(
        f"/ordenes/{orden.id}/mover", data={"transicion": clave, **datos},
        follow_redirects=True,
    )


def buscar_orden(identificador="ED445566") -> OrdenTrabajo:
    return db.session.execute(
        select(OrdenTrabajo).where(OrdenTrabajo.identificador_externo == identificador)
    ).scalar_one()


# ---------------------------------------------------------------------------
# El recorrido completo
# ---------------------------------------------------------------------------
def test_de_la_creacion_al_cierre_en_siprec(cliente, despachador, operador, admin):
    # --- El despachador la crea -------------------------------------------
    entrar(cliente, despachador)
    assert cliente.get("/ordenes/nueva").status_code == 200

    respuesta = crear_orden_por_formulario(cliente)
    assert respuesta.status_code == 200
    assert "creada" in respuesta.get_data(as_text=True)

    orden = buscar_orden()
    assert orden.estado is EstadoOrden.NUEVA
    assert orden.creado_por_id == despachador.id
    assert orden.foto_anverso_key and orden.foto_reverso_key
    assert orden.telefono_contacto == "0414-1234567"
    assert orden.folio.startswith("OT-")

    # --- Y la asigna -------------------------------------------------------
    detalle = cliente.get(orden.url_detalle).get_data(as_text=True)
    assert "Asignar a un operador" in detalle

    mover(cliente, orden, "estado:ASIGNADA", asignado_a_id=str(operador.id))
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.ASIGNADA
    assert orden.asignado_a_id == operador.id
    assert orden.asignado_en is not None
    assert notif.contar_no_leidas(operador.id) == 1
    salir(cliente)

    # --- El operador la trabaja -------------------------------------------
    entrar(cliente, operador)
    tablero = cliente.get("/tablero?tipo=ordenes").get_data(as_text=True)
    assert orden.folio in tablero
    assert "Tomar / iniciar trabajo" in tablero

    mover(cliente, orden, "estado:EN_PROCESO")
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.EN_PROCESO

    # No puede cerrarla: solo dar el OK.
    sin_permiso = mover(cliente, orden, "estado:CERRADA", comentario="ya esta")
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.EN_PROCESO, "el operador no cierra ordenes"
    assert "no esta permitido" in sin_permiso.get_data(as_text=True)

    mover(cliente, orden, "estado:OK_OPERADOR", comentario="Enlace probado a 50 Mbps")
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.OK_OPERADOR
    assert orden.cerrado_en is None
    assert orden.comentarios[-1].texto == "Enlace probado a 50 Mbps"

    # Ya no le queda nada por hacer.
    detalle = cliente.get(orden.url_detalle).get_data(as_text=True)
    assert "No hay acciones disponibles" in detalle
    salir(cliente)

    # --- El despachador la cierra en SIPREC -------------------------------
    entrar(cliente, despachador)
    assert notif.contar_no_leidas(despachador.id) >= 1
    tablero = cliente.get("/tablero?tipo=ordenes").get_data(as_text=True)
    assert "OK del operador" in tablero
    assert "Cerrada en SIPREC" in tablero

    mover(cliente, orden, "estado:CERRADA", comentario="Cierre registrado en SIPREC")
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.CERRADA
    assert orden.cerrado_en is not None
    assert orden.abierto is False
    salir(cliente)

    # --- Solo el admin la reabre ------------------------------------------
    entrar(cliente, operador)
    reabrir = mover(cliente, orden, "estado:EN_PROCESO", comentario="me falto algo")
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.CERRADA
    assert "no esta permitido" in reabrir.get_data(as_text=True)
    salir(cliente)

    entrar(cliente, admin)
    mover(cliente, orden, "estado:EN_PROCESO", comentario="Se reabre por revision")
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.EN_PROCESO
    assert orden.cerrado_en is None

    # --- Todo quedo en la bitacora ----------------------------------------
    estados = [h.valor_nuevo for h in orden.historial if h.campo == "estado"]
    assert estados == [
        "Nueva", "Asignada", "En proceso", "OK del operador", "Cerrada", "En proceso",
    ]


# ---------------------------------------------------------------------------
# Variantes del recorrido
# ---------------------------------------------------------------------------
def test_se_crea_y_asigna_en_un_solo_paso(cliente, despachador, operador):
    entrar(cliente, despachador)
    crear_orden_por_formulario(cliente, asignado_a_id=str(operador.id))

    orden = buscar_orden()
    assert orden.estado is EstadoOrden.ASIGNADA
    assert orden.asignado_a_id == operador.id
    assert notif.contar_no_leidas(operador.id) == 1


def test_la_orden_se_puede_crear_sin_fotos(cliente, despachador):
    entrar(cliente, despachador)
    respuesta = crear_orden_por_formulario(cliente, foto_anverso=None, foto_reverso=None)
    assert respuesta.status_code == 200

    orden = buscar_orden()
    assert orden.foto_anverso_key is None
    assert orden.foto_reverso_key is None
    # El detalle invita a agregarlas.
    detalle = cliente.get(orden.url_detalle).get_data(as_text=True)
    assert "Recomendada" in detalle or "Agregar" in detalle


def test_el_identificador_malo_no_crea_nada(cliente, despachador):
    entrar(cliente, despachador)
    respuesta = crear_orden_por_formulario(cliente, identificador_externo="EDF-12")
    assert "dos letras y despues solo digitos" in respuesta.get_data(as_text=True)
    assert db.session.execute(select(OrdenTrabajo)).first() is None


def test_el_identificador_corto_ahora_vale(cliente, despachador):
    """La cantidad de digitos no se restringe: dos letras y lo que traiga."""
    entrar(cliente, despachador)
    crear_orden_por_formulario(cliente, identificador_externo="ED1")
    assert buscar_orden("ED1").estado is EstadoOrden.NUEVA


def test_el_camino_de_abierta_con_motivo(cliente, despachador, operador):
    entrar(cliente, despachador)
    crear_orden_por_formulario(cliente, asignado_a_id=str(operador.id))
    orden = buscar_orden()
    salir(cliente)

    entrar(cliente, operador)
    mover(cliente, orden, "estado:EN_PROCESO")

    # Sin motivo no se mueve.
    mover(cliente, orden, "estado:ABIERTA_CON_MOTIVO", comentario="no hubo acceso")
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.EN_PROCESO

    mover(
        cliente, orden, "estado:ABIERTA_CON_MOTIVO",
        comentario="Portal cerrado", motivo="Cliente ausente",
    )
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.ABIERTA_CON_MOTIVO
    assert orden.motivo_apertura == "Cliente ausente"
    assert "Cliente ausente" in cliente.get(orden.url_detalle).get_data(as_text=True)

    # Y desde ahi tambien se da el OK.
    mover(cliente, orden, "estado:OK_OPERADOR", comentario="Atendido al dia siguiente")
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.OK_OPERADOR


def test_el_despachador_devuelve_el_ok(cliente, despachador, operador):
    entrar(cliente, despachador)
    crear_orden_por_formulario(cliente, asignado_a_id=str(operador.id))
    orden = buscar_orden()
    salir(cliente)

    entrar(cliente, operador)
    mover(cliente, orden, "estado:EN_PROCESO")
    mover(cliente, orden, "estado:OK_OPERADOR", comentario="listo")
    salir(cliente)

    entrar(cliente, despachador)
    mover(cliente, orden, "estado:EN_PROCESO", comentario="Falta la foto del cierre")
    db.session.refresh(orden)
    assert orden.estado is EstadoOrden.EN_PROCESO
    salir(cliente)

    # El operador se entera y puede volver a darle el OK.
    entrar(cliente, operador)
    assert notif.contar_no_leidas(operador.id) == 2  # asignacion + devolucion
    assert "Dar OK del trabajo" in cliente.get(orden.url_detalle).get_data(as_text=True)


def test_un_operador_ajeno_no_llega_al_detalle(cliente, despachador, operador, operador_b):
    entrar(cliente, despachador)
    crear_orden_por_formulario(cliente, asignado_a_id=str(operador.id))
    orden = buscar_orden()
    salir(cliente)

    entrar(cliente, operador_b)
    assert cliente.get(orden.url_detalle).status_code == 403
    assert orden.folio not in cliente.get("/ordenes/").get_data(as_text=True)

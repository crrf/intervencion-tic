"""La direccion del sitio: donde se hace el trabajo o donde esta la falla.

Opcional, como el telefono, pero presente en las tres puertas de creacion, en
la tarjeta, en el detalle, en la busqueda y en el CSV.
"""
from __future__ import annotations

import io

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models.base import normalizar_direccion
from app.models.enums import RolUsuario
from app.models.interrupcion import Interrupcion
from app.models.orden import OrdenTrabajo
from app.services import tickets as servicio
from app.services.consultas import Filtros, buscar
from app.services.estados import ejecutar_transicion
from tests.conftest import crear_usuario, imagen_jpeg

CLAVE = "Clave.2026"
DIRECCION = "Av. Bolivar con calle 5, edificio Centro, piso 2"


def entrar(cliente, usuario):
    return cliente.post("/login", data={"usuario": usuario.usuario, "password": CLAVE})


def texto(cliente, ruta):
    respuesta = cliente.get(ruta)
    assert respuesta.status_code == 200, ruta
    return respuesta.get_data(as_text=True)


@pytest.fixture
def tecnico_wifi(app):
    return crear_usuario("wifi", RolUsuario.TECNICO_WIFI)


# ---------------------------------------------------------------------------
# Normalizacion
# ---------------------------------------------------------------------------
def test_se_colapsan_los_espacios_y_los_saltos():
    assert normalizar_direccion("  Av.   Bolivar \n  casa 3 ") == "Av. Bolivar casa 3"


def test_una_direccion_vacia_se_guarda_como_nula():
    assert normalizar_direccion("") is None
    assert normalizar_direccion("    ") is None
    assert normalizar_direccion(None) is None


# ---------------------------------------------------------------------------
# Al crear
# ---------------------------------------------------------------------------
def test_la_orden_la_guarda(app, nueva_orden, despachador):
    orden = nueva_orden(despachador, direccion=f"  {DIRECCION}  ")
    assert orden.direccion == DIRECCION


def test_la_interrupcion_la_guarda(app, nueva_interrupcion, despachador):
    inter = nueva_interrupcion(despachador, direccion=DIRECCION)
    assert inter.direccion == DIRECCION


def test_es_opcional(app, nueva_orden, nueva_interrupcion, despachador):
    assert nueva_orden(despachador).direccion is None
    assert nueva_interrupcion(despachador).direccion is None


# ---------------------------------------------------------------------------
# Los tres formularios
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "ruta",
    ["/ordenes/nueva", "/interrupciones/nueva", "/interrupciones/nueva-wifi"],
)
def test_los_tres_formularios_piden_la_direccion(cliente, despachador, ruta):
    entrar(cliente, despachador)
    html = texto(cliente, ruta)
    assert 'name="direccion"' in html, ruta
    assert "Direccion" in html, ruta


def test_se_crea_una_orden_con_direccion_por_formulario(cliente, despachador):
    entrar(cliente, despachador)
    cliente.post(
        "/ordenes/nueva",
        data={
            "identificador_externo": "ED445566",
            "nombre_cliente": "Panaderia La Espiga",
            "titulo": "Instalacion de enlace",
            "direccion": DIRECCION,
            "foto_anverso": (io.BytesIO(imagen_jpeg()), "a.jpg"),
        },
        content_type="multipart/form-data", follow_redirects=True,
    )
    orden = db.session.execute(
        select(OrdenTrabajo).where(OrdenTrabajo.identificador_externo == "ED445566")
    ).scalar_one()
    assert orden.direccion == DIRECCION


def test_se_crea_un_sitio_wifi_con_direccion_por_formulario(
    cliente, despachador, tecnico_wifi
):
    entrar(cliente, despachador)
    cliente.post(
        "/interrupciones/nueva-wifi",
        data={
            "identificador_externo": "WF1234",
            "nombre_cliente": "Plaza Bolivar",
            "titulo": "El sitio wifi no da servicio",
            "direccion": DIRECCION,
            "asignado_a_id": str(tecnico_wifi.id),
        },
        follow_redirects=True,
    )
    inter = db.session.execute(
        select(Interrupcion).where(Interrupcion.identificador_externo == "WF1234")
    ).scalar_one()
    assert inter.direccion == DIRECCION
    assert inter.es_sitio_wifi is True
    assert inter.asignado_a_id == tecnico_wifi.id


# ---------------------------------------------------------------------------
# Completarla despues
# ---------------------------------------------------------------------------
def test_el_despachador_la_completa_despues(app, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    servicio.actualizar_contacto(orden, despachador, direccion=DIRECCION)

    assert orden.direccion == DIRECCION
    cambios = [h for h in orden.historial if h.campo == "direccion"]
    assert len(cambios) == 1
    assert cambios[0].valor_nuevo == DIRECCION


def test_los_dos_datos_se_guardan_de_una_vez(app, nueva_orden, despachador):
    orden = nueva_orden(despachador, telefono_contacto=None)
    servicio.actualizar_contacto(
        orden, despachador, telefono="0426-9998877", direccion=DIRECCION
    )
    assert orden.telefono_contacto == "0426-9998877"
    assert orden.direccion == DIRECCION
    campos = {h.campo for h in orden.historial}
    assert {"telefono_contacto", "direccion"} <= campos


def test_guardar_la_misma_no_ensucia_el_historial(app, nueva_orden, despachador):
    orden = nueva_orden(despachador, direccion=DIRECCION)
    servicio.actualizar_contacto(orden, despachador, direccion=DIRECCION)
    assert [h for h in orden.historial if h.campo == "direccion"] == []


def test_un_operador_no_la_cambia(app, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador, asignado_a=operador, direccion=DIRECCION)
    with pytest.raises(servicio.DatosInvalidos, match="despachador o un administrador"):
        servicio.actualizar_contacto(orden, operador, direccion="Otra parte")
    assert orden.direccion == DIRECCION


def test_se_borra_dejandola_vacia(app, nueva_orden, despachador):
    orden = nueva_orden(despachador, direccion=DIRECCION)
    servicio.actualizar_contacto(orden, despachador, direccion="  ")
    assert orden.direccion is None


def test_el_endpoint_de_contacto_guarda_los_dos(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador, telefono_contacto=None)
    db.session.commit()

    entrar(cliente, despachador)
    respuesta = cliente.post(
        f"/ordenes/{orden.id}/contacto",
        data={"telefono_contacto": "0412-1112233", "direccion": DIRECCION},
        follow_redirects=True,
    )
    assert "Datos de contacto actualizados" in respuesta.get_data(as_text=True)
    db.session.refresh(orden)
    assert orden.telefono_contacto == "0412-1112233"
    assert orden.direccion == DIRECCION


def test_el_endpoint_de_contacto_de_una_interrupcion(
    cliente, nueva_interrupcion, despachador
):
    inter = nueva_interrupcion(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    cliente.post(
        f"/interrupciones/{inter.id}/contacto",
        data={"direccion": DIRECCION}, follow_redirects=True,
    )
    db.session.refresh(inter)
    assert inter.direccion == DIRECCION


def test_un_telefono_invalido_no_guarda_tampoco_la_direccion(
    cliente, nueva_orden, despachador
):
    orden = nueva_orden(despachador, telefono_contacto=None)
    db.session.commit()

    entrar(cliente, despachador)
    respuesta = cliente.post(
        f"/ordenes/{orden.id}/contacto",
        data={"telefono_contacto": "no-es-telefono", "direccion": DIRECCION},
        follow_redirects=True,
    )
    assert "telefono" in respuesta.get_data(as_text=True).lower()
    db.session.refresh(orden)
    assert orden.direccion is None, "o se guardan los dos o ninguno"


# ---------------------------------------------------------------------------
# Al asignar
# ---------------------------------------------------------------------------
def test_se_registra_al_asignar(app, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador)
    assert orden.direccion is None

    ejecutar_transicion(
        orden, despachador, "estado:ASIGNADA",
        asignado_a=operador, direccion=DIRECCION,
    )
    db.session.commit()
    assert orden.direccion == DIRECCION
    assert any(h.campo == "direccion" for h in orden.historial)


def test_el_modal_de_asignacion_la_ofrece(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    modal = texto(
        cliente, f"/tablero/accion/ordenes/{orden.id}?transicion=estado:ASIGNADA"
    )
    assert 'name="direccion"' in modal
    assert 'name="telefono_contacto"' in modal


def test_se_guarda_al_mover_desde_el_tablero(cliente, nueva_orden, despachador, operador):
    orden = nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    cliente.post(
        f"/tablero/mover/ordenes/{orden.id}",
        data={
            "transicion": "estado:ASIGNADA",
            "asignado_a_id": str(operador.id),
            "direccion": DIRECCION,
        },
    )
    db.session.refresh(orden)
    assert orden.direccion == DIRECCION


# ---------------------------------------------------------------------------
# Donde se ve
# ---------------------------------------------------------------------------
def test_la_tarjeta_del_tablero_la_muestra(cliente, nueva_orden, despachador):
    nueva_orden(despachador, direccion=DIRECCION)
    db.session.commit()

    entrar(cliente, despachador)
    assert DIRECCION[:40] in texto(cliente, "/tablero?tipo=ordenes")


def test_el_detalle_la_muestra_y_deja_corregirla(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador, direccion=DIRECCION)
    db.session.commit()

    entrar(cliente, despachador)
    detalle = texto(cliente, orden.url_detalle)
    assert DIRECCION in detalle
    assert "Datos de contacto" in detalle
    assert f"/ordenes/{orden.id}/contacto" in detalle


def test_el_detalle_avisa_cuando_falta(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador, telefono_contacto="0414-1234567")
    db.session.commit()

    entrar(cliente, despachador)
    detalle = texto(cliente, orden.url_detalle)
    assert "Sin registrar" in detalle
    assert "destacado" in detalle, "el panel se resalta mientras falte"


def test_los_listados_la_muestran(
    cliente, nueva_orden, nueva_interrupcion, despachador
):
    nueva_orden(despachador, direccion=DIRECCION)
    nueva_interrupcion(despachador, direccion=DIRECCION)
    db.session.commit()

    entrar(cliente, despachador)
    assert DIRECCION[:40] in texto(cliente, "/ordenes/")
    assert DIRECCION[:40] in texto(cliente, "/interrupciones/")


# ---------------------------------------------------------------------------
# Busqueda y exportacion
# ---------------------------------------------------------------------------
def test_se_busca_por_direccion(app, nueva_orden, despachador, admin):
    con = nueva_orden(despachador, direccion="Av. Las Delicias, local 112")
    sin = nueva_orden(
        despachador, identificador_externo="ED222222", direccion="Calle Sucre, casa 14"
    )
    db.session.commit()

    datos = buscar(Filtros(texto="Delicias"), admin)
    assert datos["total"] == 1
    assert datos["filas"][0]["folio"] == con.folio
    assert datos["filas"][0]["direccion"] == "Av. Las Delicias, local 112"
    assert sin.folio not in [f["folio"] for f in datos["filas"]]


def test_la_bandeja_de_fibra_busca_por_direccion(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    from app.models.enums import Dependencia

    inter = nueva_interrupcion(
        despachador, asignado_a=operador, direccion="Sector La Romana, galpon 8"
    )
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="corte", dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()

    entrar(cliente, agente_fibra)
    assert inter.folio in texto(cliente, "/fibra/?q=Romana")


def test_el_csv_trae_la_direccion(cliente, nueva_orden, despachador):
    nueva_orden(despachador, direccion=DIRECCION)
    db.session.commit()

    entrar(cliente, despachador)
    csv = texto(cliente, "/buscar/csv")
    assert "Direccion" in csv.split("\r\n")[0]
    assert DIRECCION in csv


def test_la_auditoria_nombra_el_cambio(cliente, nueva_orden, despachador):
    orden = nueva_orden(despachador)
    servicio.actualizar_contacto(orden, despachador, direccion=DIRECCION)
    db.session.commit()

    entrar(cliente, despachador)
    bitacora = texto(cliente, "/reportes/auditoria?preset=30d")
    assert "Direccion" in bitacora
    assert DIRECCION in bitacora


# ---------------------------------------------------------------------------
# Datos de ejemplo
# ---------------------------------------------------------------------------
def test_la_siembra_pone_direcciones(app, monkeypatch):
    from app.cli import seed

    monkeypatch.setenv("SEED_PASSWORD", "Clave.2026")
    monkeypatch.setenv("ADMIN_PASSWORD", "ClaveAdmin.1")
    assert app.test_cli_runner().invoke(seed).exit_code == 0

    ordenes = db.session.execute(select(OrdenTrabajo)).scalars().unique().all()
    interrupciones = db.session.execute(select(Interrupcion)).scalars().unique().all()
    assert any(o.direccion for o in ordenes)
    assert any(i.direccion for i in interrupciones)

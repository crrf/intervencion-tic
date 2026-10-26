"""Barrido de interfaz: cada pantalla responde lo que debe para cada perfil,
y la barra ofrece exactamente lo que ese perfil puede hacer.

No sustituye a las pruebas de cada seccion: esta es la red que caza una
plantilla rota, un enlace a un endpoint que ya no existe o una pantalla que se
quedo accesible para quien no debe verla.
"""
from __future__ import annotations

import pytest

from app.extensions import db
from app.models.enums import Dependencia, RolUsuario
from app.services.estados import ejecutar_transicion
from tests.conftest import crear_usuario

CLAVE = "Clave.2026"

#: Pantallas de gestion: admin y despachador si, los demas no.
GESTION = (
    "/buscar/",
    "/buscar/csv",
    "/reportes/historico",
    "/reportes/historico/csv",
    "/reportes/auditoria",
    "/reportes/auditoria/csv",
    "/dashboard/",
    "/ordenes/nueva",
    "/interrupciones/nueva",
    "/interrupciones/nueva-wifi",
)

#: Pantallas comunes a cualquier sesion con rol de trabajo.
COMUNES = ("/tablero", "/ordenes/", "/interrupciones/", "/mi-cuenta")


@pytest.fixture
def tecnico_wifi(app):
    return crear_usuario("wifi", RolUsuario.TECNICO_WIFI)


def entrar(cliente, usuario):
    respuesta = cliente.post(
        "/login", data={"usuario": usuario.usuario, "password": CLAVE}
    )
    assert respuesta.status_code == 302, f"{usuario.usuario} no pudo entrar"


def salir(cliente):
    cliente.get("/logout")


@pytest.fixture
def datos(app, nueva_orden, nueva_interrupcion, despachador, operador, agente_fibra):
    """Un ticket de cada tipo en varios estados, para que nada se dibuje vacio."""
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:OK_OPERADOR", comentario="listo")

    enlace = nueva_interrupcion(
        despachador, identificador_externo="FD111111", asignado_a=operador
    )
    ejecutar_transicion(enlace, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        enlace, operador, "estado:DERIVADA_FIBRA",
        comentario="posible corte", dependencia=Dependencia.CAPA_FISICA,
    )
    ejecutar_transicion(
        enlace, agente_fibra, "estado_fibra:FIBRA_CON_FALLA", comentario="corte"
    )

    wifi = nueva_interrupcion(
        despachador, identificador_externo="WF2222", categoria="SITIO_WIFI",
        asignado_a=operador,
    )
    db.session.commit()
    return {"orden": orden, "enlace": enlace, "wifi": wifi}


def revisar(cliente, ruta, esperado=200):
    respuesta = cliente.get(ruta)
    assert respuesta.status_code == esperado, (
        f"{ruta}: devolvio {respuesta.status_code}, se esperaba {esperado}"
    )
    return respuesta


# ---------------------------------------------------------------------------
# Cada perfil ve lo suyo
# ---------------------------------------------------------------------------
def test_el_despachador_recorre_toda_la_gestion(cliente, datos, despachador):
    entrar(cliente, despachador)
    for ruta in GESTION + COMUNES:
        revisar(cliente, ruta)
    for ticket in datos.values():
        revisar(cliente, ticket.url_detalle)


def test_el_admin_llega_a_todo(cliente, datos, admin):
    entrar(cliente, admin)
    for ruta in GESTION + COMUNES + ("/admin/usuarios", "/admin/usuarios/nuevo", "/fibra/"):
        revisar(cliente, ruta)


def test_el_operador_solo_a_lo_suyo(cliente, datos, operador):
    entrar(cliente, operador)
    for ruta in COMUNES:
        revisar(cliente, ruta)
    for ruta in GESTION + ("/admin/usuarios", "/fibra/"):
        revisar(cliente, ruta, 403)
    for ticket in datos.values():
        revisar(cliente, ticket.url_detalle)


def test_el_agente_de_fibra_solo_a_su_bandeja(cliente, datos, agente_fibra):
    entrar(cliente, agente_fibra)
    revisar(cliente, "/fibra/")
    revisar(cliente, "/fibra/columnas")
    revisar(cliente, "/mi-cuenta")
    revisar(cliente, datos["enlace"].url_detalle)          # derivada a fibra
    revisar(cliente, datos["orden"].url_detalle, 403)
    revisar(cliente, datos["wifi"].url_detalle, 403)
    for ruta in GESTION:
        revisar(cliente, ruta, 403)
    # Su tablero redirige a la bandeja, que es su sitio.
    assert cliente.get("/tablero").status_code == 302


def test_el_tecnico_de_wifi_solo_a_lo_asignado(
    cliente, datos, despachador, tecnico_wifi
):
    from app.services.tickets import reasignar

    # La de sitio wifi nace asignada a un operador; se le pasa al tecnico.
    reasignar(datos["wifi"], despachador, tecnico_wifi)

    entrar(cliente, tecnico_wifi)
    revisar(cliente, "/tablero")
    revisar(cliente, "/interrupciones/")
    revisar(cliente, "/mi-cuenta")
    revisar(cliente, datos["wifi"].url_detalle)
    revisar(cliente, datos["enlace"].url_detalle, 403)
    revisar(cliente, datos["orden"].url_detalle, 403)
    for ruta in GESTION + ("/fibra/", "/admin/usuarios"):
        revisar(cliente, ruta, 403)


def test_sin_sesion_todo_redirige_al_login(cliente, datos):
    for ruta in GESTION + COMUNES + ("/fibra/", "/admin/usuarios"):
        respuesta = cliente.get(ruta)
        assert respuesta.status_code == 302, ruta
        assert "/login" in respuesta.headers["Location"], ruta


# ---------------------------------------------------------------------------
# La barra ofrece lo que corresponde
# ---------------------------------------------------------------------------
def test_la_barra_del_despachador_tiene_las_tres_puertas(cliente, despachador):
    entrar(cliente, despachador)
    barra = cliente.get("/tablero").get_data(as_text=True)
    assert "/ordenes/nueva" in barra
    assert "/interrupciones/nueva" in barra
    assert "/interrupciones/nueva-wifi" in barra
    assert "/buscar/" in barra and "/dashboard/" in barra
    assert "/admin/usuarios" not in barra, "no es administrador"


def test_la_barra_del_operador_no_ofrece_lo_que_no_puede(cliente, operador):
    entrar(cliente, operador)
    barra = cliente.get("/tablero").get_data(as_text=True)
    for enlace in ("/ordenes/nueva", "/interrupciones/nueva", "/buscar/", "/dashboard/"):
        assert enlace not in barra, enlace
    assert "/mi-cuenta" in barra and "/logout" in barra


def test_la_barra_del_admin_tiene_usuarios(cliente, admin):
    entrar(cliente, admin)
    barra = cliente.get("/tablero").get_data(as_text=True)
    assert "/admin/usuarios" in barra
    assert "/fibra/" in barra


def test_la_barra_del_tecnico_de_wifi_es_minima(cliente, tecnico_wifi):
    entrar(cliente, tecnico_wifi)
    barra = cliente.get("/tablero").get_data(as_text=True)
    assert "/interrupciones/nueva-wifi" not in barra, "el tecnico no crea tickets"
    assert "/fibra/" not in barra
    assert "/tablero" in barra


# ---------------------------------------------------------------------------
# Cada pantalla esta armada (titulo, sin huecos de plantilla)
# ---------------------------------------------------------------------------
SIN_HTML = ("/buscar/csv", "/reportes/historico/csv", "/reportes/auditoria/csv")


def test_ninguna_pantalla_deja_huecos_de_plantilla(cliente, datos, admin):
    """Un valor ausente en Jinja se imprime como "None" o queda vacio."""
    entrar(cliente, admin)
    rutas = [r for r in GESTION + COMUNES if r not in SIN_HTML]
    rutas += ["/admin/usuarios", "/fibra/"]
    rutas += [t.url_detalle for t in datos.values()]

    for ruta in rutas:
        cuerpo = revisar(cliente, ruta).get_data(as_text=True)
        assert "<h1" in cuerpo, f"{ruta}: no tiene titulo"
        assert "</html>" in cuerpo, f"{ruta}: la plantilla no cerro"
        assert ">None<" not in cuerpo, f"{ruta}: imprime None"
        assert "{{" not in cuerpo, f"{ruta}: quedo una expresion sin resolver"
        assert "jinja2" not in cuerpo.lower(), f"{ruta}: filtro un error de plantilla"


def test_todas_las_pantallas_cargan_la_hoja_y_los_scripts(cliente, despachador):
    entrar(cliente, despachador)
    cuerpo = cliente.get("/tablero").get_data(as_text=True)
    assert "css/app.css" in cuerpo
    assert "vendor/htmx.min.js" in cuerpo
    assert "vendor/alpine.min.js" in cuerpo
    assert "js/app.js" in cuerpo
    # Nada viene de internet: la aplicacion funciona en una red sin salida.
    assert "http://cdn" not in cuerpo and "https://cdn" not in cuerpo


def test_la_hoja_de_estilos_se_sirve(cliente, despachador):
    entrar(cliente, despachador)
    respuesta = cliente.get("/static/css/app.css")
    assert respuesta.status_code == 200
    assert "insignia" in respuesta.get_data(as_text=True)


def test_el_login_no_pide_sesion_y_esta_completo(cliente, app):
    cuerpo = cliente.get("/login").get_data(as_text=True)
    assert "<h1" in cuerpo
    assert 'name="usuario"' in cuerpo and 'name="password"' in cuerpo
    assert "css/app.css" in cuerpo


# ---------------------------------------------------------------------------
# Movil: lo esencial no se esconde
# ---------------------------------------------------------------------------
def test_en_movil_el_menu_lleva_las_acciones(cliente, despachador):
    """Lo que se oculta en pantalla estrecha tiene que estar en el menu."""
    entrar(cliente, despachador)
    cuerpo = cliente.get("/tablero").get_data(as_text=True)
    assert "hamburguesa" in cuerpo
    assert "menu-crear" in cuerpo, "las acciones de crear van en el menu movil"
    assert "menu-pie" in cuerpo, "cuenta y salir van en el menu movil"
    # El boton de crear de escritorio esta marcado para ocultarse en movil.
    assert "no-movil" in cuerpo


def test_las_tablas_anchas_pueden_desplazarse(cliente, datos, despachador):
    entrar(cliente, despachador)
    for ruta in ("/ordenes/", "/interrupciones/", "/buscar/?texto=ED"):
        cuerpo = cliente.get(ruta).get_data(as_text=True)
        assert "tabla-contenedor" in cuerpo, ruta

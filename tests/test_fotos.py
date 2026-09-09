"""Fotos: recomendadas pero no obligatorias, validacion y reemplazo."""
from __future__ import annotations

import pytest

from app.extensions import db
from app.services.tickets import (
    DatosInvalidos,
    crear_interrupcion,
    crear_orden,
    reemplazar_foto,
)
from tests.conftest import ArchivoFalso, imagen_jpeg

CLAVE = "Clave.2026"


def _orden(despachador, **kwargs):
    datos = {
        "identificador_externo": "ED111111",
        "nombre_cliente": "Cliente",
        "titulo": "Prueba",
    }
    datos.update(kwargs)
    return crear_orden(despachador, **datos)


def _interrupcion(despachador, **kwargs):
    datos = {
        "identificador_externo": "FD111111",
        "nombre_cliente": "Cliente",
        "titulo": "Prueba",
    }
    datos.update(kwargs)
    return crear_interrupcion(despachador, **datos)


# ---------------------------------------------------------------------------
# Opcionales
# ---------------------------------------------------------------------------
def test_se_crea_una_orden_sin_ninguna_foto(app, despachador, almacen):
    orden = _orden(despachador)

    assert orden.foto_anverso_key is None
    assert orden.foto_reverso_key is None
    assert almacen.objetos == {}
    assert orden.fotos_faltantes == ["anverso", "reverso"]
    assert orden.tiene_todas_las_fotos is False


def test_se_crea_una_orden_con_una_sola_cara(app, despachador):
    orden = _orden(despachador, foto_anverso=ArchivoFalso("a.jpg", imagen_jpeg()))

    assert orden.foto_anverso_key is not None
    assert orden.foto_reverso_key is None
    assert orden.fotos_faltantes == ["reverso"]


def test_se_crea_una_interrupcion_sin_foto(app, despachador):
    inter = _interrupcion(despachador)

    assert inter.foto_key is None
    assert inter.fotos_faltantes == ["foto"]


def test_un_campo_de_fichero_vacio_no_cuenta_como_foto(app, despachador):
    """El navegador manda el campo con filename vacio cuando no se elige nada."""
    orden = _orden(despachador, foto_anverso=ArchivoFalso("", b""))

    assert orden.foto_anverso_key is None
    assert orden.tiene_todas_las_fotos is False


def test_con_las_dos_caras_no_falta_ninguna(nueva_orden, despachador, almacen):
    orden = nueva_orden(despachador)

    assert orden.foto_anverso_key.startswith(f"ordenes/{orden.folio}/anverso")
    assert orden.foto_reverso_key.startswith(f"ordenes/{orden.folio}/reverso")
    assert orden.fotos_faltantes == []
    assert orden.tiene_todas_las_fotos is True
    assert set(almacen.objetos) == {orden.foto_anverso_key, orden.foto_reverso_key}


# ---------------------------------------------------------------------------
# Validacion de lo que si se adjunta
# ---------------------------------------------------------------------------
def test_formato_no_admitido(app, despachador):
    with pytest.raises(DatosInvalidos, match="Formato no admitido"):
        _orden(despachador, foto_anverso=ArchivoFalso("documento.pdf", b"%PDF-1.4"))


def test_archivo_que_no_es_imagen_de_verdad(app, despachador):
    """La extension dice jpg pero el contenido no lo es: Pillow lo detecta."""
    with pytest.raises(DatosInvalidos, match="imagen valida"):
        _orden(despachador, foto_anverso=ArchivoFalso("falsa.jpg", b"esto no es una imagen"))


def test_foto_demasiado_grande(app, despachador):
    grande = b"x" * (app.config["MAX_FOTO_MB"] * 1024 * 1024 + 10)
    with pytest.raises(DatosInvalidos, match="supera el maximo"):
        _orden(despachador, foto_anverso=ArchivoFalso("grande.jpg", grande))


def test_si_falla_la_segunda_cara_no_queda_huerfana_la_primera(app, despachador, almacen):
    with pytest.raises(DatosInvalidos, match="Formato no admitido"):
        _orden(
            despachador,
            foto_anverso=ArchivoFalso("a.jpg", imagen_jpeg()),
            foto_reverso=ArchivoFalso("r.pdf", b"%PDF"),
        )
    db.session.rollback()
    assert almacen.objetos == {}, "el anverso ya subido debe limpiarse"


# ---------------------------------------------------------------------------
# Datos del ticket (siguen siendo obligatorios)
# ---------------------------------------------------------------------------
def test_identificador_invalido(app, despachador):
    with pytest.raises(DatosInvalidos, match="dos letras y seis digitos"):
        _orden(despachador, identificador_externo="12345")


def test_identificador_se_normaliza_a_mayusculas(app, despachador):
    orden = _orden(despachador, identificador_externo=" ed987654 ")
    assert orden.identificador_externo == "ED987654"


# ---------------------------------------------------------------------------
# Agregar y reemplazar despues
# ---------------------------------------------------------------------------
def test_se_agrega_la_foto_que_faltaba(app, despachador, almacen):
    orden = _orden(despachador)
    assert orden.fotos_faltantes == ["anverso", "reverso"]

    clave = reemplazar_foto(
        orden, despachador, "anverso", ArchivoFalso("a.jpg", imagen_jpeg())
    )

    assert orden.foto_anverso_key == clave
    assert clave in almacen.objetos
    assert orden.fotos_faltantes == ["reverso"]

    cambios = [h for h in orden.historial if h.campo == "foto_anverso"]
    assert len(cambios) == 1
    assert cambios[0].valor_anterior is None, "no habia foto previa"


def test_reemplazar_una_existente_borra_la_vieja(nueva_orden, despachador, almacen):
    orden = nueva_orden(despachador)
    original = orden.foto_anverso_key

    nueva = reemplazar_foto(
        orden, despachador, "anverso", ArchivoFalso("nueva.jpg", imagen_jpeg((200, 30, 30)))
    )

    assert nueva != original
    assert original not in almacen.objetos
    cambios = [h for h in orden.historial if h.campo == "foto_anverso"]
    assert cambios[0].valor_anterior == original


def test_adjuntar_sin_elegir_archivo_avisa(app, despachador):
    orden = _orden(despachador)
    with pytest.raises(DatosInvalidos, match="No se adjunto"):
        reemplazar_foto(orden, despachador, "anverso", None)


def test_no_se_cambian_fotos_de_un_ticket_cerrado(nueva_orden, despachador, operador):
    from app.services.estados import ejecutar_transicion

    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:CERRADA", comentario="listo")
    db.session.commit()

    with pytest.raises(DatosInvalidos, match="cerrado"):
        reemplazar_foto(orden, despachador, "anverso", ArchivoFalso("x.jpg", imagen_jpeg()))


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------
def test_los_formularios_no_exigen_foto(cliente, despachador):
    cliente.post("/login", data={"usuario": despachador.usuario, "password": CLAVE})

    for ruta, campos in (
        ("/ordenes/nueva", ("foto_anverso", "foto_reverso")),
        ("/interrupciones/nueva", ("foto",)),
    ):
        html = cliente.get(ruta).get_data(as_text=True)
        assert "Recomendado" in html, ruta
        for campo in campos:
            bloque = html.split(f'name="{campo}"')[1][:120]
            assert "required" not in bloque, f"{ruta}: {campo} no debe ser obligatorio"


def test_el_detalle_ofrece_agregar_las_que_faltan(cliente, app, despachador):
    orden = _orden(despachador)
    cliente.post("/login", data={"usuario": despachador.usuario, "password": CLAVE})

    html = cliente.get(orden.url_detalle).get_data(as_text=True)
    assert "Sin foto" in html
    assert "Agregar" in html
    assert "es recomendable" in html


def test_una_foto_ausente_no_se_puede_pedir(cliente, app, despachador):
    """Sin clave no hay nada que servir: 404 limpio, no una imagen rota."""
    inter = _interrupcion(despachador)
    cliente.post("/login", data={"usuario": despachador.usuario, "password": CLAVE})

    assert cliente.get(f"/adjuntos/interrupcion/{inter.id}/foto").status_code == 404

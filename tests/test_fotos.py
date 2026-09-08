"""Fotos obligatorias, validacion y reemplazo."""
from __future__ import annotations

import pytest

from app.extensions import db
from app.services.tickets import DatosInvalidos, crear_orden, reemplazar_foto
from tests.conftest import ArchivoFalso, imagen_jpeg


def test_una_orden_exige_las_dos_caras(app, despachador, almacen):
    with pytest.raises(DatosInvalidos, match="obligatorias"):
        crear_orden(
            despachador,
            identificador_externo="ED111111",
            nombre_cliente="Cliente",
            titulo="Prueba",
            foto_anverso=ArchivoFalso("a.jpg", imagen_jpeg()),
            foto_reverso=None,
        )
    db.session.rollback()
    # El anverso ya subido se limpia para no dejar basura en el bucket.
    assert almacen.objetos == {}


def test_orden_creada_guarda_las_dos_claves(nueva_orden, despachador, almacen):
    orden = nueva_orden(despachador)
    assert orden.foto_anverso_key.startswith(f"ordenes/{orden.folio}/anverso")
    assert orden.foto_reverso_key.startswith(f"ordenes/{orden.folio}/reverso")
    assert set(almacen.objetos) == {orden.foto_anverso_key, orden.foto_reverso_key}


def test_interrupcion_exige_su_foto(app, despachador):
    from app.services.tickets import crear_interrupcion

    with pytest.raises(DatosInvalidos, match="obligatorias"):
        crear_interrupcion(
            despachador,
            identificador_externo="FD111111",
            nombre_cliente="Cliente",
            titulo="Prueba",
            foto=None,
        )


def test_formato_no_admitido(app, despachador):
    with pytest.raises(DatosInvalidos, match="Formato no admitido"):
        crear_orden(
            despachador,
            identificador_externo="ED222222",
            nombre_cliente="Cliente",
            titulo="Prueba",
            foto_anverso=ArchivoFalso("documento.pdf", b"%PDF-1.4"),
            foto_reverso=ArchivoFalso("r.jpg", imagen_jpeg()),
        )


def test_archivo_que_no_es_imagen_de_verdad(app, despachador):
    """La extension dice jpg pero el contenido no lo es: Pillow lo detecta."""
    with pytest.raises(DatosInvalidos, match="imagen valida"):
        crear_orden(
            despachador,
            identificador_externo="ED333333",
            nombre_cliente="Cliente",
            titulo="Prueba",
            foto_anverso=ArchivoFalso("falsa.jpg", b"esto no es una imagen"),
            foto_reverso=ArchivoFalso("r.jpg", imagen_jpeg()),
        )


def test_foto_demasiado_grande(app, despachador):
    grande = b"x" * (app.config["MAX_FOTO_MB"] * 1024 * 1024 + 10)
    with pytest.raises(DatosInvalidos, match="supera el maximo"):
        crear_orden(
            despachador,
            identificador_externo="ED444444",
            nombre_cliente="Cliente",
            titulo="Prueba",
            foto_anverso=ArchivoFalso("grande.jpg", grande),
            foto_reverso=ArchivoFalso("r.jpg", imagen_jpeg()),
        )


def test_identificador_invalido(app, despachador):
    with pytest.raises(DatosInvalidos, match="dos letras y seis digitos"):
        crear_orden(
            despachador,
            identificador_externo="12345",
            nombre_cliente="Cliente",
            titulo="Prueba",
            foto_anverso=ArchivoFalso("a.jpg", imagen_jpeg()),
            foto_reverso=ArchivoFalso("r.jpg", imagen_jpeg()),
        )


def test_identificador_se_normaliza_a_mayusculas(nueva_orden, despachador):
    orden = nueva_orden(despachador, identificador_externo=" ed987654 ")
    assert orden.identificador_externo == "ED987654"


def test_reemplazar_foto_deja_rastro(nueva_orden, despachador, almacen):
    orden = nueva_orden(despachador)
    original = orden.foto_anverso_key

    nueva = reemplazar_foto(
        orden, despachador, "anverso", ArchivoFalso("nueva.jpg", imagen_jpeg((200, 30, 30)))
    )
    assert nueva != original
    assert orden.foto_anverso_key == nueva
    assert original not in almacen.objetos, "la foto vieja debio borrarse"

    cambios = [h for h in orden.historial if h.campo == "foto_anverso"]
    assert len(cambios) == 1
    assert cambios[0].valor_anterior == original


def test_no_se_cambian_fotos_de_un_ticket_cerrado(nueva_orden, despachador, operador):
    from app.services.estados import ejecutar_transicion

    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:CERRADA", comentario="listo")
    db.session.commit()

    with pytest.raises(DatosInvalidos, match="cerrado"):
        reemplazar_foto(orden, despachador, "anverso", ArchivoFalso("x.jpg", imagen_jpeg()))

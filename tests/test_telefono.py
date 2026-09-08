"""Telefono de contacto del cliente: opcional pero recomendado."""
from __future__ import annotations

import pytest

from app.extensions import db
from app.models.base import normalizar_telefono, telefono_valido
from app.services.estados import ejecutar_transicion
from app.services.tickets import DatosInvalidos, actualizar_telefono

CLAVE = "Clave.2026"


# ---------------------------------------------------------------------------
# Validacion
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "valor",
    ["0414-1234567", "+58 414 1234567", "(0212) 555-1212", "02125551212", "0212.555.1212"],
)
def test_formatos_admitidos(valor):
    assert telefono_valido(valor)


@pytest.mark.parametrize("valor", ["", "   ", None])
def test_vacio_es_valido_porque_es_opcional(valor):
    assert telefono_valido(valor)
    assert normalizar_telefono(valor) is None


@pytest.mark.parametrize("valor", ["abc", "0414-ABC", "12345", "correo@dominio.com", "++"])
def test_formatos_rechazados(valor):
    assert not telefono_valido(valor)


def test_se_normalizan_los_espacios():
    assert normalizar_telefono("  0414   123 4567  ") == "0414 123 4567"


# ---------------------------------------------------------------------------
# Creacion
# ---------------------------------------------------------------------------
def test_se_guarda_al_crear(nueva_interrupcion, despachador):
    inter = nueva_interrupcion(despachador, telefono_contacto="0414-1234567")
    assert inter.telefono_contacto == "0414-1234567"
    assert inter.telefono_marcable == "04141234567"


def test_se_puede_crear_sin_telefono(nueva_orden, despachador):
    orden = nueva_orden(despachador)
    assert orden.telefono_contacto is None
    assert orden.telefono_marcable is None


def test_un_telefono_invalido_impide_crear(nueva_orden, despachador):
    with pytest.raises(DatosInvalidos, match="telefono de contacto"):
        nueva_orden(despachador, telefono_contacto="no-es-un-telefono")


def test_el_marcable_conserva_el_prefijo_internacional(nueva_orden, despachador):
    orden = nueva_orden(despachador, telefono_contacto="+58 (414) 123-4567")
    assert orden.telefono_marcable == "+584141234567"


# ---------------------------------------------------------------------------
# Actualizacion posterior
# ---------------------------------------------------------------------------
def test_el_despachador_lo_completa_despues(nueva_orden, despachador):
    orden = nueva_orden(despachador)
    actualizar_telefono(orden, despachador, "0424-7654321")

    assert orden.telefono_contacto == "0424-7654321"
    cambios = [h for h in orden.historial if h.campo == "telefono_contacto"]
    assert len(cambios) == 1
    assert cambios[0].valor_nuevo == "0424-7654321"


def test_un_operador_no_puede_cambiarlo(nueva_orden, despachador, operador):
    orden = nueva_orden(despachador, asignado_a=operador, telefono_contacto="0414-1111111")
    with pytest.raises(DatosInvalidos, match="despachador o un administrador"):
        actualizar_telefono(orden, operador, "0414-9999999")
    assert orden.telefono_contacto == "0414-1111111"


def test_guardar_el_mismo_no_ensucia_el_historial(nueva_orden, despachador):
    orden = nueva_orden(despachador, telefono_contacto="0414-1234567")
    actualizar_telefono(orden, despachador, "0414-1234567")
    assert [h for h in orden.historial if h.campo == "telefono_contacto"] == []


# ---------------------------------------------------------------------------
# Al asignar
# ---------------------------------------------------------------------------
def test_se_puede_registrar_al_asignar(nueva_interrupcion, despachador, operador):
    inter = nueva_interrupcion(despachador)
    assert inter.telefono_contacto is None

    ejecutar_transicion(
        inter, despachador, "estado:ASIGNADA",
        asignado_a=operador, telefono_contacto="0416-5556677",
    )
    db.session.commit()

    assert inter.telefono_contacto == "0416-5556677"
    assert any(h.campo == "telefono_contacto" for h in inter.historial)


def test_un_telefono_invalido_al_asignar_aborta_la_transicion(
    nueva_interrupcion, despachador, operador
):
    from app.services.estados import TransicionInvalida

    inter = nueva_interrupcion(despachador)
    with pytest.raises(TransicionInvalida, match="telefono de contacto"):
        ejecutar_transicion(
            inter, despachador, "estado:ASIGNADA",
            asignado_a=operador, telefono_contacto="xxx",
        )
    db.session.rollback()
    assert inter.estado.name == "NUEVA"


def test_asignar_sin_telefono_sigue_funcionando(nueva_orden, despachador, operador):
    orden = nueva_orden(despachador)
    ejecutar_transicion(orden, despachador, "estado:ASIGNADA", asignado_a=operador)
    db.session.commit()
    assert orden.estado.name == "ASIGNADA"
    assert orden.telefono_contacto is None


# ---------------------------------------------------------------------------
# Busqueda
# ---------------------------------------------------------------------------
def test_se_puede_buscar_por_telefono(nueva_orden, nueva_interrupcion, despachador, admin):
    con = nueva_orden(despachador, telefono_contacto="0414-8887766")
    nueva_interrupcion(despachador, telefono_contacto="0424-1112233")

    from app.services.consultas import Filtros, buscar

    datos = buscar(Filtros(texto="0414-8887766"), admin)
    assert datos["total"] == 1
    assert datos["filas"][0]["folio"] == con.folio
    assert datos["filas"][0]["telefono_contacto"] == "0414-8887766"


def test_la_web_muestra_el_campo_como_recomendado(cliente, despachador):
    cliente.post(
        "/login", data={"usuario": despachador.usuario, "password": CLAVE}
    )
    for ruta in ("/ordenes/nueva", "/interrupciones/nueva"):
        html = cliente.get(ruta).get_data(as_text=True)
        assert 'name="telefono_contacto"' in html, ruta
        assert "Recomendado" in html, ruta

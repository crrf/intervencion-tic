"""La paleta cumple WCAG AA, y cada color declarado existe en la hoja.

Si manana alguien aclara un color o agrega un estado nuevo sin su clase CSS,
esta prueba lo dice antes de que llegue a la pantalla de un tecnico.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models.enums import (
    COLORES_CATEGORIA,
    COLORES_ESTADO,
    COLORES_PRIORIDAD,
    CategoriaInterrupcion,
    EstadoFibra,
    EstadoInterrupcion,
    EstadoOrden,
    Prioridad,
)

CSS = (Path(__file__).resolve().parent.parent / "app/static/css/app.css").read_text(
    encoding="utf-8"
)

#: WCAG 2.1 AA.
TEXTO_NORMAL = 4.5
TEXTO_GRANDE = 3.0
COMPONENTE = 3.0


def _bloque(inicio: str) -> str:
    i = CSS.index(inicio)
    return CSS[i : CSS.index("}", i)]


def _variables(bloque: str) -> dict[str, str]:
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,8})", bloque))


CLARO = _variables(_bloque(":root {"))
OSCURO = {**CLARO, **_variables(_bloque("@media (prefers-color-scheme: dark) {\n  :root {"))}
TEMAS = {"claro": CLARO, "oscuro": OSCURO}


def _luminancia(color: str) -> float:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    canales = []
    for i in (0, 2, 4):
        v = int(c[i : i + 2], 16) / 255
        canales.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    r, g, b = canales
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    la, lb = _luminancia(a), _luminancia(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def razon(tema: str, texto: str, fondo: str) -> float:
    paleta = TEMAS[tema]
    assert texto in paleta, f"falta --{texto} en el tema {tema}"
    assert fondo in paleta, f"falta --{fondo} en el tema {tema}"
    return contraste(paleta[texto], paleta[fondo])


#: Nombres de color usados por las insignias.
COLORES_INSIGNIA = sorted(
    set(COLORES_ESTADO.values()) | set(COLORES_PRIORIDAD.values())
    | set(COLORES_CATEGORIA.values())
)


# ---------------------------------------------------------------------------
# El medidor mismo
# ---------------------------------------------------------------------------
def test_el_calculo_de_contraste_es_correcto():
    """Comprueba el medidor contra valores conocidos de la especificacion."""
    assert contraste("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert contraste("#ffffff", "#ffffff") == pytest.approx(1.0, abs=0.01)
    assert contraste("#767676", "#ffffff") == pytest.approx(4.54, abs=0.02)


# ---------------------------------------------------------------------------
# Insignias
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tema", list(TEMAS))
@pytest.mark.parametrize("color", COLORES_INSIGNIA)
def test_cada_insignia_es_legible(tema, color):
    """La insignia es texto de 0.72rem en negrita: umbral de texto normal."""
    valor = razon(tema, color, f"{color}-fondo")
    assert valor >= TEXTO_NORMAL, (
        f"insignia {color} en tema {tema}: {valor:.2f}:1, hace falta {TEXTO_NORMAL}:1"
    )


@pytest.mark.parametrize("color", COLORES_INSIGNIA)
def test_cada_color_de_insignia_tiene_su_clase(color):
    assert f".insignia.{color}" in CSS.replace(" ", ""), (
        f"falta la regla .insignia.{color} en app.css"
    )


@pytest.mark.parametrize(
    "clase", [EstadoOrden, EstadoInterrupcion, EstadoFibra, Prioridad, CategoriaInterrupcion]
)
def test_cada_miembro_tiene_color(clase):
    mapa = {
        "Prioridad": COLORES_PRIORIDAD,
        "CategoriaInterrupcion": COLORES_CATEGORIA,
    }.get(clase.__name__, COLORES_ESTADO)
    for miembro in clase:
        assert miembro.name in mapa, f"{clase.__name__}.{miembro.name} no tiene color"


def test_el_sitio_wifi_no_comparte_color_con_fibra():
    """Las dos insignias conviven en la misma tarjeta: no pueden ser iguales."""
    wifi = COLORES_CATEGORIA["SITIO_WIFI"]
    assert wifi != COLORES_ESTADO["DERIVADA_FIBRA"]
    assert wifi != COLORES_ESTADO["FIBRA_CON_FALLA"]
    assert wifi != COLORES_ESTADO["FIBRA_OK"]


def test_los_estados_de_cierre_y_de_ok_se_distinguen():
    assert COLORES_ESTADO["OK_OPERADOR"] != COLORES_ESTADO["CERRADA"]


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
SUPERFICIES = ("fondo", "superficie", "superficie-2")


@pytest.mark.parametrize("tema", list(TEMAS))
@pytest.mark.parametrize("texto", ("texto", "texto-suave", "texto-tenue"))
@pytest.mark.parametrize("fondo", SUPERFICIES)
def test_los_grises_de_texto_son_legibles(tema, texto, fondo):
    valor = razon(tema, texto, fondo)
    assert valor >= TEXTO_NORMAL, (
        f"--{texto} sobre --{fondo} en tema {tema}: {valor:.2f}:1"
    )


@pytest.mark.parametrize("tema", list(TEMAS))
def test_la_jerarquia_de_grises_se_sigue_notando(tema):
    """Pasar AA no debe costar que los tres grises se vean iguales."""
    paleta = TEMAS[tema]
    fuerte = razon(tema, "texto", "superficie")
    medio = razon(tema, "texto-suave", "superficie")
    debil = razon(tema, "texto-tenue", "superficie")
    assert fuerte > medio > debil, f"tema {tema}: {fuerte:.2f} / {medio:.2f} / {debil:.2f}"
    assert contraste(paleta["texto-suave"], paleta["texto-tenue"]) >= 1.2


@pytest.mark.parametrize("tema", list(TEMAS))
def test_la_marca_es_legible(tema):
    assert razon(tema, "marca", "marca-fondo") >= TEXTO_NORMAL
    assert razon(tema, "marca-clara", "superficie") >= TEXTO_NORMAL


@pytest.mark.parametrize("tema", list(TEMAS))
@pytest.mark.parametrize("color", ("rojo", "verde", "ambar", "violeta", "cian"))
def test_las_cifras_del_dashboard_son_legibles(tema, color):
    """1.8rem en negrita: cuenta como texto grande (3:1)."""
    assert razon(tema, color, "superficie") >= TEXTO_GRANDE


# ---------------------------------------------------------------------------
# Componentes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tema", list(TEMAS))
@pytest.mark.parametrize("fondo", ("superficie", "superficie-2"))
def test_el_contorno_de_los_controles_se_distingue(tema, fondo):
    """WCAG 1.4.11: el borde que identifica un control necesita 3:1."""
    valor = razon(tema, "borde-campo", fondo)
    assert valor >= COMPONENTE, f"--borde-campo sobre --{fondo} ({tema}): {valor:.2f}:1"


def test_los_controles_usan_el_borde_accesible():
    """Los campos y botones no deben volver al borde decorativo."""
    controles = CSS[CSS.index("/* ---------- Botones") : CSS.index("/* ---------- Insignias")]
    assert "var(--borde-campo)" in controles
    assert "border: 1px solid var(--borde-fuerte)" not in controles


@pytest.mark.parametrize("tema", list(TEMAS))
def test_el_tema_define_todas_sus_variables(tema):
    """Un tema incompleto hereda colores del otro y se ve roto."""
    paleta = TEMAS[tema]
    for nombre in (
        "fondo", "superficie", "superficie-2", "borde", "borde-fuerte", "borde-campo",
        "texto", "texto-suave", "texto-tenue", "marca", "marca-clara", "marca-fondo",
    ):
        assert nombre in paleta, f"falta --{nombre} en el tema {tema}"
    for color in COLORES_INSIGNIA:
        assert color in paleta, f"falta --{color} en el tema {tema}"
        assert f"{color}-fondo" in paleta, f"falta --{color}-fondo en el tema {tema}"

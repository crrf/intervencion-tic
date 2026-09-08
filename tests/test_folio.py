"""Generacion de folios: unicos y consecutivos, incluso con concurrencia."""
from __future__ import annotations

import threading

from app.extensions import db
from app.models.base import ahora
from app.models.contador import siguiente_folio
from app.models.enums import TipoTicket


def test_folios_consecutivos_y_con_formato(app):
    anio = ahora().year
    folios = [siguiente_folio(TipoTicket.ORDEN, anio) for _ in range(50)]
    db.session.commit()

    assert len(set(folios)) == 50
    assert folios[0] == f"OT-{anio}-0001"
    assert folios[-1] == f"OT-{anio}-0050"


def test_cada_tipo_lleva_su_propia_serie(app):
    anio = ahora().year
    orden = siguiente_folio(TipoTicket.ORDEN, anio)
    inter = siguiente_folio(TipoTicket.INTERRUPCION, anio)
    db.session.commit()

    assert orden == f"OT-{anio}-0001"
    assert inter == f"INT-{anio}-0001"


def test_sin_duplicados_con_varios_hilos(app):
    """Reproduce lo que hacen varios workers de gunicorn a la vez.

    El bloqueo SELECT ... FOR UPDATE del contador es lo que evita que dos
    transacciones simultaneas reserven el mismo numero.
    """
    anio = ahora().year
    hilos, resultados, errores = [], [], []
    candado = threading.Lock()

    def trabajo():
        try:
            with app.app_context():
                propios = []
                for _ in range(5):
                    propios.append(siguiente_folio(TipoTicket.ORDEN, anio))
                    db.session.commit()
                db.session.remove()
            with candado:
                resultados.extend(propios)
        except Exception as exc:  # noqa: BLE001
            with candado:
                errores.append(exc)

    for _ in range(6):
        hilos.append(threading.Thread(target=trabajo))
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)

    assert not errores, errores
    assert len(resultados) == 30
    assert len(set(resultados)) == 30, "se repitio algun folio"

    numeros = sorted(int(f.rsplit("-", 1)[1]) for f in resultados)
    assert numeros == list(range(1, 31)), "la serie quedo con huecos"

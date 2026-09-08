"""Bandeja del agente de fibra: busqueda, filtros y columna ampliada."""
from __future__ import annotations

from datetime import timedelta

from app.extensions import db
from app.models.base import ahora
from app.models.enums import Dependencia, EstadoFibra, Prioridad
from app.services.estados import ejecutar_transicion

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    return cliente.post(
        "/login", data={"usuario": usuario.usuario, "password": CLAVE}, follow_redirects=False
    )


def derivar(inter, operador):
    """Lleva una interrupcion recien creada hasta la bandeja de fibra."""
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:DERIVADA_FIBRA",
        comentario="Se descarto equipo activo; se presume corte en el tramo.",
        dependencia=Dependencia.CAPA_FISICA,
    )
    db.session.commit()
    return inter


def carga(nueva_interrupcion, despachador, operador, cuantas=6):
    """Simula una bandeja con trabajo acumulado."""
    creadas = []
    prioridades = list(Prioridad)
    for i in range(cuantas):
        inter = nueva_interrupcion(
            despachador,
            identificador_externo=f"FD{100000 + i}",
            nombre_cliente=f"Cliente {i:02d}" if i else "Panaderia El Trigal",
            telefono_contacto="0414-1234567" if i % 2 == 0 else None,
            titulo=f"Falla numero {i}",
            prioridad=prioridades[i % len(prioridades)],
            asignado_a=operador,
        )
        derivar(inter, operador)
        # Se envejece para poder probar el orden por antiguedad.
        inter.derivado_fibra_en = ahora() - timedelta(hours=cuantas - i)
        creadas.append(inter)
    db.session.commit()
    return creadas


# ---------------------------------------------------------------------------
# Busqueda y filtros
# ---------------------------------------------------------------------------
def test_la_bandeja_lista_todo_lo_derivado(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    creadas = carga(nueva_interrupcion, despachador, operador)
    entrar(cliente, agente_fibra)

    html = cliente.get("/fibra/").get_data(as_text=True)
    for inter in creadas:
        assert inter.folio in html


def test_busca_por_folio(cliente, nueva_interrupcion, despachador, operador, agente_fibra):
    creadas = carga(nueva_interrupcion, despachador, operador)
    entrar(cliente, agente_fibra)

    objetivo = creadas[2]
    html = cliente.get(f"/fibra/?q={objetivo.folio}").get_data(as_text=True)
    assert objetivo.folio in html
    for otra in creadas:
        if otra is not objetivo:
            assert otra.folio not in html


def test_busca_por_identificador_cliente_y_telefono(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    carga(nueva_interrupcion, despachador, operador)
    entrar(cliente, agente_fibra)

    assert "FD100003" in cliente.get("/fibra/?q=FD100003").get_data(as_text=True)
    assert "Panaderia" in cliente.get("/fibra/?q=Panaderia").get_data(as_text=True)
    assert "0414-1234567" in cliente.get("/fibra/?q=0414").get_data(as_text=True)


def test_sin_coincidencias_avisa(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    carga(nueva_interrupcion, despachador, operador)
    entrar(cliente, agente_fibra)

    html = cliente.get("/fibra/?q=zzz-no-existe").get_data(as_text=True)
    assert "Ninguna interrupcion derivada coincide" in html


def test_filtra_por_prioridad(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    creadas = carga(nueva_interrupcion, despachador, operador)
    entrar(cliente, agente_fibra)

    html = cliente.get("/fibra/?prioridad=CRITICA").get_data(as_text=True)
    criticas = [i for i in creadas if i.prioridad is Prioridad.CRITICA]
    otras = [i for i in creadas if i.prioridad is not Prioridad.CRITICA]
    assert criticas, "la carga de prueba debe incluir alguna critica"
    for i in criticas:
        assert i.folio in html
    for i in otras:
        assert i.folio not in html


def test_ordena_por_antiguedad_por_defecto(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    creadas = carga(nueva_interrupcion, despachador, operador)
    entrar(cliente, agente_fibra)

    html = cliente.get("/fibra/").get_data(as_text=True)
    posiciones = [html.index(i.folio) for i in creadas]
    # La primera creada es la que lleva mas tiempo esperando.
    assert posiciones == sorted(posiciones), "las mas antiguas deben ir primero"


def test_ordena_por_prioridad(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    creadas = carga(nueva_interrupcion, despachador, operador)
    entrar(cliente, agente_fibra)

    html = cliente.get("/fibra/?orden=prioridad").get_data(as_text=True)
    criticas = [i for i in creadas if i.prioridad is Prioridad.CRITICA]
    bajas = [i for i in creadas if i.prioridad is Prioridad.BAJA]
    assert criticas and bajas
    assert min(html.index(i.folio) for i in criticas) < min(html.index(i.folio) for i in bajas)


# ---------------------------------------------------------------------------
# Columna ampliada
# ---------------------------------------------------------------------------
def test_ampliar_una_columna(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    creadas = carga(nueva_interrupcion, despachador, operador)
    entrar(cliente, agente_fibra)

    html = cliente.get("/fibra/?ampliada=EN_REVISION").get_data(as_text=True)
    assert "con-ampliada" in html
    assert "columna ampliada" in html
    assert "reducida" in html
    assert "Restaurar" in html
    # Se ven todas, con los datos ampliados.
    for inter in creadas:
        assert inter.folio in html
    assert "detallada" in html
    assert "Esperando" in html


def test_la_vista_ampliada_trae_contexto_del_operador(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    carga(nueva_interrupcion, despachador, operador, cuantas=2)
    entrar(cliente, agente_fibra)

    html = cliente.get("/fibra/?ampliada=EN_REVISION").get_data(as_text=True)
    assert "se presume corte en el tramo" in html, "debe mostrar el ultimo comentario"
    assert operador.nombre_completo in html


def test_ampliada_invalida_se_ignora(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    carga(nueva_interrupcion, despachador, operador, cuantas=2)
    entrar(cliente, agente_fibra)

    respuesta = cliente.get("/fibra/?ampliada=NO_EXISTE")
    assert respuesta.status_code == 200
    assert "con-ampliada" not in respuesta.get_data(as_text=True)


def test_ampliada_y_busqueda_se_combinan(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    creadas = carga(nueva_interrupcion, despachador, operador)
    entrar(cliente, agente_fibra)

    objetivo = creadas[1]
    html = cliente.get(
        f"/fibra/?ampliada=EN_REVISION&q={objetivo.folio}"
    ).get_data(as_text=True)
    assert "con-ampliada" in html
    assert objetivo.folio in html
    assert creadas[3].folio not in html


def test_el_refresco_parcial_conserva_los_filtros(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    creadas = carga(nueva_interrupcion, despachador, operador)
    entrar(cliente, agente_fibra)

    html = cliente.get(
        f"/fibra/columnas?ampliada=EN_REVISION&q={creadas[0].folio}"
    ).get_data(as_text=True)
    assert "con-ampliada" in html
    assert creadas[0].folio in html
    assert creadas[4].folio not in html


def test_mover_conservando_los_filtros(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    """El POST del tablero recibe los filtros en la query string."""
    creadas = carga(nueva_interrupcion, despachador, operador)
    entrar(cliente, agente_fibra)

    objetivo = creadas[0]
    respuesta = cliente.post(
        f"/fibra/mover/{objetivo.id}?ampliada=EN_REVISION",
        data={
            "transicion": "estado_fibra:FIBRA_CON_FALLA",
            "comentario": "Corte confirmado en el tramo aereo.",
        },
    )
    html = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 200
    assert "con-ampliada" in html, "el modo ampliado debe sobrevivir al movimiento"
    db.session.refresh(objetivo)
    assert objetivo.estado_fibra is EstadoFibra.FIBRA_CON_FALLA


def test_la_bandeja_avisa_de_las_demoradas(
    cliente, nueva_interrupcion, despachador, operador, agente_fibra
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    derivar(inter, operador)
    inter.derivado_fibra_en = ahora() - timedelta(hours=10)
    db.session.commit()

    entrar(cliente, agente_fibra)
    html = cliente.get("/fibra/").get_data(as_text=True)
    assert "sin revisar hace mas de" in html
    assert "demorada" in cliente.get("/fibra/?ampliada=EN_REVISION").get_data(as_text=True)


def test_un_operador_no_entra_a_la_bandeja(cliente, operador):
    entrar(cliente, operador)
    assert cliente.get("/fibra/").status_code == 403
    assert cliente.get("/fibra/columnas").status_code == 403

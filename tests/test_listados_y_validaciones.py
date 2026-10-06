"""Listados por perfil, validaciones de los servicios y restablecimiento
de contrasenas desde la pantalla de administracion."""
from __future__ import annotations

import pytest

from app.extensions import db
from app.models.enums import Dependencia, RolUsuario
from app.services import tickets as servicio
from app.services import usuarios as servicio_usuarios
from app.services.estados import TransicionInvalida, ejecutar_transicion
from tests.conftest import crear_usuario

CLAVE = "Clave.2026"


def entrar(cliente, usuario):
    return cliente.post("/login", data={"usuario": usuario.usuario, "password": CLAVE})


def salir(cliente):
    cliente.get("/logout")


def texto(cliente, ruta):
    respuesta = cliente.get(ruta)
    assert respuesta.status_code == 200, ruta
    return respuesta.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Listados
# ---------------------------------------------------------------------------
def test_el_listado_de_ordenes_por_perfil(
    cliente, nueva_orden, despachador, operador, operador_b
):
    mia = nueva_orden(despachador, asignado_a=operador)
    suya = nueva_orden(
        despachador, identificador_externo="ED222222", asignado_a=operador_b
    )
    db.session.commit()

    entrar(cliente, despachador)
    completo = texto(cliente, "/ordenes/")
    assert mia.folio in completo and suya.folio in completo
    salir(cliente)

    entrar(cliente, operador)
    propio = texto(cliente, "/ordenes/")
    assert mia.folio in propio
    assert suya.folio not in propio


def test_el_listado_de_interrupciones_muestra_la_categoria(
    cliente, nueva_interrupcion, despachador
):
    wifi = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    db.session.commit()

    entrar(cliente, despachador)
    cuerpo = texto(cliente, "/interrupciones/")
    assert wifi.folio in cuerpo
    assert "Sitio wifi" in cuerpo
    assert "Por diagnosticar" in cuerpo


def test_un_listado_vacio_lo_dice(cliente, operador):
    entrar(cliente, operador)
    assert "No hay ordenes" in texto(cliente, "/ordenes/")
    assert "No hay interrupciones" in texto(cliente, "/interrupciones/")


def test_el_agente_de_fibra_no_ve_el_listado_de_ordenes(
    cliente, nueva_orden, despachador, agente_fibra
):
    orden = nueva_orden(despachador)
    db.session.commit()

    entrar(cliente, agente_fibra)
    assert orden.folio not in texto(cliente, "/ordenes/")


# ---------------------------------------------------------------------------
# Validaciones al crear
# ---------------------------------------------------------------------------
def test_el_cliente_y_el_titulo_son_obligatorios(app, despachador, nueva_orden):
    with pytest.raises(servicio.DatosInvalidos, match="cliente"):
        nueva_orden(despachador, nombre_cliente="  ")
    with pytest.raises(servicio.DatosInvalidos, match="titulo"):
        nueva_orden(despachador, titulo="")


def test_el_telefono_malo_impide_crear(app, despachador, nueva_orden):
    with pytest.raises(servicio.DatosInvalidos, match="telefono"):
        nueva_orden(despachador, telefono_contacto="abc")


def test_una_prioridad_desconocida_cae_en_media(app, despachador, nueva_orden):
    from app.models.enums import Prioridad

    orden = nueva_orden(despachador, prioridad="SUPERURGENTE")
    assert orden.prioridad is Prioridad.MEDIA


def test_una_categoria_desconocida_cae_en_enlace(app, despachador, nueva_interrupcion):
    from app.models.enums import CategoriaInterrupcion

    inter = nueva_interrupcion(despachador, categoria="LO_QUE_SEA")
    assert inter.categoria is CategoriaInterrupcion.ENLACE_CLIENTE


def test_un_archivo_que_no_es_imagen_se_rechaza(app, despachador, nueva_orden):
    from tests.conftest import ArchivoFalso

    with pytest.raises(servicio.DatosInvalidos):
        nueva_orden(despachador, foto_anverso=ArchivoFalso("x.jpg", b"no soy jpeg"))


def test_una_extension_no_admitida_se_rechaza(app, despachador, nueva_orden):
    from tests.conftest import ArchivoFalso, imagen_jpeg

    with pytest.raises(servicio.DatosInvalidos, match="jpg|png|webp|extension"):
        nueva_orden(despachador, foto_anverso=ArchivoFalso("x.gif", imagen_jpeg()))


# ---------------------------------------------------------------------------
# Comentarios y clasificacion: reglas del servicio
# ---------------------------------------------------------------------------
def test_un_ticket_cerrado_todavia_se_puede_comentar(
    cliente, nueva_orden, despachador, operador
):
    """A proposito: el comentario no cambia el estado y queda en la bitacora.

    Lo que si esta bloqueado con el ticket cerrado son las fotos y la
    dependencia, que si alterarian el expediente.
    """
    orden = nueva_orden(despachador, asignado_a=operador)
    ejecutar_transicion(orden, operador, "estado:EN_PROCESO")
    ejecutar_transicion(orden, operador, "estado:OK_OPERADOR", comentario="listo")
    ejecutar_transicion(orden, despachador, "estado:CERRADA", comentario="en SIPREC")
    db.session.commit()

    servicio.comentar(orden, operador, "El cliente llamo para agradecer")
    assert orden.comentarios[-1].texto == "El cliente llamo para agradecer"
    assert orden.estado.name == "CERRADA"

    # Y el formulario sigue ofreciendose en el detalle, coherente con eso.
    entrar(cliente, despachador)
    assert 'name="texto"' in texto(cliente, orden.url_detalle)


def test_un_comentario_vacio_se_rechaza_en_el_servicio(
    app, nueva_orden, despachador, operador
):
    orden = nueva_orden(despachador, asignado_a=operador)
    db.session.commit()
    with pytest.raises(servicio.DatosInvalidos):
        servicio.comentar(orden, operador, "   ")


def test_la_dependencia_no_se_toca_con_la_interrupcion_cerrada(
    app, nueva_interrupcion, despachador, operador
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:CERRADA",
        comentario="resuelto", dependencia=Dependencia.CORE_IPMPLS,
    )
    db.session.commit()

    with pytest.raises(TransicionInvalida, match="cerrada"):
        servicio.clasificar_dependencia(inter, operador, Dependencia.DISTRIBUCION)


def test_una_dependencia_invalida_se_rechaza(
    app, nueva_interrupcion, despachador, operador
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    db.session.commit()
    with pytest.raises(servicio.DatosInvalidos, match="dependencia valida"):
        servicio.clasificar_dependencia(inter, operador, "LO_QUE_SEA")


def test_reclasificar_a_lo_mismo_no_escribe_historial(
    app, nueva_interrupcion, despachador, operador
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    servicio.clasificar_dependencia(inter, operador, Dependencia.CORE_IPMPLS)
    cuantos = len([h for h in inter.historial if h.campo == "dependencia"])

    servicio.clasificar_dependencia(inter, operador, Dependencia.CORE_IPMPLS)
    assert len([h for h in inter.historial if h.campo == "dependencia"]) == cuantos


def test_una_categoria_invalida_se_rechaza(app, nueva_interrupcion, despachador):
    inter = nueva_interrupcion(despachador)
    with pytest.raises(servicio.DatosInvalidos, match="categoria valida"):
        servicio.actualizar_categoria(inter, despachador, "LO_QUE_SEA")


def test_la_categoria_de_una_cerrada_no_se_cambia(
    app, nueva_interrupcion, despachador, operador
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    ejecutar_transicion(inter, operador, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, operador, "estado:CERRADA",
        comentario="resuelto", dependencia=Dependencia.CORE_IPMPLS,
    )
    db.session.commit()

    with pytest.raises(TransicionInvalida, match="cerrada"):
        servicio.actualizar_categoria(inter, despachador, "SITIO_WIFI")


def test_poner_la_categoria_que_ya_tiene_no_hace_nada(
    app, nueva_interrupcion, despachador
):
    inter = nueva_interrupcion(despachador)
    servicio.actualizar_categoria(inter, despachador, "ENLACE_CLIENTE")
    assert [h for h in inter.historial if h.campo == "categoria"] == []


def test_el_telefono_igual_no_escribe_historial(app, nueva_orden, despachador):
    orden = nueva_orden(despachador, telefono_contacto="0414-1234567")
    db.session.commit()
    servicio.actualizar_telefono(orden, despachador, "0414-1234567")
    assert [h for h in orden.historial if h.campo == "telefono_contacto"] == []


def test_un_asignado_inactivo_no_bloquea_la_categoria(
    app, nueva_interrupcion, despachador
):
    """Lo que toca con un asignado inactivo es reasignar, no trabarse."""
    tecnico = crear_usuario("wifi_inactivo", RolUsuario.TECNICO_WIFI)
    inter = nueva_interrupcion(despachador, categoria="SITIO_WIFI")
    ejecutar_transicion(inter, despachador, "estado:ASIGNADA", asignado_a=tecnico)
    db.session.commit()

    tecnico.activo = False
    db.session.commit()

    servicio.actualizar_categoria(inter, despachador, "ENLACE_CLIENTE")
    assert inter.es_sitio_wifi is False


# ---------------------------------------------------------------------------
# Endpoints de interrupcion
# ---------------------------------------------------------------------------
def test_se_reasigna_una_interrupcion_por_http(
    cliente, nueva_interrupcion, despachador, operador, operador_b
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, despachador)
    cliente.post(
        f"/interrupciones/{inter.id}/reasignar",
        data={"nuevo_operador_id": str(operador_b.id)}, follow_redirects=True,
    )
    db.session.refresh(inter)
    assert inter.asignado_a_id == operador_b.id


def test_se_corrige_el_telefono_de_una_interrupcion_por_http(
    cliente, nueva_interrupcion, despachador
):
    inter = nueva_interrupcion(despachador, telefono_contacto=None)
    db.session.commit()

    entrar(cliente, despachador)
    cliente.post(
        f"/interrupciones/{inter.id}/telefono",
        data={"telefono_contacto": "0212-7778899"}, follow_redirects=True,
    )
    db.session.refresh(inter)
    assert inter.telefono_contacto == "0212-7778899"


def test_se_cambia_la_foto_de_una_interrupcion_por_http(
    cliente, nueva_interrupcion, despachador
):
    import io

    from tests.conftest import imagen_jpeg

    inter = nueva_interrupcion(despachador)
    db.session.commit()
    clave_previa = inter.foto_key

    entrar(cliente, despachador)
    cliente.post(
        f"/interrupciones/{inter.id}/foto/foto",
        data={"foto": (io.BytesIO(imagen_jpeg()), "nueva.jpg")},
        content_type="multipart/form-data", follow_redirects=True,
    )
    db.session.refresh(inter)
    assert inter.foto_key != clave_previa
    assert any(h.campo == "foto_foto" for h in inter.historial)


def test_una_dependencia_invalida_por_http_solo_avisa(
    cliente, nueva_interrupcion, despachador, operador
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, operador)
    respuesta = cliente.post(
        f"/interrupciones/{inter.id}/dependencia",
        data={"dependencia": "LO_QUE_SEA"}, follow_redirects=True,
    )
    assert respuesta.status_code == 200
    assert "dependencia valida" in respuesta.get_data(as_text=True)
    db.session.refresh(inter)
    assert inter.dependencia is None


def test_un_ajeno_no_clasifica_la_dependencia(
    cliente, nueva_interrupcion, despachador, operador, operador_b
):
    inter = nueva_interrupcion(despachador, asignado_a=operador)
    db.session.commit()

    entrar(cliente, operador_b)
    assert cliente.post(
        f"/interrupciones/{inter.id}/dependencia", data={"dependencia": "CORE_IPMPLS"}
    ).status_code == 403


def test_una_categoria_invalida_por_http_solo_avisa(
    cliente, nueva_interrupcion, despachador
):
    inter = nueva_interrupcion(despachador)
    db.session.commit()

    entrar(cliente, despachador)
    respuesta = cliente.post(
        f"/interrupciones/{inter.id}/categoria",
        data={"categoria": "LO_QUE_SEA"}, follow_redirects=True,
    )
    assert "categoria valida" in respuesta.get_data(as_text=True)
    db.session.refresh(inter)
    assert inter.es_sitio_wifi is False


# ---------------------------------------------------------------------------
# Restablecer contrasenas desde la pantalla de admin
# ---------------------------------------------------------------------------
def test_el_admin_escribe_una_clave_nueva(cliente, admin, operador):
    entrar(cliente, admin)
    respuesta = cliente.post(
        f"/admin/usuarios/{operador.id}/restablecer-password",
        data={"password": "ClaveFijada.1"}, follow_redirects=True,
    )
    assert "restablecida" in respuesta.get_data(as_text=True)
    db.session.refresh(operador)
    assert operador.check_password("ClaveFijada.1")
    assert operador.debe_cambiar_password is True


def test_el_admin_genera_una_clave_temporal(cliente, admin, operador):
    entrar(cliente, admin)
    respuesta = cliente.post(
        f"/admin/usuarios/{operador.id}/restablecer-password",
        data={"generar": "1"}, follow_redirects=True,
    )
    cuerpo = respuesta.get_data(as_text=True)
    assert "temporal" in cuerpo
    assert "no se vuelve a mostrar" in cuerpo
    db.session.refresh(operador)
    assert operador.debe_cambiar_password is True
    assert not operador.check_password(CLAVE)


def test_una_clave_corta_se_rechaza(cliente, admin, operador):
    entrar(cliente, admin)
    respuesta = cliente.post(
        f"/admin/usuarios/{operador.id}/restablecer-password",
        data={"password": "corta"}, follow_redirects=True,
    )
    assert "al menos 8" in respuesta.get_data(as_text=True)
    db.session.refresh(operador)
    assert operador.check_password(CLAVE)


def test_el_admin_cambiando_la_suya_no_queda_obligado(cliente, admin):
    entrar(cliente, admin)
    cliente.post(
        f"/admin/usuarios/{admin.id}/restablecer-password",
        data={"password": "MiClaveNueva.1"}, follow_redirects=True,
    )
    db.session.refresh(admin)
    assert admin.check_password("MiClaveNueva.1")
    assert admin.debe_cambiar_password is False


def test_restablecer_a_quien_no_existe_da_404(cliente, admin):
    entrar(cliente, admin)
    assert cliente.post(
        "/admin/usuarios/987654/restablecer-password", data={"generar": "1"}
    ).status_code == 404


def test_solo_un_admin_restablece(cliente, despachador, operador):
    entrar(cliente, despachador)
    assert cliente.post(
        f"/admin/usuarios/{operador.id}/restablecer-password", data={"generar": "1"}
    ).status_code == 403


def test_el_servicio_exige_rol_de_admin(app, despachador, operador):
    with pytest.raises(servicio_usuarios.ErrorUsuario, match="administrador"):
        servicio_usuarios.restablecer_password(operador, despachador, password="X" * 10)


def test_la_clave_generada_es_legible(app):
    clave = servicio_usuarios.generar_password()
    assert len(clave.split("-")) == 3
    assert all(len(parte) == 4 for parte in clave.split("-"))
    # Sin caracteres que se confundan al dictarlos.
    assert not set(clave) & set("0O1lI")


def test_dos_claves_generadas_no_coinciden(app):
    claves = {servicio_usuarios.generar_password() for _ in range(20)}
    assert len(claves) == 20


def test_quien_viene_de_un_restablecimiento_no_da_la_actual(app, admin, operador):
    servicio_usuarios.restablecer_password(operador, admin, password="Temporal.123")
    assert operador.debe_cambiar_password is True

    # No se le pide la actual, justo porque la fijo el administrador.
    servicio_usuarios.cambiar_password_propia(
        operador, None, "LaMia.456789", "LaMia.456789"
    )
    assert operador.debe_cambiar_password is False
    assert operador.check_password("LaMia.456789")


# ---------------------------------------------------------------------------
# Un usuario con todos los roles a la vez
# ---------------------------------------------------------------------------
def test_un_usuario_con_los_cinco_roles_no_se_contradice(
    app, nueva_orden, nueva_interrupcion
):
    """Los permisos son la union: tener todo no debe romper ninguna regla."""
    todopoderoso = crear_usuario("todo", *list(RolUsuario))
    orden = nueva_orden(todopoderoso, asignado_a=todopoderoso)
    inter = nueva_interrupcion(
        todopoderoso, asignado_a=todopoderoso, categoria="SITIO_WIFI"
    )
    db.session.commit()

    ejecutar_transicion(orden, todopoderoso, "estado:EN_PROCESO")
    ejecutar_transicion(orden, todopoderoso, "estado:OK_OPERADOR", comentario="ok")
    ejecutar_transicion(orden, todopoderoso, "estado:CERRADA", comentario="en SIPREC")
    assert orden.estado.name == "CERRADA"

    ejecutar_transicion(inter, todopoderoso, "estado:EN_PROCESO")
    ejecutar_transicion(
        inter, todopoderoso, "estado:DERIVADA_FIBRA",
        comentario="corte", dependencia=Dependencia.CAPA_FISICA,
    )
    ejecutar_transicion(
        inter, todopoderoso, "estado_fibra:FIBRA_OK", comentario="medido"
    )
    ejecutar_transicion(inter, todopoderoso, "estado:CERRADA", comentario="cerrada")
    assert inter.estado.name == "CERRADA"

"""Acceso al object storage.

El resto de la suite sustituye el almacen por uno en memoria (fixture
`almacen`, autouse). Aqui se deshacen esos parches con `monkeypatch.undo()`
para ejercitar el codigo real contra un cliente S3 simulado.
"""
from __future__ import annotations

import io

import pytest
from botocore.exceptions import ClientError
from PIL import Image

from app.services import storage


def imagen(ancho=60, alto=40, formato="JPEG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (ancho, alto), (10, 120, 90)).save(buffer, format=formato)
    return buffer.getvalue()


def error_s3(operacion="PutObject"):
    return ClientError({"Error": {"Code": "500", "Message": "falla"}}, operacion)


class S3Falso:
    """Lo minimo del cliente de boto3 que usa el modulo."""

    def __init__(self) -> None:
        self.objetos: dict[str, dict] = {}
        self.bucket_existe = True
        self.fallar_put = False
        self.fallar_create = False
        self.firmas: list[tuple[str, int]] = []

    def put_object(self, **kwargs):
        if self.fallar_put:
            raise error_s3()
        self.objetos[kwargs["Key"]] = kwargs
        return {}

    def head_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objetos:
            raise error_s3("HeadObject")
        return {}

    def delete_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objetos:
            raise error_s3("DeleteObject")
        del self.objetos[Key]
        return {}

    def head_bucket(self, Bucket):  # noqa: N803
        if not self.bucket_existe:
            raise error_s3("HeadBucket")
        return {}

    def create_bucket(self, Bucket):  # noqa: N803
        if self.fallar_create:
            raise error_s3("CreateBucket")
        self.bucket_existe = True
        return {}

    def generate_presigned_url(self, operacion, Params, ExpiresIn):  # noqa: N803
        self.firmas.append((Params["Key"], ExpiresIn))
        return f"http://publico/{Params['Bucket']}/{Params['Key']}?exp={ExpiresIn}"


@pytest.fixture
def s3(app, monkeypatch):
    """Devuelve el almacen real enchufado a un cliente simulado."""
    monkeypatch.undo()  # quita el almacen en memoria de conftest
    falso = S3Falso()
    app.extensions["s3_interno"] = falso
    app.extensions["s3_publico"] = falso
    yield falso
    app.extensions.pop("s3_interno", None)
    app.extensions.pop("s3_publico", None)


# ---------------------------------------------------------------------------
# Utilidades puras
# ---------------------------------------------------------------------------
def test_extension_de():
    assert storage.extension_de("foto.JPG") == "jpg"
    assert storage.extension_de("carpeta/foto.jpeg") == "jpeg"
    assert storage.extension_de("sin-punto") == ""
    assert storage.extension_de("doble.tar.gz") == "gz"


def test_tipo_mime():
    assert storage.tipo_mime("jpg") == "image/jpeg"
    assert storage.tipo_mime("jpeg") == "image/jpeg"
    assert storage.tipo_mime("png") == "image/png"
    assert storage.tipo_mime("webp") == "image/webp"
    assert storage.tipo_mime("exe") == "application/octet-stream"


# ---------------------------------------------------------------------------
# Normalizacion de imagenes
# ---------------------------------------------------------------------------
def test_una_imagen_grande_se_reduce(app):
    maximo = app.config["FOTO_MAX_PIXELES"]
    datos, extension = storage.normalizar_imagen(
        imagen(maximo + 800, maximo + 400), "jpg"
    )
    assert extension == "jpg"
    with Image.open(io.BytesIO(datos)) as img:
        assert max(img.size) == maximo


def test_una_imagen_pequena_no_se_agranda(app):
    datos, _ = storage.normalizar_imagen(imagen(60, 40), "jpg")
    with Image.open(io.BytesIO(datos)) as img:
        assert img.size == (60, 40)


def test_cada_formato_conserva_el_suyo(app):
    for formato, extension in (("PNG", "png"), ("WEBP", "webp")):
        datos, salida = storage.normalizar_imagen(imagen(formato=formato), extension)
        assert salida == extension
        with Image.open(io.BytesIO(datos)) as img:
            assert img.format == formato


def test_cualquier_otro_formato_sale_como_jpg(app):
    datos, extension = storage.normalizar_imagen(imagen(formato="BMP"), "bmp")
    assert extension == "jpg"
    with Image.open(io.BytesIO(datos)) as img:
        assert img.format == "JPEG"


def test_lo_que_no_es_imagen_se_rechaza(app):
    with pytest.raises(storage.ErrorAlmacenamiento, match="no es una imagen"):
        storage.normalizar_imagen(b"esto es un texto, no una foto", "jpg")


def test_un_archivo_vacio_se_rechaza(app):
    with pytest.raises(storage.ErrorAlmacenamiento):
        storage.normalizar_imagen(b"", "jpg")


# ---------------------------------------------------------------------------
# Subir
# ---------------------------------------------------------------------------
def test_subir_guarda_con_su_tipo_y_cache(app, s3):
    clave = storage.subir("ordenes/OT-1/anverso.jpg", b"contenido", "jpg")
    assert clave == "ordenes/OT-1/anverso.jpg"

    guardado = s3.objetos[clave]
    assert guardado["Body"] == b"contenido"
    assert guardado["ContentType"] == "image/jpeg"
    assert "private" in guardado["CacheControl"]
    assert guardado["Bucket"] == app.config["S3_BUCKET"]


def test_si_el_storage_falla_al_subir_se_avisa(app, s3):
    s3.fallar_put = True
    with pytest.raises(storage.ErrorAlmacenamiento, match="no se pudo subir"):
        storage.subir("x.jpg", b"datos", "jpg")


# ---------------------------------------------------------------------------
# Firmar
# ---------------------------------------------------------------------------
def test_la_url_firmada_usa_la_expiracion_configurada(app, s3):
    url = storage.url_prefirmada("ordenes/OT-1/anverso.jpg")
    assert url.startswith("http://publico/")
    assert s3.firmas[-1] == ("ordenes/OT-1/anverso.jpg", app.config["S3_URL_EXPIRACION"])


def test_se_puede_pedir_otra_expiracion(app, s3):
    storage.url_prefirmada("x.jpg", 60)
    assert s3.firmas[-1][1] == 60


def test_sin_clave_no_hay_url(app, s3):
    assert storage.url_prefirmada("") is None
    assert storage.url_prefirmada(None) is None
    assert s3.firmas == []


def test_si_no_se_puede_firmar_devuelve_none(app, s3, monkeypatch):
    def explotar(*args, **kwargs):
        raise error_s3("GetObject")

    monkeypatch.setattr(s3, "generate_presigned_url", explotar)
    assert storage.url_prefirmada("x.jpg") is None


# ---------------------------------------------------------------------------
# Eliminar y comprobar
# ---------------------------------------------------------------------------
def test_eliminar_borra_el_objeto(app, s3):
    storage.subir("x.jpg", b"datos", "jpg")
    storage.eliminar("x.jpg")
    assert "x.jpg" not in s3.objetos


def test_eliminar_lo_que_no_esta_no_revienta(app, s3):
    storage.eliminar("no-existe.jpg")  # solo deja un aviso en el log
    storage.eliminar("")
    storage.eliminar(None)


def test_existe(app, s3):
    assert storage.existe("x.jpg") is False
    storage.subir("x.jpg", b"datos", "jpg")
    assert storage.existe("x.jpg") is True


# ---------------------------------------------------------------------------
# Bucket
# ---------------------------------------------------------------------------
def test_si_el_bucket_esta_no_se_crea(app, s3):
    storage.asegurar_bucket()
    assert s3.bucket_existe is True


def test_si_no_esta_se_crea(app, s3):
    s3.bucket_existe = False
    storage.asegurar_bucket()
    assert s3.bucket_existe is True


def test_si_no_se_puede_crear_se_avisa(app, s3):
    s3.bucket_existe = False
    s3.fallar_create = True
    with pytest.raises(storage.ErrorAlmacenamiento, match="no se pudo crear el bucket"):
        storage.asegurar_bucket()


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
def test_son_dos_clientes_distintos_y_se_reutilizan(app, monkeypatch):
    """El interno sube; el publico firma lo que abrira el navegador."""
    monkeypatch.undo()
    app.extensions.pop("s3_interno", None)
    app.extensions.pop("s3_publico", None)

    creados = []

    def falso_crear(endpoint):
        creados.append(endpoint)
        return S3Falso()

    monkeypatch.setattr(storage, "_crear_cliente", falso_crear)

    primero = storage.cliente_interno()
    assert storage.cliente_interno() is primero, "se cachea en la aplicacion"
    publico = storage.cliente_publico()
    assert publico is not primero

    assert creados == [
        app.config["S3_ENDPOINT_URL"],
        app.config["S3_PUBLIC_ENDPOINT"],
    ]
    app.extensions.pop("s3_interno", None)
    app.extensions.pop("s3_publico", None)

"""Acceso al object storage (Garage, compatible con S3).

Dos clientes distintos a proposito:

* `cliente_interno`  usa S3_ENDPOINT_URL (http://garage:3900) y sirve para
  subir y borrar objetos desde el contenedor de Flask.
* `cliente_publico`  usa S3_PUBLIC_ENDPOINT (http://localhost:3900) y se usa
  UNICAMENTE para firmar las URL que abrira el navegador. Firmar con el
  endpoint interno produce URL que el navegador no puede resolver.
"""
from __future__ import annotations

import io
import logging

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
from flask import current_app

log = logging.getLogger(__name__)

_TIPOS = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


class ErrorAlmacenamiento(Exception):
    """Fallo al hablar con el object storage."""


def _crear_cliente(endpoint: str):
    cfg = current_app.config
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=cfg["S3_REGION"],
        aws_access_key_id=cfg["S3_ACCESS_KEY"],
        aws_secret_access_key=cfg["S3_SECRET_KEY"],
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def cliente_interno():
    if "s3_interno" not in current_app.extensions:
        current_app.extensions["s3_interno"] = _crear_cliente(
            current_app.config["S3_ENDPOINT_URL"]
        )
    return current_app.extensions["s3_interno"]


def cliente_publico():
    if "s3_publico" not in current_app.extensions:
        current_app.extensions["s3_publico"] = _crear_cliente(
            current_app.config["S3_PUBLIC_ENDPOINT"]
        )
    return current_app.extensions["s3_publico"]


def bucket() -> str:
    return current_app.config["S3_BUCKET"]


def asegurar_bucket() -> None:
    """Crea el bucket si no existe. El init de Garage ya lo hace; esto cubre
    despliegues donde el storage se administra por fuera."""
    s3 = cliente_interno()
    try:
        s3.head_bucket(Bucket=bucket())
    except ClientError:
        try:
            s3.create_bucket(Bucket=bucket())
            log.info("bucket %s creado", bucket())
        except ClientError as exc:
            raise ErrorAlmacenamiento(f"no se pudo crear el bucket: {exc}") from exc


def extension_de(nombre: str) -> str:
    return (nombre.rsplit(".", 1)[-1] if "." in nombre else "").lower()


def tipo_mime(extension: str) -> str:
    return _TIPOS.get(extension, "application/octet-stream")


def normalizar_imagen(datos: bytes, extension: str) -> tuple[bytes, str]:
    """Reduce la imagen al lado maximo configurado y la reencoda.

    Ademas actua como validacion real del contenido: si Pillow no puede abrir
    el archivo, no era una imagen por mas que la extension dijera otra cosa.
    """
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(datos)) as img:
            img = ImageOps.exif_transpose(img)
            maximo = current_app.config["FOTO_MAX_PIXELES"]
            if max(img.size) > maximo:
                img.thumbnail((maximo, maximo), Image.LANCZOS)
            salida = io.BytesIO()
            if extension == "png":
                img.save(salida, format="PNG", optimize=True)
                return salida.getvalue(), "png"
            if extension == "webp":
                img.save(salida, format="WEBP", quality=85)
                return salida.getvalue(), "webp"
            img.convert("RGB").save(salida, format="JPEG", quality=85, optimize=True)
            return salida.getvalue(), "jpg"
    except Exception as exc:  # noqa: BLE001
        raise ErrorAlmacenamiento(
            "El archivo no es una imagen valida (jpg, png o webp)."
        ) from exc


def subir(clave: str, datos: bytes, extension: str) -> str:
    s3 = cliente_interno()
    try:
        s3.put_object(
            Bucket=bucket(),
            Key=clave,
            Body=datos,
            ContentType=tipo_mime(extension),
            CacheControl="private, max-age=300",
        )
    except ClientError as exc:
        raise ErrorAlmacenamiento(f"no se pudo subir {clave}: {exc}") from exc
    return clave


def url_prefirmada(clave: str, segundos: int | None = None) -> str | None:
    if not clave:
        return None
    segundos = segundos or current_app.config["S3_URL_EXPIRACION"]
    try:
        return cliente_publico().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket(), "Key": clave},
            ExpiresIn=segundos,
        )
    except ClientError as exc:
        log.warning("no se pudo firmar %s: %s", clave, exc)
        return None


def eliminar(clave: str) -> None:
    if not clave:
        return
    try:
        cliente_interno().delete_object(Bucket=bucket(), Key=clave)
    except ClientError as exc:
        log.warning("no se pudo eliminar %s: %s", clave, exc)


def existe(clave: str) -> bool:
    try:
        cliente_interno().head_object(Bucket=bucket(), Key=clave)
        return True
    except ClientError:
        return False

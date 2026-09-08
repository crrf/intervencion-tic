#!/bin/sh
# ---------------------------------------------------------------------------
# Inicializacion idempotente de Garage: layout + bucket + llave de acceso.
# Se ejecuta una sola vez por "docker compose up" y puede repetirse sin danar
# nada: cada paso comprueba antes si ya esta hecho.
#
# Sintaxis verificada contra garage v1.0.1:
#   garage layout assign -z <zona> -c <capacidad con sufijo> <node-id>
#   garage layout apply --version <n>
#   garage bucket create <bucket>
#   garage key import --yes -n <nombre> <key-id> <secret-key>
#   garage bucket allow --read --write --owner --key <key-id> <bucket>
# Si se cambia la version de Garage, revalidar estos flags.
# ---------------------------------------------------------------------------
set -eu

ZONA="${GARAGE_ZONE:-dc1}"
CAPACIDAD="${GARAGE_CAPACITY:-10GB}"
BUCKET="${S3_BUCKET:-tickets-adjuntos}"
ACCESS_KEY="${S3_ACCESS_KEY:?falta S3_ACCESS_KEY}"
SECRET_KEY="${S3_SECRET_KEY:?falta S3_SECRET_KEY}"
NOMBRE_LLAVE="app-tickets"

log() { echo "[garage-init] $*"; }

# --- 1. Esperar a que el nodo responda por RPC -----------------------------
log "esperando a que el nodo de Garage responda..."
intento=0
until garage status >/dev/null 2>&1; do
  intento=$((intento + 1))
  if [ "$intento" -ge 60 ]; then
    log "ERROR: Garage no respondio tras 60 intentos"
    garage status || true
    exit 1
  fi
  sleep 2
done
log "nodo disponible"

# --- 2. Layout del cluster -------------------------------------------------
if garage layout show 2>&1 | grep -qi "no nodes currently have a role"; then
  NODE_ID="$(garage node id -q 2>/dev/null | cut -d@ -f1)"
  if [ -z "$NODE_ID" ]; then
    log "ERROR: no se pudo obtener el node id"
    exit 1
  fi
  log "asignando rol al nodo ${NODE_ID} (zona=${ZONA}, capacidad=${CAPACIDAD})"
  garage layout assign -z "$ZONA" -c "$CAPACIDAD" "$NODE_ID"

  # Garage exige que --version sea exactamente la version previa + 1.
  VERSION="$(garage layout show 2>&1 | grep -oE 'apply --version [0-9]+' | grep -oE '[0-9]+$' | tail -1)"
  log "aplicando layout version ${VERSION:-1}"
  garage layout apply --version "${VERSION:-1}"
else
  log "el layout ya estaba configurado, se omite"
fi

# --- 3. Bucket -------------------------------------------------------------
if garage bucket list 2>/dev/null | grep -qw "$BUCKET"; then
  log "el bucket '${BUCKET}' ya existe"
else
  log "creando bucket '${BUCKET}'"
  garage bucket create "$BUCKET"
fi

# --- 4. Llave de acceso ----------------------------------------------------
# Se importa con un access/secret fijos para que coincidan con el .env de la
# aplicacion; 'garage key create' generaria unos aleatorios cada vez.
if garage key list 2>/dev/null | grep -q "$ACCESS_KEY"; then
  log "la llave '${ACCESS_KEY}' ya existe"
else
  log "importando llave '${ACCESS_KEY}'"
  garage key import --yes -n "$NOMBRE_LLAVE" "$ACCESS_KEY" "$SECRET_KEY"
fi

# --- 5. Permisos de la llave sobre el bucket -------------------------------
log "otorgando permisos read/write/owner sobre '${BUCKET}'"
garage bucket allow --read --write --owner --key "$ACCESS_KEY" "$BUCKET"

log "inicializacion completada"
garage bucket info "$BUCKET" || true

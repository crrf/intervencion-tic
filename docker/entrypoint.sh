#!/bin/sh
# Espera a PostgreSQL, aplica las migraciones, siembra datos si corresponde
# y finalmente cede el proceso al comando recibido (gunicorn por defecto).
set -eu

echo "[entrypoint] esperando a PostgreSQL..."
python - <<'PY'
import os, sys, time
import psycopg

url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
for intento in range(60):
    try:
        with psycopg.connect(url, connect_timeout=3):
            print("[entrypoint] PostgreSQL disponible")
            sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        if intento % 5 == 0:
            print(f"[entrypoint] aun no responde ({exc.__class__.__name__}), reintentando...")
        time.sleep(2)
print("[entrypoint] ERROR: PostgreSQL no respondio a tiempo", file=sys.stderr)
sys.exit(1)
PY

echo "[entrypoint] aplicando migraciones..."
flask db upgrade

# Produccion: solo la cuenta de administrador, sin datos de ejemplo.
if [ "${CREAR_ADMIN:-false}" = "true" ]; then
  echo "[entrypoint] asegurando la cuenta de administrador..."
  flask crear-admin ${ADMIN_FORZAR_CAMBIO:+--forzar-cambio}
fi

# Desarrollo/demostracion: usuarios y tickets de ejemplo.
if [ "${SEED_ON_START:-false}" = "true" ]; then
  echo "[entrypoint] sembrando datos de ejemplo (idempotente)..."
  flask seed
fi

echo "[entrypoint] arrancando: $*"
exec "$@"

#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Despliegue de produccion del Sistema de Tickets e Incidencias.
#
#   - NO siembra datos de ejemplo: la base arranca vacia.
#   - Crea unicamente la cuenta de administrador; el resto de los usuarios los
#     da de alta ese administrador desde la aplicacion.
#   - Genera secretos aleatorios reales la primera vez y los guarda en .env.
#   - Es seguro repetirlo: si ya existe .env no lo pisa, y sirve para
#     actualizar la aplicacion sin tocar los datos.
#
# Uso:
#   ./desplegar.sh                  despliegue interactivo (recomendado)
#   ./desplegar.sh --sin-preguntas  usa los valores por defecto o los del entorno
#   ./desplegar.sh --actualizar     reconstruye y reinicia sin preguntar nada
#   ./desplegar.sh --ayuda
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")"

readonly ENV_FILE=".env"
readonly ENV_EJEMPLO=".env.example"

INTERACTIVO=1
SOLO_ACTUALIZAR=0

for arg in "$@"; do
  case "$arg" in
    --sin-preguntas|-y) INTERACTIVO=0 ;;
    --actualizar|-u)    INTERACTIVO=0; SOLO_ACTUALIZAR=1 ;;
    --ayuda|-h|--help)
      awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"
      exit 0 ;;
    *) echo "Opcion desconocida: $arg (usa --ayuda)" >&2; exit 2 ;;
  esac
done

# --- Salida ----------------------------------------------------------------
if [ -t 1 ]; then
  AZUL=$'\033[1;34m'; VERDE=$'\033[1;32m'; AMBAR=$'\033[1;33m'
  ROJO=$'\033[1;31m'; GRIS=$'\033[0;90m'; FIN=$'\033[0m'
else
  AZUL=""; VERDE=""; AMBAR=""; ROJO=""; GRIS=""; FIN=""
fi

paso()  { printf '\n%s==>%s %s\n' "$AZUL" "$FIN" "$1"; }
ok()    { printf '  %s[ok]%s %s\n' "$VERDE" "$FIN" "$1"; }
aviso() { printf '  %s[!]%s  %s\n' "$AMBAR" "$FIN" "$1"; }
nota()  { printf '  %s%s%s\n' "$GRIS" "$1" "$FIN"; }
fallar(){ printf '\n%s[error]%s %s\n\n' "$ROJO" "$FIN" "$1" >&2; exit 1; }

preguntar() {  # preguntar <texto> <valor por defecto>
  local texto="$1" defecto="$2" respuesta
  if [ "$INTERACTIVO" -eq 0 ]; then printf '%s' "$defecto"; return; fi
  read -r -p "    $texto [$defecto]: " respuesta </dev/tty || respuesta=""
  printf '%s' "${respuesta:-$defecto}"
}

# --- Generacion de secretos ------------------------------------------------
# Garage exige formatos exactos: el access key es GK + 24 hexadecimales y el
# secret key y el rpc_secret son 64 hexadecimales. No son cadenas cualesquiera.
hex() {  # hex <cantidad de bytes>
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  elif [ -r /dev/urandom ]; then
    od -An -tx1 -N "$1" /dev/urandom | tr -d ' \n'
  else
    fallar "No hay openssl ni /dev/urandom para generar secretos."
  fi
}

password_legible() {  # sin caracteres que se confundan al dictarlos
  local alfabeto="ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
  local salida="" i
  for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
    local n=$(( ( $(od -An -N1 -tu1 /dev/urandom | tr -d ' ') ) % ${#alfabeto} ))
    salida="${salida}${alfabeto:$n:1}"
    if [ "$i" = 4 ] || [ "$i" = 8 ]; then salida="${salida}-"; fi
  done
  printf '%s' "$salida"
}

fijar() {  # fijar <CLAVE> <valor>  -- reemplaza o agrega en .env
  local clave="$1" valor="$2"
  if grep -q "^${clave}=" "$ENV_FILE"; then
    # Se usa un archivo temporal para no depender del sed -i de cada sistema.
    awk -v c="$clave" -v v="$valor" \
      'BEGIN{FS=OFS="="} $1==c {print c "=" v; hecho=1; next} {print} END{if(!hecho) print c "=" v}' \
      "$ENV_FILE" > "$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE"
  else
    printf '%s=%s\n' "$clave" "$valor" >> "$ENV_FILE"
  fi
}

leer() {  # leer <CLAVE>
  grep "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true
}

# ---------------------------------------------------------------------------
printf '\n%s  Sistema de Tickets e Incidencias  ·  despliegue de produccion%s\n' "$AZUL" "$FIN"

# --- 1. Requisitos ---------------------------------------------------------
paso "Comprobando requisitos"
command -v docker >/dev/null 2>&1 || fallar "Docker no esta instalado o no esta en el PATH."
docker compose version >/dev/null 2>&1 || fallar "Falta el plugin 'docker compose' (v2)."
docker info >/dev/null 2>&1 || fallar "El demonio de Docker no responde. Arrancalo y repite."
ok "docker $(docker --version | awk '{print $3}' | tr -d ,)"
ok "compose $(docker compose version --short 2>/dev/null || echo v2)"

# --- 2. Configuracion ------------------------------------------------------
ADMIN_PASSWORD_NUEVA=""

if [ -f "$ENV_FILE" ]; then
  paso "Configuracion"
  ok "$ENV_FILE ya existe: se respeta tal cual (no se regeneran secretos)"
  if [ "$(leer SEED_ON_START)" = "true" ] && [ "$SOLO_ACTUALIZAR" -eq 0 ]; then
    aviso "SEED_ON_START=true sembraria datos de EJEMPLO."
    if [ "$INTERACTIVO" -eq 1 ]; then
      resp=$(preguntar "Desactivarlo para produccion? (s/n)" "s")
      case "$resp" in [sS]*) fijar SEED_ON_START false; ok "SEED_ON_START=false" ;; esac
    else
      aviso "Se deja como esta. Ponlo en false a mano para un despliegue limpio."
    fi
  fi
  fijar CREAR_ADMIN true
else
  [ -f "$ENV_EJEMPLO" ] || fallar "No se encuentra $ENV_EJEMPLO."

  paso "Creando $ENV_FILE con secretos nuevos"
  cp "$ENV_EJEMPLO" "$ENV_FILE"
  chmod 600 "$ENV_FILE" 2>/dev/null || true

  fijar FLASK_ENV production
  fijar SECRET_KEY            "$(hex 32)"
  fijar POSTGRES_PASSWORD     "$(hex 16)"
  fijar GARAGE_RPC_SECRET     "$(hex 32)"
  fijar GARAGE_ADMIN_TOKEN    "$(hex 24)"
  fijar S3_ACCESS_KEY         "GK$(hex 12)"
  fijar S3_SECRET_KEY         "$(hex 32)"
  ok "secretos aleatorios generados"

  # La URL de la base tiene que llevar la contrasena recien generada.
  USUARIO_BD="$(leer POSTGRES_USER)"
  BASE_BD="$(leer POSTGRES_DB)"
  fijar DATABASE_URL "postgresql+psycopg://${USUARIO_BD}:$(leer POSTGRES_PASSWORD)@db:5432/${BASE_BD}"
  ok "DATABASE_URL enlazada a la contrasena nueva"

  # Nunca datos de ejemplo en produccion.
  fijar SEED_ON_START false
  fijar CREAR_ADMIN true
  fijar SEED_PASSWORD ""
  ok "sin datos de ejemplo: solo se creara la cuenta de administrador"

  if [ "$INTERACTIVO" -eq 1 ]; then
    printf '\n  %sResponde estas cuatro preguntas (Enter acepta el valor entre corchetes):%s\n' "$AMBAR" "$FIN"
  fi

  # El valor sugerido sale de una variable de entorno exportada si la hay, y
  # si no del .env.example. Asi un despliegue desatendido se puede preparar de
  # antemano en cualquiera de los dos sitios.
  TZ_APP=$(preguntar "Zona horaria del grupo (ej. America/Caracas)" "${APP_TZ:-$(leer APP_TZ)}")
  fijar APP_TZ "${TZ_APP:-UTC}"

  nota ""
  nota "La direccion publica es por donde el NAVEGADOR de los usuarios alcanza"
  nota "el puerto 3900 (las fotos se sirven con URL firmadas contra ella)."
  nota "Si te equivocas aqui, las fotos no cargaran."
  PUBLICO=$(preguntar "Direccion publica del storage" \
    "${S3_PUBLIC_ENDPOINT:-$(leer S3_PUBLIC_ENDPOINT)}")
  PUBLICO="${PUBLICO:-http://localhost:3900}"
  fijar S3_PUBLIC_ENDPOINT "$PUBLICO"

  case "$PUBLICO" in
    https://*) fijar SESSION_COOKIE_SECURE true; ok "HTTPS detectado: cookies marcadas como Secure" ;;
    *)         fijar SESSION_COOKIE_SECURE false ;;
  esac

  nota ""
  ADMIN_USR=$(preguntar "Usuario del administrador" "${ADMIN_USUARIO:-$(leer ADMIN_USUARIO)}")
  fijar ADMIN_USUARIO "${ADMIN_USR:-admin}"
  ADMIN_NOM=$(preguntar "Nombre completo del administrador" \
    "${ADMIN_NOMBRE:-$(leer ADMIN_NOMBRE)}")
  fijar ADMIN_NOMBRE "${ADMIN_NOM:-Administrador del Sistema}"
  ADMIN_MAIL=$(preguntar "Correo del administrador (opcional)" "${ADMIN_EMAIL:-}")
  fijar ADMIN_EMAIL "$ADMIN_MAIL"

  ADMIN_PASSWORD_NUEVA="$(password_legible)"
  fijar ADMIN_PASSWORD "$ADMIN_PASSWORD_NUEVA"
  # Contrasena generada: el administrador la reemplaza al entrar.
  fijar ADMIN_FORZAR_CAMBIO 1
  ok "contrasena temporal generada para '$ADMIN_USR'"
fi

# --- 3. Directorios de datos ----------------------------------------------
paso "Preparando el almacenamiento en el host"
RUTA_DATOS="$(leer RUTA_DATOS)"
RUTA_DATOS="${RUTA_DATOS:-./datos}"
mkdir -p "$RUTA_DATOS/postgres" "$RUTA_DATOS/garage/meta" "$RUTA_DATOS/garage/data"
ok "datos en $(cd "$RUTA_DATOS" && pwd)"
nota "Un 'docker compose down -v' ya no los borra. Respalda ese directorio."

# --- 4. Construccion y arranque -------------------------------------------
paso "Construyendo la imagen de la aplicacion"
docker compose build

paso "Levantando los servicios"
docker compose up -d

# --- 5. Espera activa ------------------------------------------------------
paso "Esperando a que todo quede sano"
INTENTOS=60
while [ "$INTENTOS" -gt 0 ]; do
  ESTADO="$(docker compose ps --format '{{.Service}}={{.Health}}' 2>/dev/null | tr '\n' ' ')"
  case "$ESTADO" in
    *"app=healthy"*) break ;;
  esac
  if docker compose ps --status exited --format '{{.Service}}' 2>/dev/null | grep -qx app; then
    printf '\n'; docker compose logs --tail 40 app
    fallar "El contenedor de la aplicacion se detuvo. Revisa el log de arriba."
  fi
  INTENTOS=$((INTENTOS - 1))
  sleep 3
done
[ "$INTENTOS" -gt 0 ] || { docker compose logs --tail 40 app; fallar "La aplicacion no respondio a tiempo."; }

docker compose ps --format 'table {{.Service}}\t{{.Status}}'

# --- 6. Comprobaciones de humo --------------------------------------------
paso "Comprobaciones finales"
if docker compose exec -T app python -c "
import sys, urllib.request
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/salud', timeout=5).status == 200 else 1)
" >/dev/null 2>&1; then
  ok "la aplicacion responde en /salud"
else
  aviso "la aplicacion no respondio a /salud"
fi

if docker compose exec -T app flask storage-check >/dev/null 2>&1; then
  ok "el object storage acepta escritura y lectura"
else
  aviso "el object storage no respondio (revisa: docker compose logs garage-init)"
fi

USUARIOS="$(docker compose exec -T db psql -U "$(leer POSTGRES_USER)" -d "$(leer POSTGRES_DB)" \
  -tAc 'select count(*) from usuario' 2>/dev/null | tr -d '[:space:]')"
if [ "${USUARIOS:-}" = "1" ]; then
  ok "la base tiene exactamente 1 usuario: el administrador (sin datos de ejemplo)"
else
  nota "usuarios en la base: ${USUARIOS:-?}"
fi

# --- 7. Resumen ------------------------------------------------------------
# El puerto publicado se le pregunta a compose, no se supone.
PUERTO="$(docker compose port app 8000 2>/dev/null | sed 's/.*://')"
printf '\n%s  Listo.%s\n\n' "$VERDE" "$FIN"
printf '  Aplicacion:  http://localhost:%s\n' "${PUERTO:-8000}"
printf '  Usuario:     %s\n' "$(leer ADMIN_USUARIO)"

if [ -n "$ADMIN_PASSWORD_NUEVA" ]; then
  printf '  Contrasena:  %s%s%s\n' "$AMBAR" "$ADMIN_PASSWORD_NUEVA" "$FIN"
  printf '\n  %sAnotala ahora.%s Se le pedira cambiarla al entrar; despues de eso el valor\n' "$AMBAR" "$FIN"
  printf '  de ADMIN_PASSWORD en .env deja de servir.\n'
else
  printf '  Contrasena:  la que ya tuviera la cuenta (este script no la cambia)\n'
fi

printf '\n  %sPendientes tipicos:%s\n' "$AZUL" "$FIN"
printf '   · Pon un proxy inverso con HTTPS delante del puerto 8000.\n'
printf '   · Programa un respaldo de %s y de pg_dump.\n' "$RUTA_DATOS"
printf '   · Crea los usuarios del equipo desde Usuarios, en la propia aplicacion.\n'
printf '\n  %sOperacion:%s  docker compose logs -f app  ·  docker compose down  ·  ./desplegar.sh --actualizar\n\n' "$GRIS" "$FIN"

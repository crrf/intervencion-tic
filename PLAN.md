# Sistema de Tickets e Incidencias — Grupo de Intervención Técnica (Fibra Óptica)

## Contexto

El directorio `Intervencion-Tickets` está vacío: es un proyecto desde cero.

El grupo de intervención técnica atiende conectividades por fibra óptica y hoy no tiene una
herramienta para registrar, asignar y dar seguimiento al trabajo de campo. Se necesita un sistema
web donde un **despachador** registre dos tipos de trabajo —**órdenes de trabajo** e
**interrupciones**— con la foto del documento físico, los asigne a **operadores** específicos, y
donde el operador diagnostique y resuelva. Cuando el operador determina que la falla es de **capa
física (fibra)**, deriva la interrupción a un **agente de fibra**, cuyo único trabajo es revisar el
tramo, marcarlo OK o con falla y comentar; el operador ve esa respuesta y decide el cierre.

Las averías se clasifican en tres dependencias: **Core (IPMPLS)**, **Distribución** y **Capa
Física (la fibra)**.

Resultado esperado: un `docker-compose.yml` que levanta Flask + PostgreSQL + Garage (object
storage S3), con el Dockerfile de la aplicación, listo para producción.

---

## Decisiones tomadas (confirmadas con el usuario)

| Tema | Decisión |
|---|---|
| Frontend | Jinja2 + HTMX + Alpine.js + Tailwind — todo dentro de Flask, un solo servicio de app |
| Modelo | **Dos tablas separadas**: `orden_trabajo` e `interrupcion` |
| Roles | `admin`, `despachador`, `operador`, `agente_fibra` — **un usuario puede tener varios a la vez** (p. ej. despachador + operador) |
| Auth | Flask-Login (sesión con cookie) + RBAC por decoradores |
| Dependencia | La define **solo el operador** al diagnosticar (nace como "Por diagnosticar") |
| Kanban | Un tablero para todos los roles, filtrado y con transiciones limitadas por permiso |
| Fotos | OT = 2 fotos (anverso + reverso), Interrupción = 1 foto. **Obligatorias al crear**. Solo las sube el despachador/admin |
| Evidencia de cierre | No. Operador y agente_fibra solo escriben comentarios de texto |
| Identificador | Campo externo digitado por el despachador, formato `ED123456` / `FD123456` |
| Notificaciones | In-app: campana con contador + auto-refresco HTMX cada ~20 s |
| Prioridad/Métricas | Prioridad + dashboard de desempeño por operador (sin reglas de SLA automáticas) |
| Búsqueda e histórico | Admin y despachador: búsqueda por identificador/folio, reporte por rango de fechas y bitácora de auditoría completa, con exportación CSV |
| Acabado | Producción: Gunicorn, Alembic, seeds, healthchecks, pytest, `.env.example` |

---

## Máquinas de estado (el corazón del sistema)

### Orden de trabajo — `EstadoOrden`

```
NUEVA ──(despachador asigna)──► ASIGNADA ──(operador)──► EN_PROCESO
                                                          ├─► CERRADA              (comentario obligatorio)
                                                          └─► ABIERTA_CON_MOTIVO   (motivo + comentario obligatorios)
ABIERTA_CON_MOTIVO ──► EN_PROCESO ──► CERRADA
CERRADA ──(solo admin, reapertura auditada)──► EN_PROCESO
```

### Interrupción — `EstadoInterrupcion` + `EstadoFibra`

```
NUEVA ──(despachador asigna)──► ASIGNADA ──(operador)──► EN_PROCESO
                                                          │  (el operador DEBE fijar la dependencia aquí)
                                                          ├─► CERRADA                 (comentario obligatorio)
                                                          ├─► DERIVADA_FIBRA          (exige dependencia = CAPA_FISICA)
                                                          │      └─ estado_fibra = EN_REVISION
                                                          └─► ABIERTA_OTRO_MOTIVO     (motivo + comentario)

DERIVADA_FIBRA ──(operador, tras leer la respuesta de fibra)──► CERRADA
DERIVADA_FIBRA ──(operador retoma)──► EN_PROCESO
```

`estado_fibra` (columna aparte, solo la toca el **agente_fibra**, comentario obligatorio en cada cambio):

```
EN_REVISION ──► FIBRA_OK
EN_REVISION ──► FIBRA_CON_FALLA
FIBRA_OK / FIBRA_CON_FALLA ──► EN_REVISION   (reabrir revisión)
```

**Límites duros del `agente_fibra`** (probar explícitamente):
no ve órdenes de trabajo; no ve interrupciones que no estén en `DERIVADA_FIBRA`; no crea, no
asigna, no cambia `estado`, no cierra, no sube fotos. Solo `estado_fibra` + comentarios.

---

## Modelo de datos (PostgreSQL 16 + SQLAlchemy 2.x)

`app/models/enums.py` — Enums nativos de Postgres:
`RolUsuario`, `EstadoOrden`, `EstadoInterrupcion`, `EstadoFibra`, `Dependencia`
(`CORE_IPMPLS`, `DISTRIBUCION`, `CAPA_FISICA`), `Prioridad` (`BAJA`, `MEDIA`, `ALTA`, `CRITICA`).

**`usuario`** — `id`, `usuario` (login, único), `nombre_completo`, `email`, `password_hash`
(`werkzeug.security.generate_password_hash`, scrypt), `activo`, `creado_en`.
**Sin columna `rol`** (ver la sección de roles múltiples).

**`usuario_rol`** — tabla puente `(usuario_id, rol)` con PK compuesta. Un usuario tiene 1..N roles.

**`orden_trabajo`**
`id`, `folio` (único, `OT-2026-0001`), `identificador_externo` (indexado, no único, validado
`^[A-Z]{2}\d{6}$`, normalizado a mayúsculas), `nombre_cliente`, `titulo`, `descripcion`,
`prioridad`, `estado`, `motivo_apertura` (texto, obligatorio si `ABIERTA_CON_MOTIVO`),
`creado_por_id` → usuario, `asignado_a_id` → usuario, `foto_anverso_key`, `foto_reverso_key`,
`creado_en`, `asignado_en`, `cerrado_en`.

**`interrupcion`**
Los mismos campos base, más: `dependencia` (nullable = "Por diagnosticar"), `estado`
(`EstadoInterrupcion`), `estado_fibra` (nullable), `agente_fibra_id` → usuario,
`derivado_fibra_en`, `respuesta_fibra_en`, `foto_key`.

**`comentario`** — `id`, `orden_id` (nullable), `interrupcion_id` (nullable),
`CHECK (num_nonnulls(orden_id, interrupcion_id) = 1)`, `autor_id`, `texto`, `creado_en`.
Todos los comentarios son visibles para quien pueda ver el ticket (el operador **debe** leer los
del agente_fibra).

**`historial`** — misma pareja de FK con el mismo CHECK, más `usuario_id`, `campo`,
`valor_anterior`, `valor_nuevo`, `creado_en`. Lo escribe la capa de servicios en cada cambio de
estado, asignación, cambio de dependencia y reemplazo de foto.

**`notificacion`** — `id`, `usuario_id`, `titulo`, `mensaje`, `url`, `leida`, `creada_en`.

**`contador_folio`** — `anio`, `tipo` (`OT`/`INT`), `valor`. El folio se genera dentro de la misma
transacción con `SELECT ... FOR UPDATE` sobre esta fila (evita duplicados con varios workers de
Gunicorn). No usar `COUNT(*)`.

Índices: `(estado)`, `(asignado_a_id, estado)`, `(identificador_externo)`, `(creado_en DESC)`,
`(cerrado_en)` en ambas tablas de ticket; `(usuario_id, leida)` en notificaciones;
`(creado_en DESC)` y `(usuario_id)` en `historial`.

---

## Roles múltiples por usuario

Un mismo usuario puede ser **despachador y operador a la vez** (y en general cualquier combinación).
Esto obliga a que el permiso sea la **unión** de las capacidades de sus roles, evaluada siempre
contra el ticket concreto:

- `Usuario.roles` → `set[RolUsuario]`; helpers `usuario.tiene_rol(...)` y
  `usuario.tiene_alguno(...)`.
- `@rol_requerido('admin', 'despachador')` pasa si la intersección no es vacía.
- `transiciones_permitidas(ticket, usuario)` devuelve la **unión** de las transiciones que aporta
  cada rol. Un despachador+operador puede asignar cualquier ticket *y además* trabajar y cerrar los
  que estén asignados a él mismo — incluido asignárselos a sí mismo.
- La **visibilidad también es unión**: la restricción del `agente_fibra` (ver solo interrupciones
  derivadas) limita a ese rol, no al usuario. Si alguien es despachador + agente_fibra, ve todo por
  su rol de despachador; lo que no gana es la facultad de cambiar `estado_fibra` fuera de las
  interrupciones derivadas.
- El selector "asignar a" lista a todos los usuarios activos que tengan el rol `operador`,
  incluyendo a los que además son despachadores.
- Admin de usuarios: casillas de verificación de roles, no un desplegable. Validar al menos un rol
  y no permitir que el último admin activo se quede sin el rol `admin`.

⚠️ **Trampa a evitar:** nada de `if usuario.rol == 'operador'` en plantillas o vistas. Toda decisión
de permiso sale de `security/decoradores.py` o de `services/estados.py`.

---

## Búsqueda, histórico y auditoría (admin + despachador)

### 1. Búsqueda avanzada — `/buscar`
Formulario con envío HTMX (resultados sin recargar) y todos los filtros combinables:

- **Identificador externo** (`ED123456`) y **folio** (`OT-2026-0001`) — coincidencia parcial,
  insensible a mayúsculas; es el caso de uso principal, debe estar en la barra superior de toda la app.
- Tipo (OT / Interrupción / ambos), estado, `estado_fibra`, dependencia, prioridad.
- Operador asignado, despachador creador, agente de fibra que atendió.
- **Rango de fechas** sobre `creado_en` o `cerrado_en` (a elección).
- Texto libre sobre título, descripción y comentarios.

Resultado: tabla paginada y ordenable (folio, identificador, tipo, cliente, prioridad, dependencia,
asignado a, estado actual, creado, cerrado, tiempo de resolución) + botón **Exportar CSV** que
respeta los filtros activos.

### 2. Reporte histórico por periodo — `/reportes/historico`
Selector de rango con presets (hoy, 7 días, 30 días, mes anterior, personalizado) reutilizado en
todo el módulo. Responde exactamente a "qué pasó en este periodo":

- Todos los tickets creados y/o cerrados en el rango.
- A quién se asignó cada uno y **en qué estado quedó** al cierre del periodo.
- Si pasó por fibra, quién lo atendió y con qué resultado.
- Tiempo de resolución por ticket y totales por estado.
- Exportación CSV.

### 3. Bitácora de auditoría — `/reportes/auditoria`
Feed cronológico unificado de `historial` + `comentario` en el rango seleccionado —
"todo lo que pasó", quién lo hizo y cuándo. Filtrable por usuario, por ticket y por tipo de evento.
Paginado por cursor (`creado_en`, `id`) para que no se degrade con el volumen. Exportable a CSV.
El detalle de cada ticket muestra esta misma línea de tiempo, acotada a ese ticket.

### Nota técnica: consultas sobre dos tablas
Como `orden_trabajo` e `interrupcion` son tablas separadas, búsquedas, reportes y métricas que
cruzan ambos tipos deben pasar por un solo lugar: `services/consultas.py`, con un
`ticket_union_cte()` que arma un `UNION ALL` de las columnas comunes (`id`, `tipo`, `folio`,
`identificador_externo`, `nombre_cliente`, `prioridad`, `estado::text`, `dependencia`,
`asignado_a_id`, `creado_por_id`, `creado_en`, `cerrado_en`). Filtros, orden, paginación y
agregaciones se construyen sobre esa CTE. **No duplicar la lógica de filtrado por tipo de ticket.**

---

## Dashboard de desempeño (admin + despachador) — `/dashboard`

Mismo selector de rango de fechas que los reportes. Todas las cifras se recalculan con el rango.

**Tarjetas superiores:** abiertos ahora · cerrados en el periodo · derivados a fibra pendientes de
respuesta · abiertos con motivo · tiempo promedio de resolución.

**Tabla comparativa por operador** (el núcleo de lo pedido), ordenable por cualquier columna:

| Operador | Asignados en el periodo | **Soluciones** (cerrados) | **Pendientes** (abiertos ahora) | Abiertos c/ motivo | Derivados a fibra | Tiempo prom. de cierre | % de cierre |
|---|---|---|---|---|---|---|---|

- **Soluciones** se cuenta desde `historial` (`campo='estado'`, `valor_nuevo='CERRADA'`,
  `usuario_id = operador`), no desde `asignado_a`: así se atribuye a quien realmente cerró, aunque
  el ticket haya cambiado de manos.
- **Pendientes** es un corte al momento de la consulta (estado ≠ `CERRADA`), no depende del rango.

**Gráficos** (Chart.js pineado desde cdnjs):
barras horizontales de soluciones por operador · barras apiladas de pendientes por estado y
operador · línea de creados vs. cerrados por día · dona por dependencia
(Core / Distribución / Capa Física).

**Desempeño del agente de fibra:** derivaciones recibidas, resueltas como *Fibra OK* vs. *Con
falla*, y tiempo promedio de respuesta.

*(Opcional, barato de agregar: el operador ve `/dashboard` recortado solo a sus propias cifras.)*

---

## Estructura del proyecto

```
Dockerfile                     multi-stage: build de Tailwind → python:3.12-slim + gunicorn
docker-compose.yml             db · garage · garage-init · app
.env.example
requirements.txt
docker/
  entrypoint.sh                espera Postgres → flask db upgrade → seed opcional → gunicorn
  garage.toml                  configuración single-node
  garage-init.sh               layout + bucket + key (idempotente)
app/
  __init__.py                  create_app() (application factory)
  config.py                    Config / DevConfig / ProdConfig / TestConfig
  extensions.py                db, migrate, login_manager, csrf, limiter
  cli.py                       flask seed, flask crear-usuario
  models/                      enums, usuario, usuario_rol, orden, interrupcion, comentario, historial, notificacion
  services/
    estados.py                 ⭐ máquinas de estado: transiciones_permitidas(ticket, usuario) y ejecutar_transicion(...)
    tickets.py                 crear, asignar, comentar, reemplazar foto — escribe historial + notificaciones
    consultas.py               ⭐ ticket_union_cte() + filtros/paginación compartidos por búsqueda, reportes y métricas
    metricas.py                agregados del dashboard (por operador, por dependencia, series diarias)
    exportacion.py             CSV en streaming a partir de una consulta filtrada
    storage.py                 boto3 → Garage: subir(), url_prefirmada(), eliminar()
    notificaciones.py
  security/
    decoradores.py             @rol_requerido(...), @puede_ver(ticket), @puede_transicionar(...)
  blueprints/
    auth/  tablero/  ordenes/  interrupciones/  fibra/  adjuntos/
    buscar/  reportes/  dashboard/  notificaciones/  admin/
  templates/                   base.html + parciales HTMX (_tarjeta.html, _columna.html, _campana.html)
  static/
migrations/                    Alembic (Flask-Migrate)
tests/
```

**Regla de oro de arquitectura:** las vistas nunca cambian un estado directamente. Toda transición
pasa por `services/estados.py::ejecutar_transicion()`, que valida rol + estado origen + campos
obligatorios, escribe `historial` y dispara notificaciones. El frontend solo *pinta* lo que el
servidor autoriza; el servidor **siempre** revalida.

---

## Tablero Kanban (una vista, tres comportamientos)

Ruta `/tablero`, con pestañas `Órdenes | Interrupciones` (y `Fibra` para el agente).
Columnas = estados. Drag & drop con SortableJS; al soltar, un `POST` HTMX a
`/tablero/mover/<tipo>/<id>` que devuelve la tarjeta re-renderizada (o un 422 con el motivo y
revierte visualmente).

| Rol | Qué ve | Qué puede arrastrar |
|---|---|---|
| `admin` | Todo | Todas las transiciones + reapertura |
| `despachador` | Todos los tickets | Solo `NUEVA → ASIGNADA` (abre modal para elegir operador) |
| `operador` | Solo `asignado_a_id == yo` | Su máquina de estados completa |
| `agente_fibra` | Solo interrupciones en `DERIVADA_FIBRA`, columnas por `estado_fibra` | Solo `estado_fibra` |

Cada tarjeta renderiza `data-transiciones="..."` con los destinos válidos para *ese* usuario y *ese*
ticket, calculados por `transiciones_permitidas()`. Transiciones que exigen texto (cierre, motivo,
respuesta de fibra) abren un modal en vez de mover directo.

---

## Fotos en Garage (S3)

- Bucket privado único (`tickets-adjuntos`), claves predecibles:
  `ordenes/{folio}/anverso.jpg`, `ordenes/{folio}/reverso.jpg`, `interrupciones/{folio}/foto.jpg`.
- Validación al subir: extensión + `content-type` real + tamaño máximo (`MAX_FOTO_MB`, def. 8 MB).
  Opcional: recomprimir con Pillow a máx. 1920 px.
- **Gotcha crítico:** la URL prefirmada la usa el *navegador*, no el contenedor. Se necesitan dos
  endpoints:
  - `S3_ENDPOINT_URL=http://garage:3900` → para **subir** (red interna de Docker).
  - `S3_PUBLIC_ENDPOINT=http://localhost:3900` → cliente boto3 aparte, solo para **firmar** las URL
    de lectura (15 min).
  Si se usa un solo endpoint, las imágenes no cargarán en el navegador.
- El endpoint `/adjuntos/<tipo>/<id>/<cual>` verifica permiso y responde `302` a la URL prefirmada.
- Reemplazo de foto permitido mientras el ticket no esté cerrado; queda asentado en `historial`.

---

## Docker Compose (4 servicios)

- **`db`** — `postgres:16-alpine`, volumen `pgdata`, `healthcheck: pg_isready`.
- **`garage`** — `dxflrs/garage:v1.0.1` (pinear la versión), monta `docker/garage.toml`, volúmenes
  `garage-meta` y `garage-data`, expone `3900` (S3) y `3903` (admin), healthcheck contra el puerto
  admin. En `garage.toml`: `replication_factor = 1`, `db_engine = "lmdb"`, `s3_region = "garage"`,
  `rpc_secret` desde `.env`.
- **`garage-init`** — servicio de un solo disparo (`restart: "no"`), `depends_on: garage
  (service_healthy)`. Ejecuta `garage-init.sh`: espera el nodo, `garage layout assign -z dc1 -c 10G`
  + `layout apply`, crea el bucket, importa la llave con el access/secret fijos del `.env`
  (`garage key import`) y otorga permisos read/write al bucket. **Todo idempotente** (verificar si
  ya existe antes de crear) para que `docker compose up` se pueda repetir sin errores.
  ⚠️ Los flags del CLI de Garage cambian entre versiones mayores: validar contra la doc de la
  versión pineada antes de dar por bueno el script.
- **`app`** — build local, `depends_on` db healthy + garage-init completado, healthcheck contra
  `/salud`, publica `8000`.

`.env.example`: `POSTGRES_*`, `DATABASE_URL`, `SECRET_KEY`, `GARAGE_RPC_SECRET`, `S3_ENDPOINT_URL`,
`S3_PUBLIC_ENDPOINT`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `MAX_FOTO_MB`,
`APP_TZ` (por defecto `UTC` — cambiar a la zona real del grupo), `SEED_ON_START`, `ADMIN_*`.

**Dockerfile:** etapa 1 descarga el binario standalone de Tailwind (versión pineada) y compila
`static/css/app.css`; etapa 2 `python:3.12-slim`, usuario no-root, `pip install -r requirements.txt`,
copia la app y el CSS compilado, `ENTRYPOINT ["/app/docker/entrypoint.sh"]`,
`CMD gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app()"`.

**Dependencias:** Flask, Flask-SQLAlchemy, Flask-Migrate, Flask-Login, Flask-WTF, WTForms,
psycopg[binary], boto3, gunicorn, python-dotenv, Pillow, Flask-Limiter, pytest, pytest-flask, moto.

---

## Seguridad

- CSRF en todos los formularios y peticiones HTMX (`X-CSRFToken` en `hx-headers` global).
- Contraseñas con scrypt (`werkzeug.security`); forzar cambio de la contraseña semilla del admin.
- Cookies `HttpOnly`, `SameSite=Lax`, `Secure` cuando `PROD`.
- Flask-Limiter sobre `/auth/login` (nota: con almacenamiento en memoria el límite es por worker;
  si se necesita estricto, hay que agregar Redis).
- La autorización se resuelve **en el query**, no solo en la plantilla: quien solo es operador
  consulta `WHERE asignado_a_id = current_user.id`; quien solo es agente_fibra,
  `WHERE estado = 'DERIVADA_FIBRA'`. Nunca cargar todo y filtrar en Jinja.
- Búsqueda, reportes y dashboard están cerrados a `admin` y `despachador`: probar que un operador
  puro recibe 403 en `/buscar`, `/reportes/*` y `/dashboard`.

---

## Datos semilla (`flask seed`)

Un usuario por rol para recorrer el flujo completo de inmediato: `admin`, `despachador1`,
`operador1`, `operador2`, `fibra1`, más **`mixto1` con los roles despachador + operador** para
ejercitar la combinación. Además, ~40 tickets repartidos entre estados, dependencias y operadores,
con `creado_en`/`cerrado_en` distribuidos en los últimos 60 días para que el dashboard y los
reportes por periodo tengan algo que mostrar. Idempotente: no hace nada si ya existen usuarios.

---

## Plan de implementación (orden sugerido)

1. Esqueleto: `create_app()`, config, extensiones, Dockerfile, compose, `.env.example`, `/salud`.
2. Garage funcionando: `garage.toml`, `garage-init.sh`, y un smoke test de `storage.py`
   (subir → firmar → descargar).
3. Modelos (incluida `usuario_rol`) + primera migración de Alembic + `flask seed`.
4. Auth y decoradores RBAC **con semántica de unión de roles** desde el día uno.
5. `services/estados.py` con las dos máquinas de estado **y sus tests** — antes de cualquier UI.
6. `services/tickets.py`: crear con fotos obligatorias, asignar, comentar; historial + notificaciones.
7. Vistas de detalle de OT e Interrupción (formularios, comentarios, línea de tiempo, fotos).
8. Bandeja del agente_fibra + cambio de `estado_fibra`.
9. Tablero Kanban con HTMX + SortableJS y las reglas por rol.
10. Campana de notificaciones con polling.
11. `services/consultas.py` (`ticket_union_cte`) → búsqueda avanzada `/buscar` + exportación CSV.
12. Reportes: histórico por periodo y bitácora de auditoría.
13. Dashboard de desempeño por operador (`services/metricas.py` + Chart.js).
14. Admin de usuarios con roles múltiples.
15. Endurecimiento: manejadores de error 403/404/500, logging estructurado, README.

---

## Verificación

**Automatizada** — `docker compose run --rm app pytest`:
- `test_estados.py`: matriz completa de transiciones × roles, válidas e inválidas. Incluye
  explícitamente: el agente_fibra no puede cerrar ni ver órdenes; el operador no puede derivar a
  fibra sin fijar `dependencia = CAPA_FISICA`; cerrar sin comentario falla.
- `test_permisos.py`: el operador B recibe 403/404 en un ticket del operador A; un operador puro
  recibe 403 en `/buscar`, `/reportes/*` y `/dashboard`.
- `test_roles_multiples.py`: un usuario despachador+operador puede asignarse un ticket a sí mismo y
  luego cerrarlo; sigue sin poder tocar `estado_fibra`; ve el tablero completo (por despachador) y
  las transiciones de operador solo en lo asignado a él.
- `test_consultas.py`: la búsqueda por identificador parcial (`ED1234`) devuelve tanto órdenes como
  interrupciones; el rango de fechas no incluye tickets fuera del periodo; la paginación no repite
  ni omite filas.
- `test_metricas.py`: con un conjunto fijo de tickets, las "soluciones" por operador se atribuyen a
  quien ejecutó la transición a `CERRADA` (no a `asignado_a`), y los pendientes son un corte actual.
- `test_folio.py`: 50 creaciones concurrentes → 50 folios distintos y consecutivos.
- `test_fotos.py` (moto): crear una OT sin las dos fotos falla; con ambas, se guardan las claves.
- `test_notificaciones.py`: derivar a fibra notifica a los agentes; la respuesta de fibra notifica
  al operador asignado.

**Manual, extremo a extremo** — `docker compose up --build`, entrar a `http://localhost:8000`:
1. `despachador1` crea una interrupción con `ED123456`, cliente y su foto → verificar que sin foto
   no deja guardar; asignarla a `operador1`.
2. `operador1` la pasa a *En proceso*, la clasifica como **Capa Física** y la deriva a fibra.
3. `fibra1` la ve aparecer en su bandeja (y confirmar que **no** ve nada más), la marca *Fibra con
   falla* con comentario.
4. `operador1` recibe la campana, lee el comentario y cierra la interrupción.
5. Crear una orden de trabajo con anverso y reverso; verificar que ambas imágenes se despliegan
   (esto valida el `S3_PUBLIC_ENDPOINT`); cerrarla y luego dejarla abierta con motivo.
6. Revisar la línea de tiempo completa del ticket.
7. Como `despachador1`: buscar por `ED123456` y encontrar el ticket; filtrar por rango "últimos 30
   días" y confirmar que el reporte histórico muestra a quién se asignó y en qué estado quedó cada
   ticket; abrir la bitácora de auditoría y verificar que aparecen la derivación, la respuesta de
   fibra y el cierre con sus autores y horas; exportar el CSV.
8. Abrir `/dashboard` y comprobar que `operador1` suma una solución más y que sus pendientes bajan;
   cambiar el rango de fechas y verificar que las cifras cambian.
9. Entrar como `mixto1` (despachador + operador): crear una orden, asignársela a sí mismo,
   trabajarla y cerrarla en la misma sesión; confirmar que ve el tablero completo pero solo puede
   arrastrar por su máquina de estados los tickets propios.

**Infraestructura:** `docker compose ps` con los 3 servicios `healthy`, `garage-init` en `exited
(0)`; `docker compose down && docker compose up` no falla (init idempotente); los datos sobreviven
al reinicio.

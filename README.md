# Sistema de Tickets e Incidencias — Intervención Técnica

Sistema web para el grupo de intervención técnica de conectividades por fibra óptica.
Registra, asigna y da seguimiento a **órdenes de trabajo** e **interrupciones**, clasificadas en
tres dependencias: **Core (IPMPLS)**, **Distribución** y **Capa física (la fibra)**.

Flask + PostgreSQL + Garage (object storage compatible con S3), los tres en un solo
`docker-compose.yml`.

---

## Puesta en producción

```bash
./desplegar.sh
```

Es lo único que hace falta en un servidor limpio. El script:

- comprueba Docker y el plugin `compose`;
- crea el `.env` a partir de `.env.example` **generando secretos aleatorios reales**
  (`SECRET_KEY`, contraseña de PostgreSQL, `rpc_secret` y llaves S3 de Garage con el formato exacto
  que exige: `GK` + 24 hexadecimales y 64 hexadecimales);
- pregunta las cuatro cosas que no puede adivinar: zona horaria, dirección pública del storage,
  y usuario y nombre del administrador;
- deja `SEED_ON_START=false`: **no siembra ningún dato de ejemplo**, la base arranca vacía;
- crea **solo la cuenta de administrador**, con una contraseña temporal que imprime una vez y que
  el administrador está obligado a cambiar en su primer ingreso;
- crea los directorios de datos, construye, levanta, espera a que los tres servicios queden sanos
  y hace comprobaciones de humo (`/salud`, escritura y lectura en el object storage, y que la base
  tenga exactamente un usuario).

A partir de ahí, el administrador da de alta al resto del equipo desde **Usuarios**, dentro de la
propia aplicación.

```bash
./desplegar.sh                  # despliegue interactivo
./desplegar.sh --sin-preguntas  # desatendido: toma los valores de .env.example o del entorno
./desplegar.sh --actualizar     # reconstruye y reinicia sin tocar .env ni los datos
./desplegar.sh --ayuda
```

Repetirlo es seguro: si ya existe `.env` **no lo pisa** ni regenera secretos (regenerar
`SECRET_KEY` cerraría todas las sesiones), y `flask crear-admin` es idempotente — si la cuenta ya
existe no le cambia la contraseña, solo se asegura de que siga activa y con su rol.

---

## Arranque de demostración

Para probar el sistema con contenido, **no en producción**:

```bash
cp .env.example .env      # trae SEED_ON_START=true
docker compose up --build
```

Abre <http://localhost:8000>. Se crean usuarios y unos 48 tickets de ejemplo repartidos en los
últimos 60 días, para que el tablero, los reportes y el dashboard tengan contenido desde el primer
minuto.

| Usuario | Rol(es) | Contraseña |
|---|---|---|
| `admin` | Administrador | la de `ADMIN_PASSWORD` |
| `despachador1` | Despachador | la de `SEED_PASSWORD` |
| `operador1` · `operador2` · `operador3` | Operador | la de `SEED_PASSWORD` |
| `fibra1` · `fibra2` | Agente de fibra | la de `SEED_PASSWORD` |
| `wifi1` | Técnico de wifi | la de `SEED_PASSWORD` |
| `mixto1` | **Despachador + Operador** | la de `SEED_PASSWORD` |

---

## El flujo

### Orden de trabajo

```
NUEVA ──(despachador asigna)──► ASIGNADA ──(operador)──► EN PROCESO
                                                          ├─► OK DEL OPERADOR      (exige comentario)
                                                          └─► ABIERTA CON MOTIVO    (exige motivo + comentario)

ABIERTA CON MOTIVO ──(operador)──► EN PROCESO · OK DEL OPERADOR

OK DEL OPERADOR ──(despachador)──► CERRADA            (cierre en SIPREC, exige comentario)
                └─(despachador)──► EN PROCESO         (devuelve al operador, exige comentario)

CERRADA ──(solo admin, queda auditado)──► EN PROCESO
```

El operador **no cierra** una orden de trabajo: cuando termina da su **OK**, y la orden queda en
la columna *OK del operador*, a la vista del despachador (que ademas recibe una notificacion).
El despachador es quien la marca **cerrada en SIPREC** o, si el OK no procede, la **devuelve
al operador** explicando qué falta. El dashboard muestra cuantas ordenes esperan ese cierre.

### Interrupción

```
NUEVA ──(despachador asigna)──► ASIGNADA ──(operador)──► EN PROCESO
                                                          │  aquí el operador DEBE clasificar la dependencia
                                                          ├─► CERRADA
                                                          ├─► DERIVADA A FIBRA      (solo si es capa física)
                                                          └─► ABIERTA / OTRO MOTIVO
```

### Sitios wifi

Hay **tres puertas de creación**, cada una con su formulario, y las tres están en la barra
superior (y en el menú, en móvil):

| Botón | Crea | La atiende |
|---|---|---|
| **+ Orden** | Orden de trabajo | Un operador |
| **+ Interrupción** | Interrupción de *enlace de cliente* | Un operador |
| **+ Sitio wifi** | Interrupción de *sitio wifi* | Un técnico de wifi |

Cada formulario **fija su categoría**: no hay una casilla que se pueda combinar mal. El de sitio
wifi ofrece primero a los técnicos de wifi (y a los operadores en un segundo grupo, por si no
hay ninguno disponible), y avisa si no existe ningún técnico activo. El servidor valida igual
la combinación, no se fía del formulario.

La **categoría** (*Enlace de cliente* o *Sitio wifi*) es la que decide a quién se le puede
entregar:

- Al **técnico de wifi** —el que va al sitio a detectar la falla y, si puede, a resolverla— solo
  se le pueden asignar interrupciones de **sitio wifi**. El sistema rechaza cualquier otra.
- Una de sitio wifi también se le puede asignar a un operador normal, por si el técnico no está
  disponible.

Con su interrupción asignada, el técnico de wifi trabaja igual que un operador: la toma, clasifica
la dependencia, la cierra, la deja abierta con motivo o la deriva a fibra si resulta ser capa
física. No ve órdenes de trabajo ni interrupciones que no sean suyas.

La categoría se corrige después desde el detalle (solo despachador o admin). Si la interrupción
está en manos de un técnico de wifi, primero hay que reasignarla: el sistema no lo deja quedarse
con una que ya no es de sitio wifi.

Cuando una interrupción se deriva, aparece en la bandeja del **agente de fibra**, que solo puede
mover la columna `estado_fibra` (En revisión → Fibra OK / Fibra con falla) y comentar. El operador
ve esa respuesta y decide el cierre. El agente de fibra **no** crea, no asigna, no cierra y no ve
órdenes de trabajo.

### Color y contraste

La paleta vive entera en variables CSS, con un juego para el tema claro y otro para el oscuro
(`prefers-color-scheme`). Dos reglas que `tests/test_paleta.py` comprueba en cada ejecución:

- **Todo el texto cumple WCAG 2.1 AA**: 4.5:1 para texto normal (incluidas las insignias, que son
  texto pequeño en negrita) y 3:1 para las cifras grandes del dashboard. El contorno de los
  campos y botones usa `--borde-campo`, con 3:1 contra el fondo, como pide el criterio 1.4.11; los
  bordes que solo separan paneles son decorativos y quedan exentos.
- **Ningún color significa dos cosas a la vez.** El fucsia es solo de *sitio wifi*, el violeta
  solo de *derivada a fibra*, el cian solo de *OK del operador*. Importa porque esas insignias
  conviven en la misma tarjeta.

Los tres grises de texto mantienen entre sí al menos 1.2:1 para que la jerarquía se siga
leyendo: cumplir el contraste no debería costar que todo se vea del mismo tono.

### Teléfono de contacto del cliente

Órdenes e interrupciones llevan un **teléfono de contacto**: no es obligatorio, pero está marcado
como **Recomendado** porque sin él el operador no puede coordinar el acceso al sitio.

- Se captura al **crear** el ticket y también en el **formulario de asignación** (que es cuando más
  falta hace), y el despachador puede completarlo o corregirlo después desde el detalle mientras el
  ticket siga abierto; cada cambio queda en el historial.
- Se muestra en la tarjeta del tablero, en el detalle y en la bandeja de fibra como enlace `tel:`,
  para llamar con un toque desde el teléfono del técnico.
- Es **buscable**: `/buscar` y la bandeja de fibra encuentran por número, y sale en el CSV.
- Se admiten dígitos y los separadores `+ ( ) - .` y espacios, con un mínimo de 7 dígitos.

---

## Uso desde el telefono

El sistema esta pensado para usarse en campo, asi que la vista movil no es un
remate: es la mitad del uso real.

- **Menu plegable.** En pantalla estrecha la barra deja a la vista la marca y la
  campana; navegacion, "nueva orden", "nueva interrupcion", mi cuenta y salir se
  agrupan tras el boton de menu, con enlaces grandes.
- **Tablero en vertical.** Las columnas se apilan a lo ancho de la pantalla en
  lugar de formar un carrusel horizontal: se recorren con un scroll normal y la
  cabecera de cada estado queda fija. Arrastrar exige mantener pulsado un
  momento, para que deslizar el dedo no se lleve una tarjeta por accidente.
- **Tablas convertidas en fichas.** Las siete tablas del sistema (busqueda,
  historico, auditoria, usuarios, dashboard y los dos listados) pasan a fichas
  con la etiqueta al lado de cada dato, en vez de obligar a barrer de lado.
- **Filtros plegables.** En `/buscar` solo queda a la vista el cuadro de
  busqueda; los otros doce filtros se despliegan con un boton.
- **Botones a medida del dedo:** minimo 44 px de alto en pantallas tactiles.
- **Sin zoom automatico en iOS:** los campos usan 16 px en movil, que es el
  umbral por debajo del cual Safari amplia la pagina sola al enfocar.
- Modales como hoja inferior, avisos abajo (al alcance del pulgar), graficos y
  formularios a una columna.

---

## La bandeja de fibra

Pensada para cuando se acumula trabajo:

- **Buscador** por folio, identificador externo, cliente, teléfono, título o descripción, que filtra
  mientras escribes.
- **Ordenamiento**: más tiempo esperando (por defecto), derivadas hace poco, prioridad o cliente.
- **Filtro por prioridad** en un solo clic.
- **Ampliar una columna** con el botón `⤡` de su cabecera: esa columna se lleva todo el ancho y
  muestra las tarjetas en rejilla con más datos —cuándo se derivó, cuánto lleva esperando, el
  teléfono del cliente, el operador asignado y el último comentario—, de modo que se revisa todo lo
  que hay en ella sin abrir ticket por ticket. Las otras columnas quedan como tiras estrechas y
  siguen aceptando tarjetas al arrastrar. `⤢ Restaurar` vuelve a las tres columnas.
- Las que llevan más de 4 horas sin revisar se marcan en rojo y se cuentan en el encabezado.

Los filtros viven en la URL, así que se pueden compartir y **sobreviven** tanto al refresco
automático como a mover una tarjeta.

---

## Roles

| Rol | Puede |
|---|---|
| `admin` | Todo, más reabrir tickets cerrados y administrar usuarios |
| `despachador` | Crear tickets con sus fotos, asignar y reasignar, buscar, reportes y dashboard |
| `operador` | Trabajar los tickets asignados a él: diagnosticar, clasificar, derivar a fibra, cerrar |
| `agente_fibra` | Solo interrupciones derivadas: cambiar `estado_fibra` y comentar |

**Un usuario puede tener varios roles a la vez.** Los permisos son la **unión** de los que aportan
sus roles, evaluada contra cada ticket: `mixto1` (despachador + operador) ve todo el tablero, puede
asignarse un ticket a sí mismo y luego trabajarlo y cerrarlo.

### Restablecer contraseñas

El **admin puede restablecer la contraseña de cualquier usuario**, incluida la de otro admin, desde
`/admin/usuarios`:

- **Restablecer clave** (botón en la lista) genera una contraseña temporal y la muestra **una sola
  vez** en el aviso. Usa un alfabeto sin caracteres que se confundan al dictarla por radio o
  teléfono: nada de `0/O` ni `1/l/I`.
- En la pantalla de edición del usuario hay además un bloque para **escribir** una contraseña
  concreta, separado del formulario de datos para que no se dispare al guardar nombre o roles.

Al restablecerle la clave a **otra persona**, esa cuenta queda marcada con
`debe_cambiar_password`: la próxima vez que entre —o de inmediato, si tenía sesión abierta— solo
podrá acceder a `/mi-cuenta` hasta fijar una contraseña propia. En esa pantalla no se le pide la
anterior, porque es la que le dio el administrador. La lista de usuarios muestra un distintivo
**Clave por cambiar** mientras el restablecimiento sigue pendiente. Cuando un admin cambia su
**propia** contraseña no se le exige nada extra.

Las contraseñas solo se guardan hasheadas (scrypt): una clave restablecida no se puede volver a
consultar. Cada restablecimiento queda registrado en el log de la aplicación con quién lo hizo y
sobre quién — nunca la contraseña.

---

## Fotos

Las fotos son **recomendadas, no obligatorias**: un ticket se puede registrar sin ellas —a veces
el reporte entra por teléfono y no hay documento a mano— y completarse después.

- **Orden de trabajo:** anverso y reverso del documento físico.
- **Interrupción:** una foto del reporte.
- Las sube el despachador (o un admin) al crear el ticket, y puede agregarlas o reemplazarlas
  mientras el ticket siga abierto; cada cambio queda en el historial.
- En el detalle, las que faltan aparecen como un hueco con su botón **Agregar** y un aviso de que
  conviene adjuntarlas — nunca como una imagen rota.
- El operador y el agente de fibra **no** suben imágenes: solo comentan.
- Lo que sí se adjunta se valida igual: formato (jpg, png, webp), tamaño máximo y que el archivo
  sea de verdad una imagen, no solo que tenga la extensión.

El bucket es privado. Las imágenes se sirven por `/adjuntos/<tipo>/<id>/<cual>`, que verifica el
permiso sobre el ticket y redirige a una **URL prefirmada** de 15 minutos.

> **Detalle importante de configuración.** La URL prefirmada la abre el *navegador*, no el
> contenedor, así que hacen falta dos endpoints:
>
> - `S3_ENDPOINT_URL=http://garage:3900` — para subir, por la red interna de Docker.
> - `S3_PUBLIC_ENDPOINT=http://localhost:3900` — solo para **firmar** las URL de lectura.
>
> Si ambos apuntan al endpoint interno, las imágenes no cargan en el navegador. Al publicar el
> sistema en un servidor real, `S3_PUBLIC_ENDPOINT` debe ser la dirección por la que los usuarios
> alcanzan el puerto 3900.

---

## Búsqueda, reportes y dashboard

Reservados a `admin` y `despachador`:

- **`/buscar`** — por identificador externo (`ED123456`, `FD1234`…), folio, cliente, texto libre en
  descripciones y comentarios, más filtros de tipo, estado, dependencia, prioridad, operador,
  creador, agente de fibra y rango de fechas. Exporta a CSV.
- **`/reportes/historico`** — qué pasó en un periodo: a quién se asignó cada ticket, en qué estado
  quedó, si pasó por fibra y con qué resultado, y cuánto tomó resolverlo. Exporta a CSV.
- **`/reportes/auditoria`** — bitácora cronológica de todo lo ocurrido (cambios + comentarios), con
  autor y hora. Filtrable por usuario, folio y tipo de evento. Exporta a CSV.
- **`/dashboard`** — tabla comparativa por operador (asignados, soluciones, pendientes, abiertos con
  motivo, derivados a fibra, tiempo promedio, % de cierre), gráficos y desempeño de fibra.

Las **soluciones** se atribuyen desde el historial a quien realmente dio el trabajo por terminado
—el **OK** en las órdenes (el cierre en SIPREC es del despachador, no del operador) y el
**cierre** en las interrupciones—, no a quien figuraba como asignado: un ticket que cambió de
manos se le acredita a quien lo resolvió.

---

## Estructura

```
app/
  models/       usuario (+ usuario_rol), orden_trabajo, interrupcion,
                comentario, historial, notificacion, contador_folio
  services/
    estados.py     ⭐ las dos máquinas de estado: única autoridad sobre quién mueve qué
    tickets.py     crear, asignar, comentar, fotos — escribe historial y notificaciones
    consultas.py   ⭐ cte_tickets(): el UNION ALL de las dos tablas de ticket
    metricas.py    agregados del dashboard
    auditoria.py   feed de historial + comentarios
    storage.py     boto3 → Garage
  security/
    decoradores.py permisos por unión de roles y filtros de visibilidad
  blueprints/   auth, tablero, ordenes, interrupciones, fibra, adjuntos,
                buscar, reportes, dashboard, notificaciones, admin
  templates/    Jinja2 + HTMX; static/ trae htmx, Alpine, Sortable y Chart.js vendorizados
docker/         garage.toml, entrypoint.sh, init/ (layout + bucket + llave)
tests/          pytest
```

Dos reglas de arquitectura que conviene respetar al extender el sistema:

1. **Las vistas nunca cambian un estado directamente.** Todo pasa por
   `services/estados.py::ejecutar_transicion()`, que valida rol + estado de origen + campos
   obligatorios, escribe el historial y dispara las notificaciones. El `data-transiciones` del HTML
   es una ayuda para la interfaz; el servidor siempre revalida.
2. **Nada de `if usuario.rol == "operador"`.** Los permisos salen de `security/decoradores.py` o de
   `services/estados.py`, que manejan la unión de roles.

Como `orden_trabajo` e `interrupcion` son tablas separadas, cualquier consulta que las cruce debe
usar `services/consultas.py::cte_tickets()`. No dupliques ese `UNION ALL`.

---

## Persistencia de los datos

PostgreSQL y Garage **no** usan volúmenes administrados por Docker: escriben directamente en el
sistema de archivos del anfitrión, bajo la ruta que indique `RUTA_DATOS` (por defecto `./datos`).

```
datos/
  postgres/        base de datos completa
  garage/meta/     metadatos del object storage (índice de objetos, llaves, layout)
  garage/data/     los objetos: las fotos de los tickets
```

Consecuencias prácticas:

- **`docker compose down -v` ya no borra nada.** Para empezar de cero hay que borrar `./datos` a
  mano, de forma consciente.
- Se respalda con las herramientas de siempre: `tar`, `rsync`, una copia programada del directorio.
  Para un respaldo consistente de la base, `pg_dump` sigue siendo lo correcto:
  `docker compose exec -T db pg_dump -U tickets tickets > respaldo.sql`.
- `RUTA_DATOS` admite una ruta absoluta: en un servidor conviene algo como
  `RUTA_DATOS=/srv/tickets/datos`, en un disco con respaldo.
- El directorio está en `.gitignore`: nunca entra al repositorio.

> En Docker Desktop para Windows, un bind mount sobre una ruta `C:\...` puede dar problemas de
> permisos a PostgreSQL. Aquí funciona, pero si en otra máquina el contenedor `db` no arranca por
> ese motivo, apunta `RUTA_DATOS` a una ruta dentro de WSL (por ejemplo `/home/usuario/tickets`).

---

## Operación

```bash
docker compose up -d                       # levantar
docker compose logs -f app                 # ver la aplicación
docker compose exec app flask storage-check    # diagnóstico del object storage
docker compose exec app flask crear-admin        # solo el admin (idempotente)
docker compose exec app flask crear-usuario --rol OPERADOR --rol DESPACHADOR
docker compose exec app flask db upgrade   # aplicar migraciones
docker compose down                        # detener (los datos quedan en ./datos)
```

### Pruebas

```bash
docker compose run --rm app pytest
```

Las pruebas usan una base `tickets_test` aparte (se crea sola) y un almacenamiento en memoria: no
tocan Garage ni la base de producción.

### Migraciones

```bash
docker compose exec app flask db migrate -m "descripcion del cambio"
docker compose exec app flask db upgrade
```

El `entrypoint.sh` ya ejecuta `flask db upgrade` en cada arranque.

---

## Notas de despliegue

- **Cambia todos los secretos del `.env`** antes de exponer el sistema: `SECRET_KEY`,
  `POSTGRES_PASSWORD`, `GARAGE_RPC_SECRET`, `GARAGE_ADMIN_TOKEN`, `S3_SECRET_KEY` y las contraseñas
  semilla.
- **`APP_TZ`** viene en `UTC`. Ponle la zona horaria real del grupo (por ejemplo
  `America/Caracas`): todo se almacena en UTC y esto solo afecta cómo se muestran las fechas y cómo
  se cortan los rangos de los reportes.
- Detrás de HTTPS, pon `SESSION_COOKIE_SECURE=true`.
- El límite de intentos de login usa memoria por worker. Si necesitas un límite estricto en toda la
  aplicación, configura `RATELIMIT_STORAGE_URI` apuntando a un Redis.
- La versión de Garage está fijada en `v1.0.1` y `docker/init/garage-init.sh` está escrito contra
  los flags de esa versión. **Si subes de versión mayor, valida el script**: el CLI de Garage cambia
  entre versiones.
- Formatos de llave que exige Garage: `S3_ACCESS_KEY` debe ser `GK` + 24 hexadecimales;
  `S3_SECRET_KEY` y `GARAGE_RPC_SECRET`, 64 hexadecimales.

---

## Diferencias respecto al plan aprobado

Tres decisiones cambiaron durante la construcción, todas verificadas en marcha:

1. **PostgreSQL 18 en vez de 16.** La 16 no se pudo descargar (fallos de red al registry) y la 18
   ya estaba disponible en la máquina. Postgres 18 exige un cambio en el montaje: el volumen va en
   `/var/lib/postgresql`, no en `/var/lib/postgresql/data`, y coloca los datos en un subdirectorio
   por versión mayor. Ya está así en el `docker-compose.yml`. Para volver a la 16, cambia la imagen
   **y** el montaje a `pgdata:/var/lib/postgresql/data`, con el volumen vacío.

2. **CSS propio en vez de compilar Tailwind.** El plan preveía una etapa de build que descargara el
   binario standalone de Tailwind. Se descartó porque añade una descarga frágil a cada `docker
   build`. En su lugar hay una hoja `app/static/css/app.css` con variables CSS, tema claro/oscuro y
   soporte de impresión. El Dockerfile quedó de una sola etapa.

3. **Librerías JS vendorizadas en vez de CDN.** htmx, Alpine, SortableJS y Chart.js viven en
   `app/static/vendor/`. La aplicación funciona completa en una red sin salida a internet, que es
   lo habitual en un NOC.

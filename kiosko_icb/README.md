# Kiosko ICB: ejecución local

La aplicación y el worker se ejecutan directamente en este equipo. PostgreSQL
17.6 se ejecuta en Docker Compose, con puerto `127.0.0.1:5432` y volumen
persistente. Django escucha por HTTP en `127.0.0.1`; Twilio usa HTTPS saliente.
No se requieren Redis, Celery ni un servidor público. SQLite sigue disponible
como alternativa.

## Preparación

Requisitos: Python 3.14, Docker con Compose y el motor de Docker iniciado.
Desde la carpeta `kiosko_icb`:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Configura el archivo local `.env` usando `.env.example` como referencia, sin
compartirlo ni subirlo al repositorio. Si ya existe, conserva sus variables y
la `SECRET_KEY`; no copies el ejemplo encima. Si falta, genera una clave con
`python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'`.
En `.env`, escribe la `SECRET_KEY` entre comillas simples para que Compose no
interprete como variables los caracteres `$` de la clave.

```dotenv
DEBUG=true
ALLOWED_HOSTS=localhost,127.0.0.1
SECURE_SSL_REDIRECT=false
SESSION_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
DB_ENGINE=postgresql
DB_NAME=kiosko_icb
DB_USER=kiosko_user
DB_PASSWORD=CAMBIAR_POR_UNA_CLAVE_SEGURA
DB_HOST=127.0.0.1
DB_PORT=5432
TWILIO_ENABLED=false
TWILIO_STATUS_CALLBACK_ENABLED=false
```

Reemplaza `DB_PASSWORD` por una contraseña aleatoria segura. Compose utiliza
las mismas variables `DB_NAME`, `DB_USER` y `DB_PASSWORD` para inicializar
PostgreSQL. La imagen solo las aplica al crear un volumen vacío: cambiar
después el `.env` no cambia automáticamente el usuario, contraseña ni base
existentes. No borres el volumen para cambiar credenciales.

La configuración local predeterminada no fuerza HTTPS ni cookies seguras,
incluso con `DEBUG=false`. Usa `DEBUG=true` solo para desarrollo local: Django
sirve así los archivos estáticos y multimedia durante el desarrollo. Mantén
el servidor vinculado a `127.0.0.1`.

Inicia PostgreSQL y comprueba su disponibilidad:

```sh
docker compose up -d
docker compose ps
docker compose logs -f postgres
docker compose exec postgres pg_isready
```

Para detener el seguimiento de logs usa `Ctrl+C`. Luego aplica las migraciones:

```sh
python manage.py check
python manage.py migrate
```

Si es una instalación nueva, sin datos restaurados y sin administrador:

```sh
python manage.py createsuperuser
```

Para detener PostgreSQL sin borrar su volumen:

```sh
docker compose down
```

No uses `docker compose down -v`: eliminaría los datos persistidos.

## Iniciar la aplicación

En una terminal, dentro de `kiosko_icb`:

```sh
source .venv/bin/activate
python manage.py runserver 127.0.0.1:8000
```

Abre `http://127.0.0.1:8000/`; el panel está en
`http://127.0.0.1:8000/admin/`. En una segunda terminal:

```sh
cd /ruta/al/kiosko_icb
source .venv/bin/activate
python manage.py procesar_notificaciones --interval 10 --limit 100
```

El worker sigue ejecutándose hasta detenerlo con `Ctrl+C`. Para procesar un
solo lote y terminar, utiliza `python manage.py procesar_notificaciones --once`.
Reinicia Django y el worker después de cambiar `.env`.

## Respaldos y recuperación

Los respaldos contienen datos sensibles: guárdalos con permisos restringidos y
no los subas a Git. El siguiente comando crea un respaldo PostgreSQL en formato
custom; elige un nombre que no exista:

```sh
umask 077
(set -C; docker compose exec -T postgres sh -c \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backup_postgres.dump)
```

Comprueba que el archivo no esté vacío y que PostgreSQL pueda leer su índice:

```sh
test -s backup_postgres.dump
docker compose exec -T postgres pg_restore -l < backup_postgres.dump
```

Para restaurarlo sin sobrescribir la base activa, detén Django y el worker y
crea una base nueva con un nombre que no exista; si ya existe, detente:

```sh
docker compose exec -T postgres sh -c \
  'exec createdb -U "$POSTGRES_USER" kiosko_restaurado'
docker compose exec -T postgres sh -c \
  'exec pg_restore -U "$POSTGRES_USER" -d kiosko_restaurado --no-owner --exit-on-error' \
  < backup_postgres.dump
```

Una restauración fallida puede dejar esa nueva base parcialmente cargada: no
repitas la carga encima. Verifica los datos en la nueva base antes de cambiar
`DB_NAME` en `.env` y reiniciar Django y el worker. Cambiar `DB_NAME` no crea
una base adicional en un volumen ya inicializado. Conserva el respaldo y la
base original.

Para volver temporalmente a SQLite, detén Django y el worker, cambia
`DB_ENGINE=sqlite` en `.env` y reinícialos. Se utilizará el archivo local
`db.sqlite3` con los datos que tenga; **no** se sincroniza automáticamente con
PostgreSQL. Conserva ambas bases y respalda antes de volver a migrar datos.

Para migrar una SQLite existente a una instalación PostgreSQL vacía, detén
Django y el worker, guarda una copia física consistente de `db.sqlite3` y
verifica su integridad. Con `DB_ENGINE=sqlite`, genera un respaldo lógico en
un archivo nuevo:

```sh
(set -C; python manage.py dumpdata --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission > backup_kiosko.json)
```

Verifica el respaldo. Cambia a PostgreSQL solo después de comprobar que la base
de destino está vacía; ejecuta `python manage.py migrate` y luego
`python manage.py loaddata backup_kiosko.json`. Comprueba los datos y relaciones
antes de iniciar Django o el worker. No cargues el volcado sobre datos
existentes ni elimines la SQLite original o su copia.

## Activar envíos de Twilio

En `.env`, configura `TWILIO_ENABLED=true` y los valores reales de:

- `TWILIO_ACCOUNT_SID`.
- `TWILIO_AUTH_TOKEN`, o bien `TWILIO_API_KEY_SID` y
  `TWILIO_API_KEY_SECRET` para autenticar el envío. El Auth Token también es
  obligatorio si activas callbacks.
- `TWILIO_WHATSAPP_FROM`, con formato `whatsapp:+` y número E.164 habilitado.
- `TWILIO_MESSAGING_SERVICE_SID`, con el remitente en su pool.
- `TWILIO_CONTENT_TEMPLATE_NUEVO_ENCARGADO`.
- `TWILIO_CONTENT_TEMPLATE_TOMADO_ENCARGADO`.
- `TWILIO_CONTENT_TEMPLATE_PAGO_ENCARGADO`.
- `TWILIO_CONTENT_TEMPLATE_LISTO_CLIENTE`.
- `TWILIO_CONTENT_TEMPLATE_ANULADO_ENCARGADO`.
- `TWILIO_CONTENT_TEMPLATE_ANULADO_CLIENTE`.

Los Content SID deben corresponder a plantillas aprobadas y sus variables
deben coincidir con las que construye la aplicación. En administración, registra
cada encargado y marca su autorización explícita. Los clientes autorizan sus
notificaciones en el formulario. Revocar una autorización en administración
impide intentos futuros, pero no cancela un envío ya en curso.

Con `TWILIO_ENABLED=false` no se generan nuevas intenciones ni se procesan
pendientes. Al habilitarlo no se crean notificaciones retroactivas. Los pedidos
no esperan una respuesta de Twilio.

## Tomar pedidos desde administración

En la lista de pedidos, selecciona un pedido disponible y ejecuta
**Tomar pedidos disponibles**. Puede hacerlo quien ya tenga acceso a esa
lista en Django Admin (usuario activo y staff con el acceso existente de
consulta o cambio, incluidos los superusuarios). No se crean grupos, roles
ni permisos personalizados, ni hace falta configurar permisos adicionales.

La toma solo permite pedidos en estado `P` sin responsable, independientemente
del estado de pago. Registra al usuario autenticado y la fecha, y cambia el
estado a `E`. Los filtros de asignación muestran disponibles, propios y ajenos.
Responsable y fecha no se pueden editar directamente. El creador del pedido
es independiente de su responsable.

La actualización condicional y las intenciones del Outbox se guardan en una
misma transacción. Si otro usuario ya lo tomó, se muestra un aviso sin
sobrescribir la asignación. Si SQLite está ocupada, la operación falla de
forma controlada: actualiza la lista y vuelve a intentarlo. Un error al
guardar el Outbox revierte la toma; un fallo posterior de Twilio no la revierte.

Vincula opcionalmente cada destinatario encargado WhatsApp con su cuenta Django
para excluirlo de los avisos de sus propias tomas. Este vínculo no concede
acceso ni es necesario para tomar pedidos; los destinatarios sin vínculo
siguen recibiendo avisos si están autorizados. La plantilla aprobada
`TWILIO_CONTENT_TEMPLATE_TOMADO_ENCARGADO` usa `{{1}}` para el número de pedido
y `{{2}}` para el nombre completo del responsable (o su usuario si no tiene
nombre). Solo el worker envía estos mensajes. Reinícialo después de configurar
el Content SID.

Los pedidos existentes quedan sin responsable: solo los que aún estén en `P`
pueden tomarse. Al eliminar una cuenta Django, su responsable se establece en
nulo y se conserva la fecha de asignación; el pedido no vuelve a estar
disponible porque la toma ya lo pasó a `E`.

## Callbacks deshabilitados

Deja `TWILIO_STATUS_CALLBACK_ENABLED=false`; no hace falta configurar
`TWILIO_STATUS_CALLBACK_URL` ni abrir un túnel. La aplicación enviará y
registrará el SID y el estado inicial de Twilio. **No conocerá automáticamente
los estados posteriores de entrega o lectura.**

Si el Messaging Service tiene configurado en la consola de Twilio un *Delivery
Status Callback* predeterminado, Twilio puede usarlo aunque la aplicación no
envíe un callback por mensaje. Elimínalo en la consola si no deseas callbacks.
El endpoint local también rechaza solicitudes mientras la opción esté
deshabilitada.

## Probar callbacks temporalmente

Solo si deseas probar estados, instala y ejecuta opcionalmente Cloudflare
Tunnel o ngrok. Por ejemplo, con `cloudflared` ya instalado:

```sh
cloudflared tunnel --url http://127.0.0.1:8000
```

El comando muestra un hostname HTTPS temporal. Añade ese hostname a
`ALLOWED_HOSTS` junto con los hosts locales y configura en `.env`:

```dotenv
TWILIO_STATUS_CALLBACK_ENABLED=true
TWILIO_STATUS_CALLBACK_URL=https://HOSTNAME_DEL_TUNEL/webhooks/twilio/status/
```

Reemplaza `HOSTNAME_DEL_TUNEL` por el hostname real y configura también
`TWILIO_AUTH_TOKEN`. Reinicia Django y el worker. La aplicación añade a la URL
un token por mensaje y valida siempre `X-Twilio-Signature` con la URL pública
exacta, todos los parámetros y el Auth Token; no es necesario habilitar HTTPS
en Django ni desactivar CSRF globalmente.

**Un túnel puede exponer toda la aplicación, incluido el panel de
administración.** Úsalo solo temporalmente, restringe en el túnel las rutas
expuestas al POST de `/webhooks/twilio/status/`, desactiva `DEBUG` durante la
prueba y detén el túnel al finalizar. En esa prueba puedes iniciar Django con
`python manage.py runserver 127.0.0.1:8000 --insecure` para servir estáticos
con `DEBUG=false`; los archivos multimedia de desarrollo requieren `DEBUG=true`.
No actives autenticación interactiva en el endpoint: Twilio debe poder llegar
al webhook y la aplicación verifica su firma.

El hostname de un túnel temporal puede cambiar: actualiza la URL y
`ALLOWED_HOSTS` y reinicia ambos procesos. Los mensajes enviados sin callback
no reciben retroactivamente actualizaciones al habilitarlo.

## Pruebas y recuperación

Ejecuta `python manage.py test`. La suite simula Twilio y no envía mensajes.
Para la suite de pedidos y kiosko usa `python manage.py test pedidos kiosko`;
PostgreSQL necesita que `DB_USER` pueda crear la base de pruebas.
Los rechazos HTTP 429 se reintentan con límite. Los timeouts o procesos
interrumpidos quedan en estado incierto para revisión: no se reenvían
automáticamente, ya que el proveedor podría haber aceptado el mensaje.
Consulta las notificaciones y sus intentos en administración.

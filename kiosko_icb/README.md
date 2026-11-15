# Kiosko ICB: ejecución local

La aplicación usa SQLite y se ejecuta en este equipo. Django escucha por HTTP
en `127.0.0.1`; el SDK de Twilio realiza sus solicitudes salientes por HTTPS.
El worker es otro proceso local. No se requieren Redis, Docker ni un servidor
público.

## Preparación

Desde la carpeta `kiosko_icb`, con Python 3.14:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Configura el archivo local `.env`, sin compartirlo ni subirlo al repositorio.
Conserva la `SECRET_KEY` existente; si falta, genera una con
`python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'`
y añádela al archivo. Para funcionamiento local:

```dotenv
DEBUG=true
ALLOWED_HOSTS=localhost,127.0.0.1
SECURE_SSL_REDIRECT=false
SESSION_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
TWILIO_ENABLED=false
TWILIO_STATUS_CALLBACK_ENABLED=false
```

La configuración local predeterminada no fuerza HTTPS ni cookies seguras,
incluso con `DEBUG=false`. Usa `DEBUG=true` solo para desarrollo local: Django
sirve así los archivos estáticos y multimedia durante el desarrollo. Mantén
el servidor vinculado a `127.0.0.1`.

Aplica las migraciones a SQLite y, si aún no tienes un administrador, créalo:

```sh
python manage.py migrate
python manage.py createsuperuser
```

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

## Activar envíos de Twilio

En `.env`, configura `TWILIO_ENABLED=true` y los valores reales de:

- `TWILIO_ACCOUNT_SID`.
- `TWILIO_AUTH_TOKEN`, o bien `TWILIO_API_KEY_SID` y
  `TWILIO_API_KEY_SECRET` para autenticar el envío. El Auth Token también es
  obligatorio si activas callbacks.
- `TWILIO_WHATSAPP_FROM`, con formato `whatsapp:+` y número E.164 habilitado.
- `TWILIO_MESSAGING_SERVICE_SID`, con el remitente en su pool.
- `TWILIO_CONTENT_TEMPLATE_NUEVO_ENCARGADO`.
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
Los rechazos HTTP 429 se reintentan con límite. Los timeouts o procesos
interrumpidos quedan en estado incierto para revisión: no se reenvían
automáticamente, ya que el proveedor podría haber aceptado el mensaje.
Consulta las notificaciones y sus intentos en administración.

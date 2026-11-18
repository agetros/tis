# Kiosko ICB

La aplicación Django se ejecuta localmente y utiliza PostgreSQL 17.6 en Docker
Compose. PostgreSQL publica el puerto `127.0.0.1:5432` y conserva los datos en
un volumen. SQLite está disponible como alternativa. La aplicación no requiere
un proceso de fondo adicional.

## Preparación

Requisitos: Python 3.14, Docker Compose y el motor de Docker iniciado. Desde la
carpeta `kiosko_icb`:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Configura `.env` usando `.env.example` como referencia. No compartas ni subas
el archivo local. Si ya existe, conserva sus variables y su `SECRET_KEY`; no
copies el ejemplo encima. Si falta, genera una clave con:

```sh
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

Escribe `SECRET_KEY` entre comillas simples en `.env` para que Compose no
interprete como variables los caracteres `$`. Reemplaza `DB_PASSWORD` por una
contraseña aleatoria segura. Compose usa `DB_NAME`, `DB_USER` y `DB_PASSWORD`
al inicializar PostgreSQL. La imagen aplica esos valores solo al crear un
volumen vacío; cambiar `.env` no modifica las credenciales de una base
existente.

La configuración local predeterminada no fuerza HTTPS ni cookies seguras.
Usa `DEBUG=true` solo en desarrollo local para servir archivos estáticos y
multimedia. Mantén el servidor vinculado a `127.0.0.1`.

Inicia PostgreSQL y verifica su disponibilidad:

```sh
docker compose up -d
docker compose ps
docker compose exec postgres pg_isready
```

Aplica las migraciones:

```sh
python manage.py check
python manage.py migrate
```

En una instalación nueva, crea un administrador:

```sh
python manage.py createsuperuser
```

Inicia la aplicación:

```sh
python manage.py runserver 127.0.0.1:8000
```

Abre `http://127.0.0.1:8000/`; Django Admin está en
`http://127.0.0.1:8000/admin/`. Para detener PostgreSQL sin borrar sus datos:

```sh
docker compose down
```

No uses `docker compose down -v`: eliminaría el volumen persistente.

## Administración de pedidos

En la lista de pedidos, selecciona uno disponible y ejecuta
**Tomar pedidos disponibles**. La acción está disponible para usuarios activos
con acceso existente de consulta o cambio en Django Admin, incluidos los
superusuarios. No se crean roles ni permisos personalizados.

Solo se pueden tomar pedidos en estado `P` sin responsable,
independientemente del estado de pago. La toma registra al usuario y la fecha,
y cambia el estado a `E`. Los filtros permiten ver pedidos disponibles,
asignados a la persona usuaria o a otras personas. Responsable y fecha no se
pueden editar directamente. El creador del pedido es independiente de quien lo
toma.

La actualización condicional evita sobrescribir una asignación concurrente. Si
otra persona ya tomó el pedido, Django Admin muestra un aviso. Si SQLite está
ocupada, la operación falla de forma controlada; actualiza la lista y vuelve a
intentarlo. Al eliminar una cuenta, su pedido conserva la fecha de asignación
y no vuelve a estar disponible.

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

Para restaurar sin sobrescribir la base activa, crea una base nueva con un
nombre que no exista:

```sh
docker compose exec -T postgres sh -c \
  'exec createdb -U "$POSTGRES_USER" kiosko_restaurado'
docker compose exec -T postgres sh -c \
  'exec pg_restore -U "$POSTGRES_USER" -d kiosko_restaurado --no-owner --exit-on-error' \
  < backup_postgres.dump
```

Una restauración fallida puede dejar la nueva base parcialmente cargada: no
repitas la carga encima. Verifica los datos antes de cambiar `DB_NAME` en
`.env`. Cambiar `DB_NAME` no crea otra base en un volumen ya inicializado.
Conserva el respaldo y la base original.

Para usar SQLite, cambia `DB_ENGINE=sqlite` en `.env` y reinicia Django. Se
utilizará el archivo local `db.sqlite3`; los datos no se sincronizan
automáticamente con PostgreSQL. Conserva ambas bases y respalda antes de
migrar datos.

Para migrar una SQLite existente a una instalación PostgreSQL vacía, guarda una
copia física consistente de `db.sqlite3` y verifica su integridad. Con
`DB_ENGINE=sqlite`, crea un respaldo lógico en un archivo nuevo:

```sh
(set -C; python manage.py dumpdata --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission > backup_kiosko.json)
```

Verifica el respaldo y confirma que la base de destino está vacía antes de
ejecutar `python manage.py migrate` y `python manage.py loaddata
backup_kiosko.json`. Comprueba los datos y las relaciones; no cargues el volcado
sobre datos existentes ni elimines la SQLite original o su copia.

## Validación

Ejecuta los chequeos y pruebas desde el entorno virtual:

```sh
python manage.py check
python manage.py makemigrations --check
python manage.py test
```

La suite de pedidos y autoservicio puede ejecutarse por separado con
`python manage.py test pedidos kiosko`. PostgreSQL necesita que `DB_USER`
pueda crear la base de pruebas.

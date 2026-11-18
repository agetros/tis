# Repository guidance

## Setup and validation

The Django application lives in `kiosko_icb/`, not the repository root.
Run the following commands from that directory. Python 3.14 is documented in
`kiosko_icb/README.md`; dependencies are in `requirements.txt`.

```sh
cd kiosko_icb
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Configure `.env` using `.env.example` as a reference. Preserve an existing
`.env` and its `SECRET_KEY`; do not overwrite it with the example. Quote
`SECRET_KEY` with single quotes so Compose does not interpolate `$`.

The documented local setup runs Django on the host and PostgreSQL in Docker:

```sh
docker compose up -d
docker compose ps
docker compose exec postgres pg_isready
python manage.py check
python manage.py migrate
python manage.py createsuperuser  # New installations only.
python manage.py runserver 127.0.0.1:8000
```

Validation uses Django's built-in test runner and system checks:

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
python manage.py test pedidos kiosko
python manage.py test pedidos.tests.TomaPedidoTests
python manage.py test kiosko.tests.AutoservicioTests.test_order_uses_server_price_and_keeps_payment_pending
```

`DB_ENGINE` selects `postgresql` or `sqlite`. PostgreSQL tests require a database
user that can create the test database. To run a test without PostgreSQL or
editing `.env`, prefix the command with `DB_ENGINE=sqlite`. Assignment
concurrency tests in `pedidos.tests.TomaPedidoConcurrenciaTests` use real
transactions and threads, with backend-specific PostgreSQL/SQLite assertions;
retain that distinction when changing assignment logic.

## Architecture

- `kiosko_icb/kiosko_icb/` configures Django and routes `/` to the `kiosko` app
  and `/admin/` to Django Admin, styled with `django-unfold`.
- `productos` owns categories, product prices, stock, and uploaded images.
  `pedidos` owns orders and line items; `finanzas` owns payment methods and
  financial movements. `pedidos/services.py` coordinates these models.
- `kiosko` is the customer-facing, server-rendered catalog and checkout.
  `CheckoutForm` parses form fields, views call order services, and checkout
  returns JSON containing either `redirect_url` or an `error` with HTTP 400.
  Staff order actions in `pedidos/admin.py` call the same service layer;
  payment and cancellation actions have confirmation templates.
- Shared templates are in `kiosko_icb/templates/`; customer pages are in
  `kiosko/templates/kiosko/`. The frontend uses Bootstrap from a CDN plus
  `static/css/styles.css` and vanilla `static/js/scripts.js`. Catalog data is
  passed through Django's `json_script`; JavaScript keeps the cart in
  localStorage and submits `FormData`, including the CSRF token.
- The root-level `html_css/` is a separate static academic-resource page, not
  the Django kiosk frontend.

## Domain and implementation conventions

- Keep order mutations in `pedidos/services.py`. Creation, payment,
  cancellation, readiness, and completion use atomic transactions and raise
  Django `ValidationError` for business failures; views/admin translate these
  into customer errors or staff messages.
- Checkout items contain `product_id` and `quantity`. The server validates
  integer IDs and quantities, aggregates duplicate products, caps each product
  at 99 units, and derives prices from the database, never from browser prices.
  Product prices are decimal, but order line prices and totals are integer
  Chilean pesos rounded with `Decimal` and `ROUND_HALF_UP`. Keep catalog,
  service, and `kiosko_tags.clp` rounding consistent.
- Creating an order checks stock but does not reserve or deduct it. Confirming
  payment deducts stock with conditional `F()` updates and records an income
  movement (`I`) in the same transaction. Cancelling a paid order requires
  explicit refund confirmation, restores stock, and records an expense (`E`).
  Preserve guards against repeat payment/refund and partial updates.
- Order state and payment state are separate: order codes are `P` pending,
  `E` in progress, `L` ready, `C` completed, `A` cancelled; payment codes are
  `P` pending, `G` paid, `A` cancelled. Order numbers use `ICB-{pk:06d}`.
  Only ready orders can be completed.
- Taking an order requires `estado="P"` and no `responsable`, regardless of
  payment state. `tomar_pedido` uses a conditional update as its transaction's
  first query to prevent concurrent reassignment, sets state `E`, and records
  `responsable`/`asignado_en` separately from `creado_por`. Reuse existing
  active staff/admin view-or-change access rather than adding custom roles.
  SQLite busy/locked errors become controlled validation failures; unrelated
  database errors must propagate. Assignment fields stay read-only in admin.
- Confirmation access is session-scoped: `pedidos_kiosko` stores the last 50
  order IDs created by that session, and other sessions receive HTTP 404.
  Preserve this check rather than authorizing access by order ID alone.
- Registered admin classes inherit `unfold.admin.ModelAdmin`. Orders cannot be
  added through admin; financial movements cannot be added or edited there.
- Domain names and customer/admin messages use Spanish; localization is
  `es-cl` and timezone is `America/Santiago`.

## Local configuration and data

`kiosko_icb/README.md` documents database setup, backups, and recovery. Keep the
development server on loopback; `DEBUG=true` enables local static/media serving.
PostgreSQL uses a persistent Compose volume. `docker compose down` preserves
it; do not use `docker compose down -v`. Changing `.env` credentials does not
change an already initialized database. Switching to SQLite uses the local
`db.sqlite3` and does not synchronize data between backends. Do not commit
local `.env`, databases, or backups.

## Commit messages

Follow `kiosko_icb/.github/instructions/commit-messages.md`: an imperative
subject of at most 72 characters without a trailing period, followed by a
2-4-line body explaining what changed, why, and important implementation
details. Use `type(scope): subject` when applicable.

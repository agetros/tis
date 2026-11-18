import json
import os
import runpy
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

from django.test import Client, LiveServerTestCase, TestCase, override_settings
from django.urls import reverse

from finanzas.models import MedioPago
from pedidos.models import DetallePedido, Pedido
from productos.models import Categoria, Producto

from .forms import CheckoutForm


@override_settings(SECURE_SSL_REDIRECT=False)
class AutoservicioTests(TestCase):
    def setUp(self):
        self.category = Categoria.objects.create(nombre="Cafetería")
        self.product = Producto.objects.create(
            nombre="Café americano",
            descripcion="Café de grano",
            precio=Decimal("1250"),
            categoria=self.category,
            stock=3,
        )
        self.payment_method = MedioPago.objects.create(tipo="EF", nombre="Efectivo")

    def test_catalog_uses_database_products_and_payment_methods(self):
        response = self.client.get(reverse("index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Café americano")
        self.assertContains(response, "$1.250")
        self.assertContains(response, "Efectivo")
        self.assertContains(response, 'name="telefono_cliente"')
        self.assertContains(response, "bootstrap@5.3.9")
        self.assertContains(response, "row-cols-2 row-cols-sm-3 row-cols-lg-4")
        self.assertContains(response, "modal-dialog-centered")

    def test_order_uses_server_price_and_keeps_payment_pending(self):
        response = self.client.post(
            reverse("crear_pedido"),
            {
                "items": json.dumps(
                    [{"product_id": self.product.pk, "quantity": 2, "price": 1}]
                ),
                "medio_pago_id": self.payment_method.pk,
                "cliente": "  Alex  ",
                "telefono_cliente": "+56 9 1234 5678",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        pedido = Pedido.objects.get()
        detalle = DetallePedido.objects.get(pedido=pedido)
        self.assertEqual(pedido.numero_pedido, f"ICB-{pedido.pk:06d}")
        self.assertEqual(pedido.total, 2500)
        self.assertEqual(pedido.cliente, "Alex")
        self.assertEqual(pedido.telefono_cliente, "+56 9 1234 5678")
        self.assertEqual(pedido.estado_pago, "P")
        self.assertEqual(detalle.precio_unitario, 1250)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertEqual(
            response.json()["redirect_url"],
            reverse("pedido_confirmacion", args=[pedido.pk]),
        )
        confirmation = self.client.get(response.json()["redirect_url"])
        self.assertContains(confirmation, "¡Tu pedido está registrado!")
        self.assertContains(confirmation, f"ICB-{pedido.pk:06d}")

    def test_order_rejects_quantity_above_current_stock(self):
        response = self.client.post(
            reverse("crear_pedido"),
            {
                "items": json.dumps([{"product_id": self.product.pk, "quantity": 4}]),
                "medio_pago_id": self.payment_method.pk,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Stock insuficiente", response.json()["error"])
        self.assertFalse(Pedido.objects.exists())

    def test_order_confirmation_is_scoped_to_the_session_that_created_it(self):
        pedido = Pedido.objects.create(numero_pedido="ICB-000001")

        response = self.client.get(reverse("pedido_confirmacion", args=[pedido.pk]))

        self.assertEqual(response.status_code, 404)

    def test_checkout_renderiza_los_campos_del_formulario(self):
        tarjeta = MedioPago.objects.create(tipo="TC", nombre="Tarjeta")
        response = self.client.get(reverse("index"))
        self.assertIsInstance(response.context["checkout_form"], CheckoutForm)
        self.assertContains(response, 'name="items"')
        self.assertContains(response, 'id="customer-name"')
        self.assertContains(response, 'id="customer-phone"')
        self.assertNotContains(response, "WhatsApp")
        self.assertContains(response, 'name="medio_pago_id"')
        self.assertContains(response, f'value="{self.payment_method.pk}"')
        self.assertContains(response, "Tarjeta")

        class Inputs(HTMLParser):
            def __init__(self):
                super().__init__()
                self.radios = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "input" and attrs.get("name") == "medio_pago_id":
                    self.radios.append(attrs)

        parser = Inputs()
        parser.feed(response.content.decode())
        self.assertEqual(
            {radio["value"] for radio in parser.radios},
            {str(self.payment_method.pk), str(tarjeta.pk)},
        )
        for radio in parser.radios:
            self.assertEqual(radio["type"], "radio")
            self.assertEqual(radio["class"], "form-check-input")
            self.assertIn("required", radio)

    def test_checkout_sin_medios_de_pago_deshabilita_confirmacion(self):
        self.payment_method.delete()
        response = self.client.get(reverse("index"))
        self.assertContains(response, "No hay medios de pago disponibles en este momento.")

        class SubmitButtons(HTMLParser):
            def __init__(self):
                super().__init__()
                self.buttons = []

            def handle_starttag(self, tag, attrs):
                if tag == "button":
                    self.buttons.append(dict(attrs))

        parser = SubmitButtons()
        parser.feed(response.content.decode())
        self.assertTrue(any("disabled" in button for button in parser.buttons))

    def test_formulario_limpia_items_y_conserva_el_nombre_ingresado(self):
        data = {
            "items": json.dumps([{"product_id": self.product.pk, "quantity": 1}]),
            "medio_pago_id": str(self.payment_method.pk),
            "cliente": "  Alex  ",
            "telefono_cliente": "+56 9 1234 5678",
        }
        form = CheckoutForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["items"][0]["product_id"], self.product.pk)
        self.assertEqual(form.cleaned_data["medio_pago_id"], self.payment_method.pk)
        self.assertEqual(form.cleaned_data["cliente"], "  Alex  ")

    def test_checkout_conserva_errores_y_prioridad_de_validacion(self):
        items = json.dumps([{"product_id": self.product.pk, "quantity": 1}])
        casos = [
            ({}, "El detalle del pedido no tiene un formato válido."),
            ({"items": items}, "Selecciona un medio de pago disponible."),
            ({"items": items, "medio_pago_id": "no-numero"},
             "Selecciona un medio de pago disponible."),
            ({"items": items, "medio_pago_id": 999999},
             "El medio de pago seleccionado ya no está disponible."),
            ({"items": "{}", "medio_pago_id": self.payment_method.pk},
             "Agrega al menos un producto antes de confirmar."),
            ({"items": items, "medio_pago_id": self.payment_method.pk, "cliente": "x" * 101},
             "El nombre no puede superar los 100 caracteres."),
            ({"items": items, "medio_pago_id": self.payment_method.pk,
              "telefono_cliente": " " * 21}, "El teléfono es demasiado largo."),
        ]
        for datos, mensaje in casos:
            with self.subTest(datos=datos):
                response = self.client.post(reverse("crear_pedido"), datos)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"error": mensaje})
                self.assertFalse(Pedido.objects.exists())

    def test_checkout_preserva_campos_y_cantidades_invalidas(self):
        for item, mensaje in (
            ({"product_id": True, "quantity": 1}, "Uno de los productos no es válido."),
            ({"product_id": self.product.pk, "quantity": 0},
             "La cantidad de un producto no es válida."),
            ({"product_id": self.product.pk, "quantity": 4}, "Stock insuficiente"),
        ):
            with self.subTest(item=item):
                response = self.client.post(
                    reverse("crear_pedido"),
                    {"items": json.dumps([item]), "medio_pago_id": self.payment_method.pk},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(mensaje, response.json()["error"])
                self.assertFalse(Pedido.objects.exists())

    def test_http_local_con_cookies_y_csrf_sin_debug(self):
        settings_path = Path(__file__).resolve().parent.parent / "kiosko_icb" / "settings.py"
        with patch.dict(os.environ, {"DEBUG": "false"}, clear=True), patch("dotenv.load_dotenv"):
            local = runpy.run_path(str(settings_path))
        with override_settings(
            DEBUG=False, ALLOWED_HOSTS=["localhost"],
            SECURE_SSL_REDIRECT=local["SECURE_SSL_REDIRECT"],
            SESSION_COOKIE_SECURE=local["SESSION_COOKIE_SECURE"],
            CSRF_COOKIE_SECURE=local["CSRF_COOKIE_SECURE"],
        ):
            cliente = Client(enforce_csrf_checks=True)
            respuesta = cliente.get(reverse("index"), HTTP_HOST="localhost")
            self.assertEqual(respuesta.status_code, 200)
            csrf = respuesta.cookies["csrftoken"]
            self.assertFalse(csrf["secure"])
            respuesta = cliente.post(
                reverse("crear_pedido"),
                {
                    "items": json.dumps([{"product_id": self.product.pk, "quantity": 1}]),
                    "medio_pago_id": self.payment_method.pk,
                },
                HTTP_HOST="localhost", HTTP_X_CSRFTOKEN=csrf.value,
            )
            self.assertEqual(respuesta.status_code, 200)
            self.assertFalse(respuesta.cookies["sessionid"]["secure"])


@override_settings(SECURE_SSL_REDIRECT=False)
class ServidorLocalTests(LiveServerTestCase):
    def test_servidor_responde_por_http_en_loopback(self):
        self.assertTrue(self.live_server_url.startswith("http://localhost:"))
        with urlopen(self.live_server_url, timeout=5) as respuesta:
            self.assertEqual(respuesta.status, 200)

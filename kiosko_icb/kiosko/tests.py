import json
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from finanzas.models import MedioPago
from pedidos.models import DetallePedido, Pedido
from productos.models import Categoria, Producto


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

    def test_order_uses_server_price_and_keeps_payment_pending(self):
        response = self.client.post(
            reverse("crear_pedido"),
            {
                "items": json.dumps(
                    [{"product_id": self.product.pk, "quantity": 2, "price": 1}]
                ),
                "medio_pago_id": self.payment_method.pk,
                "cliente": "  Alex  ",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        pedido = Pedido.objects.get()
        detalle = DetallePedido.objects.get(pedido=pedido)
        self.assertEqual(pedido.numero_pedido, f"ICB-{pedido.pk:06d}")
        self.assertEqual(pedido.total, 2500)
        self.assertEqual(pedido.cliente, "Alex")
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

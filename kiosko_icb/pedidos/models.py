from django.conf import settings
from django.db import models

from productos.models import Producto

ESTADOS_PEDIDO = [
    ("P", "Pendiente"),
    ("E", "En Proceso"),
    ("C", "Completado"),
    ("A", "Anulado"),
]

ESTADOS_PAGO = [
    ("P", "Pendiente"),
    ("G", "Pagado"),
    ("A", "Anulado"),
]

ORIGEN_PEDIDO = [
    ("K", "Autoservicio"),
    ("A", "Atendido por encargado"),
]


class Pedido(models.Model):
    fecha = models.DateTimeField(auto_now_add=True)
    numero_pedido = models.CharField(max_length=20, unique=True, blank=True)
    cliente = models.CharField(max_length=100, blank=True, default="")
    origen = models.CharField(max_length=1, choices=ORIGEN_PEDIDO, default="K")
    estado = models.CharField(max_length=1, choices=ESTADOS_PEDIDO, default="P")
    estado_pago = models.CharField(max_length=1, choices=ESTADOS_PAGO, default="P")
    total = models.IntegerField(default=0)
    medio_pago = models.ForeignKey(
        "finanzas.MedioPago", on_delete=models.SET_NULL, null=True, blank=True
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Pedido"
        verbose_name_plural = "Pedidos"

    def __str__(self):
        return self.numero_pedido or f"Pedido {self.pk}"


class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="detalle")
    producto = models.ForeignKey(Producto, on_delete=models.RESTRICT)
    cantidad = models.IntegerField(default=1)
    precio_unitario = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Detalle de Pedido"
        verbose_name_plural = "Detalles de Pedido"

    def __str__(self):
        return f"{self.producto} - " f"{self.cantidad} x {self.precio_unitario}"

from django.db import models

from finanzas.models import MedioPago
from productos.models import Producto

ESTADOS_PEDIDO = [
    ("P", "Pendiente"),
    ("E", "En Proceso"),
    ("C", "Completado"),
    ("A", "Anulado"),
]


# Create your models here.
class Pedido(models.Model):
    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=1, choices=ESTADOS_PEDIDO, default="P")
    total = models.IntegerField(default=0)
    medio_pago = models.ForeignKey(
        "finanzas.MedioPago", on_delete=models.SET_NULL, null=True, blank=True
    )
    numero_pedido = models.CharField(max_length=20, unique=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Pedido {self.id} - {self.fecha}"

    def generar_numero_pedido(self):
        if not self.numero_pedido:
            self.numero_pedido = f"PED-{self.id}"
        return self.numero_pedido


class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="detalle")
    producto = models.ForeignKey(Producto, on_delete=models.RESTRICT)
    cantidad = models.IntegerField(default=1)
    precio_unitario = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.producto} - {self.cantidad} x {self.precio_unitario}"

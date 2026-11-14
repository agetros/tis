from django.db import models

TIPOS_PAGO = [
    ("EF", "Efectivo"),
    ("TC", "Tarjeta de Débito/Crédito"),
    ("TR", "Transferencia Bancaria"),
]


class MedioPago(models.Model):
    tipo = models.CharField(max_length=2, choices=TIPOS_PAGO)
    nombre = models.CharField(max_length=100)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Medio de Pago"
        verbose_name_plural = "Medios de Pago"

    def __str__(self):
        return f"{self.nombre} ({self.get_tipo_display()})"


class MovimientoFinanciero(models.Model):

    TIPOS_MOVIMIENTO = [
        ("I", "Ingreso"),
        ("E", "Egreso"),
    ]

    pedido = models.ForeignKey(
        "pedidos.Pedido", on_delete=models.PROTECT, related_name="movimientos"
    )

    medio_pago = models.ForeignKey(
        MedioPago, on_delete=models.PROTECT, related_name="movimientos"
    )

    tipo = models.CharField(max_length=1, choices=TIPOS_MOVIMIENTO, default="I")

    monto = models.DecimalField(max_digits=10, decimal_places=2)

    descripcion = models.CharField(max_length=200, blank=True)

    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Movimiento Financiero"
        verbose_name_plural = "Movimientos Financieros"

    def __str__(self):
        return f"{self.get_tipo_display()} - ${self.monto}"

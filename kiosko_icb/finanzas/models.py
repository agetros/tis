from django.db import models

# Create your models here.
TIPOS_PAGO = [
    ("EF", "Efectivo"),
    ("TC", "Tarjeta de Débito/Crédito"),
]


class MedioPago(models.Model):
    tipo = models.CharField(max_length=2, choices=TIPOS_PAGO)
    nombre = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.nombre} ({self.get_tipo_display()})"

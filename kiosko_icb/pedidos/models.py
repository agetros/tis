import uuid

from django.conf import settings
from django.db import models

from productos.models import Producto

ESTADOS_PEDIDO = [
    ("P", "Pendiente"),
    ("E", "En Proceso"),
    ("L", "Listo para retirar"),
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
    telefono_cliente = models.CharField(max_length=20, blank=True)
    acepta_notificaciones_whatsapp = models.BooleanField(default=False)
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
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pedidos_asignados",
        editable=False,
    )
    asignado_en = models.DateTimeField(null=True, blank=True, editable=False)
    actualizado_en = models.DateTimeField(auto_now=True)
    version_notificacion = models.PositiveIntegerField(default=0, editable=False)

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


class NotificacionWhatsApp(models.Model):

    EVENTOS = [
        ("N", "Pedido nuevo"),
        ("P", "Pago confirmado"),
        ("L", "Pedido listo"),
        ("A", "Pedido anulado"),
    ]

    ESTADOS = [
        ("P", "Pendiente"),
        ("E", "Aceptado por Meta"),
        ("F", "Fallido"),
    ]

    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.PROTECT,
        related_name="notificaciones",
    )
    evento = models.CharField(max_length=1, choices=EVENTOS)
    telefono = models.CharField(max_length=20)
    estado = models.CharField(
        max_length=1,
        choices=ESTADOS,
        default="P",
    )
    identificador_whatsapp = models.CharField(
        max_length=150,
        blank=True,
    )
    error = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Notificación WhatsApp"
        verbose_name_plural = "Notificaciones WhatsApp"
        constraints = [
            models.UniqueConstraint(
                fields=["pedido", "evento", "telefono"],
                name="unique_notificacion_pedido_evento_telefono",
            )
        ]

    def __str__(self):
        return f"{self.pedido} - {self.get_evento_display()}"


class EncargadoWhatsApp(models.Model):
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20, unique=True)
    autorizado = models.BooleanField(default=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="destinatarios_whatsapp",
        help_text="Solo identifica al usuario para excluir sus avisos de toma de pedido.",
    )

    class Meta:
        verbose_name = "Destinatario encargado WhatsApp"
        verbose_name_plural = "Destinatarios encargados WhatsApp"

    def __str__(self):
        return self.nombre


class NotificacionSalida(models.Model):
    class Procesamiento(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        PROCESANDO = "procesando", "Procesando"
        ACEPTADO = "aceptado", "Aceptado"
        FALLIDO = "fallido", "Fallido"
        INCIERTO = "incierto", "Resultado incierto"
        CANCELADO = "cancelado", "Cancelado"

    class Destinatario(models.TextChoices):
        CLIENTE = "cliente", "Cliente"
        ENCARGADO = "encargado", "Encargado"

    pedido = models.ForeignKey(
        Pedido, on_delete=models.PROTECT, related_name="notificaciones_salida"
    )
    evento = models.CharField(
        max_length=1,
        choices=NotificacionWhatsApp.EVENTOS + [("T", "Pedido tomado")],
    )
    clave_evento = models.CharField(max_length=100)
    tipo_destinatario = models.CharField(max_length=10, choices=Destinatario.choices)
    telefono = models.CharField(max_length=20)
    encargado = models.ForeignKey(
        EncargadoWhatsApp, null=True, blank=True, on_delete=models.PROTECT
    )
    proveedor = models.CharField(max_length=30, default="twilio")
    parametros = models.JSONField(default=dict)
    token_callback = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    estado = models.CharField(
        max_length=12, choices=Procesamiento.choices, default=Procesamiento.PENDIENTE
    )
    estado_proveedor = models.CharField(max_length=30, blank=True)
    identificador_proveedor = models.CharField(
        max_length=150, null=True, blank=True, unique=True
    )
    codigo_error = models.CharField(max_length=40, blank=True)
    error = models.TextField(blank=True)
    intentos = models.PositiveIntegerField(default=0)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    ultimo_intento = models.DateTimeField(null=True, blank=True)
    proximo_intento = models.DateTimeField(null=True, blank=True)
    enviado_en = models.DateTimeField(null=True, blank=True)
    entregado_en = models.DateTimeField(null=True, blank=True)
    leido_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Notificación de salida"
        verbose_name_plural = "Notificaciones de salida"
        constraints = [
            models.UniqueConstraint(
                fields=["clave_evento", "tipo_destinatario", "telefono"],
                name="unique_salida_evento_destinatario",
            )
        ]
        indexes = [models.Index(fields=["estado", "proximo_intento"])]

    def __str__(self):
        return f"{self.pedido} - {self.get_evento_display()}"


class IntentoNotificacion(models.Model):
    notificacion = models.ForeignKey(
        NotificacionSalida, on_delete=models.PROTECT, related_name="historial_intentos"
    )
    numero = models.PositiveIntegerField()
    iniciado_en = models.DateTimeField()
    finalizado_en = models.DateTimeField(null=True, blank=True)
    resultado = models.CharField(max_length=20, default="iniciado")
    codigo_error = models.CharField(max_length=40, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        verbose_name = "Intento de notificación"
        verbose_name_plural = "Intentos de notificación"
        constraints = [
            models.UniqueConstraint(
                fields=["notificacion", "numero"], name="unique_intento_notificacion"
            )
        ]

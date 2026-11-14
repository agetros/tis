from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from finanzas.models import MedioPago, MovimientoFinanciero
from productos.models import Producto

from .models import Pedido


def generar_link_whatsapp(pedido):
    mensaje = f"Hola, quiero realizar un pedido: #PED-{pedido.id}\n\n"

    for detalle in pedido.detalles.all():
        mensaje += f"- {detalle.cantidad} x {detalle.producto.nombre}\n"

    mensaje += f"\nTotal: ${pedido.total}\n"

    mensaje = quote(mensaje)
    return f"https://wa.me/{settings.WHATSAPP_NUMBER}?text={quote(mensaje)}"


@transaction.atomic
def marcar_como_pagado(pedido_id, medio_pago_id):

    # Bloquear el pedido durante la operación.
    pedido = Pedido.objects.select_for_update().get(pk=pedido_id)

    # Evitar pagos duplicados.
    if pedido.estado_pago == "G":
        raise ValidationError("Este pedido ya está pagado.")

    if pedido.estado_pago == "A" or pedido.estado == "A":
        raise ValidationError("No se puede pagar un pedido anulado.")

    if pedido.total <= 0:
        raise ValidationError("El pedido no tiene un total válido.")

    # Verificar que existan productos en el pedido.
    detalles = list(
        pedido.detalle.values("producto_id")
        .annotate(cantidad_total=Sum("cantidad"))
        .order_by("producto_id")
    )

    if not detalles:
        raise ValidationError("El pedido no contiene productos.")

    medio_pago = MedioPago.objects.get(pk=medio_pago_id)

    # Evitar registrar un ingreso duplicado.
    if pedido.movimientos.filter(tipo="I").exists():
        raise ValidationError("Este pedido ya tiene un ingreso registrado.")

    # Descontar el stock de cada producto.
    for detalle in detalles:

        cantidad = detalle["cantidad_total"]

        if cantidad <= 0:
            raise ValidationError("Cantidad de producto inválida.")

        actualizado = Producto.objects.filter(
            pk=detalle["producto_id"], stock__gte=cantidad
        ).update(stock=F("stock") - cantidad, actualizado_en=timezone.now())

        if actualizado == 0:
            producto = Producto.objects.get(pk=detalle["producto_id"])

            raise ValidationError(
                f"Stock insuficiente para {producto.nombre}. "
                f"Disponible: {producto.stock}."
            )

    # Registrar el ingreso financiero.
    MovimientoFinanciero.objects.create(
        pedido=pedido,
        medio_pago=medio_pago,
        tipo="I",
        monto=pedido.total,
        descripcion=f"Pago del pedido {pedido.numero_pedido}",
    )

    # Actualizar el pedido.
    pedido.estado_pago = "G"
    pedido.medio_pago = medio_pago
    pedido.save(update_fields=["estado_pago", "medio_pago", "actualizado_en"])

    return pedido

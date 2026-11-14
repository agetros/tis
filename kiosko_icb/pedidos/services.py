from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from finanzas.models import MedioPago, MovimientoFinanciero
from productos.models import Producto

from .models import DetallePedido, Pedido


@transaction.atomic
def crear_pedido_autoservicio(items, medio_pago_id, cliente=""):
    if not isinstance(items, list) or not items:
        raise ValidationError("Agrega al menos un producto antes de confirmar.")

    cantidades = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("El detalle del pedido no es válido.")

        producto_id = item.get("product_id")
        cantidad = item.get("quantity")
        if type(producto_id) is not int or producto_id < 1:
            raise ValidationError("Uno de los productos no es válido.")
        if type(cantidad) is not int or cantidad < 1 or cantidad > 99:
            raise ValidationError("La cantidad de un producto no es válida.")
        cantidades[producto_id] = cantidades.get(producto_id, 0) + cantidad
        if cantidades[producto_id] > 99:
            raise ValidationError("Puedes pedir hasta 99 unidades de un mismo producto.")

    if type(medio_pago_id) is not int or medio_pago_id < 1:
        raise ValidationError("Selecciona un medio de pago disponible.")

    if not isinstance(cliente, str):
        raise ValidationError("El nombre ingresado no es válido.")
    nombre_cliente = cliente.strip()
    if len(nombre_cliente) > 100:
        raise ValidationError("El nombre no puede superar los 100 caracteres.")

    productos = {
        producto.pk: producto
        for producto in Producto.objects.select_for_update()
        .filter(pk__in=cantidades)
        .order_by("pk")
    }
    if len(productos) != len(cantidades):
        raise ValidationError("Uno de los productos ya no está disponible.")

    for producto_id, cantidad in cantidades.items():
        producto = productos[producto_id]
        if producto.stock < cantidad:
            raise ValidationError(
                f"Stock insuficiente para {producto.nombre}. "
                f"Disponible: {producto.stock}."
            )

    try:
        medio_pago = MedioPago.objects.get(pk=medio_pago_id)
    except MedioPago.DoesNotExist as error:
        raise ValidationError("El medio de pago seleccionado ya no está disponible.") from error

    detalles = []
    total = 0
    for producto_id, cantidad in cantidades.items():
        producto = productos[producto_id]
        precio = int(producto.precio.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += precio * cantidad
        detalles.append(
            DetallePedido(
                producto=producto,
                cantidad=cantidad,
                precio_unitario=precio,
            )
        )

    pedido = Pedido.objects.create(
        cliente=nombre_cliente,
        origen="K",
        estado="P",
        estado_pago="P",
        medio_pago=medio_pago,
        total=total,
    )
    pedido.numero_pedido = f"ICB-{pedido.pk:06d}"
    pedido.save(update_fields=["numero_pedido", "actualizado_en"])
    for detalle in detalles:
        detalle.pedido = pedido
    DetallePedido.objects.bulk_create(detalles)
    return pedido


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

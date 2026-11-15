from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from finanzas.models import MedioPago, MovimientoFinanciero
from productos.models import Producto

from . import notificaciones
from .models import DetallePedido, Pedido


def _generar_numero_pedido(pedido):
    pedido.numero_pedido = f"ICB-{pedido.pk:06d}"
    pedido.save(update_fields=["numero_pedido", "actualizado_en"])
    return pedido


def _validar_datos_cliente(
    cliente,
    telefono_cliente,
    acepta_notificaciones_whatsapp,
):
    if not isinstance(cliente, str):
        raise ValidationError("El nombre ingresado no es válido.")

    if len(cliente.strip()) > 100:
        raise ValidationError("El nombre no puede superar los 100 caracteres.")

    if not isinstance(telefono_cliente, str):
        raise ValidationError("El teléfono ingresado no es válido.")

    if len(telefono_cliente) > 20:
        raise ValidationError("El teléfono es demasiado largo.")

    if type(acepta_notificaciones_whatsapp) is not bool:
        raise ValidationError("La autorización de WhatsApp no es válida.")

    if acepta_notificaciones_whatsapp and not telefono_cliente.strip():
        raise ValidationError("Ingresa un teléfono para recibir notificaciones.")


def _crear_detalles_pedido(pedido, items):

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

        if type(cantidad) is not int or not 1 <= cantidad <= 99:
            raise ValidationError("La cantidad de un producto no es válida.")

        cantidades[producto_id] = cantidades.get(producto_id, 0) + cantidad

        if cantidades[producto_id] > 99:
            raise ValidationError(
                "Puedes pedir hasta 99 unidades de un mismo producto."
            )

    productos = {
        producto.pk: producto
        for producto in Producto.objects.select_for_update()
        .filter(pk__in=cantidades)
        .order_by("pk")
    }

    if len(productos) != len(cantidades):
        raise ValidationError("Uno de los productos ya no está disponible.")

    detalles = []
    total = 0

    for producto_id, cantidad in cantidades.items():

        producto = productos[producto_id]

        if producto.stock < cantidad:
            raise ValidationError(
                f"Stock insuficiente para {producto.nombre}. "
                f"Disponible: {producto.stock}."
            )

        precio = int(
            Decimal(producto.precio).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )

        total += precio * cantidad

        detalles.append(
            DetallePedido(
                pedido=pedido,
                producto=producto,
                cantidad=cantidad,
                precio_unitario=precio,
            )
        )

    DetallePedido.objects.bulk_create(detalles)

    return total


@transaction.atomic
def crear_pedido_autoservicio(
    items,
    medio_pago_id,
    cliente="",
    telefono_cliente="",
    acepta_notificaciones_whatsapp=False,
):

    _validar_datos_cliente(
        cliente,
        telefono_cliente,
        acepta_notificaciones_whatsapp,
    )

    if type(medio_pago_id) is not int or medio_pago_id < 1:
        raise ValidationError("Selecciona un medio de pago disponible.")

    try:
        medio_pago = MedioPago.objects.get(pk=medio_pago_id)
    except MedioPago.DoesNotExist as error:
        raise ValidationError(
            "El medio de pago seleccionado ya no está disponible."
        ) from error

    pedido = Pedido.objects.create(
        cliente=cliente.strip(),
        telefono_cliente=telefono_cliente.strip(),
        acepta_notificaciones_whatsapp=(acepta_notificaciones_whatsapp),
        origen="K",
        estado="P",
        estado_pago="P",
        medio_pago=medio_pago,
    )

    _generar_numero_pedido(pedido)

    pedido.total = _crear_detalles_pedido(
        pedido,
        items,
    )

    pedido.save(update_fields=["total", "actualizado_en"])

    # Evento 1: nuevo pedido.
    notificaciones.notificar_pedido_nuevo(pedido)

    return pedido


@transaction.atomic
def crear_pedido_encargado(
    items,
    medio_pago_id,
    usuario,
    cliente="",
    telefono_cliente="",
    acepta_notificaciones_whatsapp=False,
):

    _validar_datos_cliente(
        cliente,
        telefono_cliente,
        acepta_notificaciones_whatsapp,
    )

    if type(medio_pago_id) is not int or medio_pago_id < 1:
        raise ValidationError("Selecciona un medio de pago disponible.")

    try:
        medio_pago = MedioPago.objects.get(pk=medio_pago_id)
    except MedioPago.DoesNotExist as error:
        raise ValidationError("El medio de pago seleccionado no existe.") from error

    pedido = Pedido.objects.create(
        cliente=cliente.strip(),
        telefono_cliente=telefono_cliente.strip(),
        acepta_notificaciones_whatsapp=(acepta_notificaciones_whatsapp),
        origen="A",
        estado="P",
        estado_pago="P",
        medio_pago=medio_pago,
        creado_por=usuario,
    )

    _generar_numero_pedido(pedido)

    pedido.total = _crear_detalles_pedido(
        pedido,
        items,
    )

    pedido.save(update_fields=["total", "actualizado_en"])

    # Evento 1: nuevo pedido.
    notificaciones.notificar_pedido_nuevo(pedido)

    return pedido


@transaction.atomic
def marcar_como_pagado(pedido_id, medio_pago_id):

    pedido = Pedido.objects.select_for_update().get(pk=pedido_id)

    if pedido.estado_pago == "G":
        raise ValidationError("Este pedido ya está pagado.")

    if pedido.estado_pago == "A" or pedido.estado == "A":
        raise ValidationError("No se puede pagar un pedido anulado.")

    if pedido.total <= 0:
        raise ValidationError("El pedido no tiene un total válido.")

    detalles = list(
        pedido.detalle.values("producto_id")
        .annotate(cantidad_total=Sum("cantidad"))
        .order_by("producto_id")
    )

    if not detalles:
        raise ValidationError("El pedido no contiene productos.")

    try:
        medio_pago = MedioPago.objects.get(pk=medio_pago_id)
    except MedioPago.DoesNotExist as error:
        raise ValidationError("El medio de pago seleccionado no existe.") from error

    if pedido.movimientos.filter(tipo="I").exists():
        raise ValidationError("Este pedido ya tiene un ingreso registrado.")

    # Descontar inventario.
    for detalle in detalles:

        cantidad = detalle["cantidad_total"]

        if cantidad <= 0:
            raise ValidationError("Cantidad de producto inválida.")

        actualizado = Producto.objects.filter(
            pk=detalle["producto_id"],
            stock__gte=cantidad,
        ).update(
            stock=F("stock") - cantidad,
            actualizado_en=timezone.now(),
        )

        if actualizado == 0:

            producto = Producto.objects.get(pk=detalle["producto_id"])

            raise ValidationError(
                f"Stock insuficiente para {producto.nombre}. "
                f"Disponible: {producto.stock}."
            )

    # Registrar ingreso financiero.
    MovimientoFinanciero.objects.create(
        pedido=pedido,
        medio_pago=medio_pago,
        tipo="I",
        monto=pedido.total,
        descripcion=(f"Pago del pedido {pedido.numero_pedido}"),
    )

    pedido.estado_pago = "G"
    pedido.medio_pago = medio_pago

    pedido.save(
        update_fields=[
            "estado_pago",
            "medio_pago",
            "actualizado_en",
        ]
    )

    # Evento 2: pago confirmado.
    notificaciones.notificar_pago_confirmado(pedido)

    return pedido


@transaction.atomic
def marcar_como_listo(pedido_id):

    pedido = Pedido.objects.select_for_update().get(pk=pedido_id)

    if pedido.estado in ("C", "A"):
        raise ValidationError("El pedido ya está finalizado o anulado.")

    if pedido.estado == "L":
        raise ValidationError("El pedido ya está listo para retirar.")

    pedido.estado = "L"

    pedido.save(update_fields=["estado", "actualizado_en"])

    # Evento 3: pedido listo.
    notificaciones.notificar_pedido_listo(pedido)

    return pedido


@transaction.atomic
def completar_pedido(pedido_id):

    pedido = Pedido.objects.select_for_update().get(pk=pedido_id)

    if pedido.estado != "L":
        raise ValidationError("Solo puedes completar pedidos listos para retirar.")

    pedido.estado = "C"

    pedido.save(update_fields=["estado", "actualizado_en"])

    return pedido


@transaction.atomic
def anular_pedido(
    pedido_id,
    reembolso_confirmado=False,
):

    pedido = Pedido.objects.select_for_update().get(pk=pedido_id)

    if pedido.estado == "A":
        raise ValidationError("El pedido ya está anulado.")

    if pedido.estado == "C":
        raise ValidationError("No se puede anular un pedido completado.")

    if pedido.estado_pago == "G":

        if not reembolso_confirmado:
            raise ValidationError(
                "Debes confirmar el reembolso antes de anular " "un pedido pagado."
            )

        if pedido.movimientos.filter(tipo="E").exists():
            raise ValidationError("Este pedido ya tiene un reembolso registrado.")

        detalles = list(
            pedido.detalle.values("producto_id").annotate(
                cantidad_total=Sum("cantidad")
            )
        )

        # Devolver inventario.
        for detalle in detalles:

            Producto.objects.filter(pk=detalle["producto_id"]).update(
                stock=F("stock") + detalle["cantidad_total"],
                actualizado_en=timezone.now(),
            )

        # Registrar egreso por devolución.
        MovimientoFinanciero.objects.create(
            pedido=pedido,
            medio_pago=pedido.medio_pago,
            tipo="E",
            monto=pedido.total,
            descripcion=(f"Reembolso del pedido {pedido.numero_pedido}"),
        )

    pedido.estado = "A"
    pedido.estado_pago = "A"

    pedido.save(
        update_fields=[
            "estado",
            "estado_pago",
            "actualizado_en",
        ]
    )

    # Evento 4: pedido anulado.
    notificaciones.notificar_pedido_anulado(pedido)

    return pedido

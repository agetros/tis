import logging

from django.conf import settings
from django.db import transaction

from .integrations.whatsapp import enviar_template_whatsapp
from .models import NotificacionWhatsApp

logger = logging.getLogger(__name__)


def normalizar_telefono(telefono):

    telefono = "".join(
        caracter for caracter in str(telefono or "") if caracter.isdigit()
    )

    # Formato chileno: agregar código de país
    # cuando se ingresa un celular nacional de 9 dígitos.
    if len(telefono) == 9 and telefono.startswith("9"):
        telefono = "56" + telefono

    if not 8 <= len(telefono) <= 15:
        raise ValueError("Número telefónico inválido.")

    return telefono


def formato_pesos(valor):
    return f"${int(valor):,}".replace(",", ".")


def obtener_productos(pedido):

    detalles = pedido.detalle.select_related("producto")

    return ", ".join(
        f"{detalle.cantidad}x {detalle.producto.nombre}" for detalle in detalles
    )


def enviar_notificacion(notificacion_id, parametros):

    notificacion = NotificacionWhatsApp.objects.get(pk=notificacion_id)

    if notificacion.estado == "E":
        return

    try:
        resultado = enviar_template_whatsapp(
            telefono=notificacion.telefono,
            evento=notificacion.evento,
            parametros=parametros,
        )

        mensaje = resultado.get("messages", [{}])[0]

        notificacion.estado = "E"
        notificacion.identificador_whatsapp = mensaje.get("id", "")
        notificacion.error = ""

    except Exception as error:

        logger.exception(
            "Error enviando notificación WhatsApp. Pedido: %s",
            notificacion.pedido_id,
        )

        notificacion.estado = "F"
        notificacion.error = str(error)[:2000]

    notificacion.save(
        update_fields=[
            "estado",
            "identificador_whatsapp",
            "error",
        ]
    )


def programar_notificacion(
    pedido,
    evento,
    telefono,
    parametros,
):

    if not telefono:
        return

    try:
        telefono = normalizar_telefono(telefono)
    except ValueError:
        logger.warning(
            "Teléfono inválido para pedido %s",
            pedido.pk,
        )
        return

    notificacion, creada = NotificacionWhatsApp.objects.get_or_create(
        pedido=pedido,
        evento=evento,
        telefono=telefono,
    )

    if not creada:

        if notificacion.estado in ("P", "E"):
            return

        notificacion.estado = "P"
        notificacion.error = ""

        notificacion.save(update_fields=["estado", "error"])

    transaction.on_commit(
        lambda: enviar_notificacion(
            notificacion.pk,
            parametros,
        )
    )


def notificar_pedido_nuevo(pedido):

    parametros = [
        pedido.numero_pedido,
        pedido.cliente or "Sin nombre",
        obtener_productos(pedido),
        formato_pesos(pedido.total),
    ]

    programar_notificacion(
        pedido=pedido,
        evento="N",
        telefono=settings.WHATSAPP_RECEIVER,
        parametros=parametros,
    )


def notificar_pago_confirmado(pedido):

    parametros = [
        pedido.numero_pedido,
        formato_pesos(pedido.total),
        str(pedido.medio_pago),
    ]

    programar_notificacion(
        pedido=pedido,
        evento="P",
        telefono=settings.WHATSAPP_RECEIVER,
        parametros=parametros,
    )


def notificar_pedido_listo(pedido):

    if not pedido.acepta_notificaciones_whatsapp:
        return

    parametros = [
        pedido.cliente or "Cliente",
        pedido.numero_pedido,
    ]

    programar_notificacion(
        pedido=pedido,
        evento="L",
        telefono=pedido.telefono_cliente,
        parametros=parametros,
    )


def notificar_pedido_anulado(pedido):

    parametros = [
        pedido.numero_pedido,
        pedido.cliente or "Sin nombre",
    ]

    # Notificación al encargado.
    programar_notificacion(
        pedido=pedido,
        evento="A",
        telefono=settings.WHATSAPP_RECEIVER,
        parametros=parametros,
    )

    # Notificación al cliente con consentimiento.
    if pedido.acepta_notificaciones_whatsapp:

        programar_notificacion(
            pedido=pedido,
            evento="A",
            telefono=pedido.telefono_cliente,
            parametros=parametros,
        )

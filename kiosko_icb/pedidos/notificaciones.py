import logging
import re

from django.conf import settings

from .models import EncargadoWhatsApp, NotificacionSalida

logger = logging.getLogger(__name__)


def normalizar_telefono(telefono):
    """Normaliza móviles chilenos explícitos, sin inferir otros países."""
    telefono = str(telefono or "").strip()
    if not re.fullmatch(r"\+?[0-9 ()-]+", telefono):
        raise ValueError("Ingresa un número móvil chileno válido.")
    numero = re.sub(r"[ ()-]", "", telefono)
    if re.fullmatch(r"9[0-9]{8}", numero):
        numero = "+56" + numero
    elif re.fullmatch(r"569[0-9]{8}", numero):
        numero = "+" + numero
    elif not re.fullmatch(r"\+569[0-9]{8}", numero):
        raise ValueError("Ingresa un número móvil chileno válido.")
    return numero


def formato_pesos(valor):
    return f"${int(valor):,}".replace(",", ".")


def obtener_productos(pedido):
    return ", ".join(
        f"{detalle.cantidad}x {detalle.producto.nombre}"
        for detalle in pedido.detalle.select_related("producto")
    )


def _registrar(pedido, evento, tipo, telefono, parametros, encargado=None):
    try:
        telefono = normalizar_telefono(telefono)
    except ValueError:
        logger.warning("Destinatario inválido para pedido %s, evento %s", pedido.pk, evento)
        return
    NotificacionSalida.objects.get_or_create(
        clave_evento=f"pedido:{pedido.pk}:transicion:{pedido.version_notificacion}",
        tipo_destinatario=tipo,
        telefono=telefono,
        defaults={
            "pedido": pedido,
            "evento": evento,
            "parametros": parametros,
            "encargado": encargado,
        },
    )


def _encargados(pedido, evento, parametros):
    for encargado in EncargadoWhatsApp.objects.filter(autorizado=True):
        _registrar(
            pedido, evento, NotificacionSalida.Destinatario.ENCARGADO,
            encargado.telefono, parametros, encargado,
        )


def _cliente(pedido, evento, parametros):
    if pedido.acepta_notificaciones_whatsapp:
        _registrar(
            pedido, evento, NotificacionSalida.Destinatario.CLIENTE,
            pedido.telefono_cliente, parametros,
        )


def notificar_pedido_nuevo(pedido):
    if not settings.TWILIO_ENABLED:
        return
    _encargados(pedido, "N", {
        "1": pedido.numero_pedido,
        "2": pedido.cliente or "Sin nombre",
        "3": obtener_productos(pedido),
        "4": formato_pesos(pedido.total),
    })


def notificar_pago_confirmado(pedido):
    if not settings.TWILIO_ENABLED:
        return
    _encargados(pedido, "P", {
        "1": pedido.numero_pedido,
        "2": formato_pesos(pedido.total),
        "3": str(pedido.medio_pago),
    })


def notificar_pedido_listo(pedido):
    if settings.TWILIO_ENABLED:
        _cliente(pedido, "L", {
            "1": pedido.cliente or "Cliente",
            "2": pedido.numero_pedido,
        })


def notificar_pedido_anulado(pedido):
    if not settings.TWILIO_ENABLED:
        return
    parametros = {"1": pedido.numero_pedido, "2": pedido.cliente or "Sin nombre"}
    _encargados(pedido, "A", parametros)
    _cliente(pedido, "A", parametros)

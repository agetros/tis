import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from .integrations.whatsapp import ErrorEnvio, ProveedorMensajeria, TwilioWhatsApp
from .models import IntentoNotificacion, NotificacionSalida
from .notificaciones import normalizar_telefono

logger = logging.getLogger(__name__)
MAX_INTENTOS = 5
TIEMPO_ABANDONO = timedelta(minutes=5)

ORDEN_ESTADOS = {
    "accepted": 0, "queued": 1, "sending": 2, "sent": 3,
    "failed": 3, "delivered": 4, "undelivered": 4, "read": 5,
}


def actualizar_estado_proveedor(pk, sid, estado, codigo=""):
    """Aplica callbacks repetidos o desordenados sin retroceder el estado."""
    if estado not in ORDEN_ESTADOS:
        return False
    for _ in range(5):
        try:
            actual = NotificacionSalida.objects.get(pk=pk)
        except NotificacionSalida.DoesNotExist:
            return False
        if actual.identificador_proveedor not in (None, sid):
            return False
        if actual.identificador_proveedor is None and actual.estado not in (
            NotificacionSalida.Procesamiento.PROCESANDO,
            NotificacionSalida.Procesamiento.INCIERTO,
        ):
            return False
        previo = actual.estado_proveedor
        if previo and ORDEN_ESTADOS.get(previo, -1) >= ORDEN_ESTADOS[estado]:
            return True
        ahora = timezone.now()
        cambios = {
            "identificador_proveedor": sid,
            "estado_proveedor": estado,
            "estado": (
                NotificacionSalida.Procesamiento.FALLIDO
                if estado in ("failed", "undelivered")
                else NotificacionSalida.Procesamiento.ACEPTADO
            ),
            "actualizado_en": ahora,
        }
        if estado in ("failed", "undelivered"):
            cambios.update(codigo_error=str(codigo)[:40], error="El proveedor informó un fallo.")
        else:
            cambios.update(codigo_error="", error="")
        if estado == "sent":
            cambios["enviado_en"] = actual.enviado_en or ahora
        elif estado == "delivered":
            cambios["entregado_en"] = actual.entregado_en or ahora
        elif estado == "read":
            cambios["leido_en"] = actual.leido_en or ahora
        actualizado = NotificacionSalida.objects.filter(
            pk=pk, estado_proveedor=previo,
            identificador_proveedor=actual.identificador_proveedor, estado=actual.estado,
        ).update(**cambios)
        if actualizado:
            return True
    logger.error("No se pudo actualizar el estado de la notificación %s por concurrencia", pk)
    return False


def recuperar_abandonadas():
    ahora = timezone.now()
    cantidad = NotificacionSalida.objects.filter(
        estado=NotificacionSalida.Procesamiento.PROCESANDO,
        ultimo_intento__lt=ahora - TIEMPO_ABANDONO,
    ).update(
        estado=NotificacionSalida.Procesamiento.INCIERTO,
        error="Proceso interrumpido: revisar antes de reenviar.",
        actualizado_en=ahora,
    )
    IntentoNotificacion.objects.filter(
        notificacion__estado=NotificacionSalida.Procesamiento.INCIERTO,
        resultado="iniciado",
        iniciado_en__lt=ahora - TIEMPO_ABANDONO,
    ).update(
        resultado="incierto",
        finalizado_en=ahora,
        error="Proceso interrumpido: revisar antes de reenviar.",
    )
    return cantidad


def _autorizada(notificacion):
    if notificacion.tipo_destinatario == NotificacionSalida.Destinatario.CLIENTE:
        if not notificacion.pedido.acepta_notificaciones_whatsapp:
            return False
        telefono = notificacion.pedido.telefono_cliente
    else:
        if not notificacion.encargado or not notificacion.encargado.autorizado:
            return False
        telefono = notificacion.encargado.telefono
    try:
        return normalizar_telefono(telefono) == notificacion.telefono
    except ValueError:
        return False


def procesar_pendientes(limite=100, proveedor: ProveedorMensajeria | None = None):
    if not settings.TWILIO_ENABLED:
        return 0
    recuperar_abandonadas()
    proveedor = proveedor or TwilioWhatsApp()
    ahora = timezone.now()
    candidatos = list(
        NotificacionSalida.objects.filter(estado=NotificacionSalida.Procesamiento.PENDIENTE)
        .filter(Q(proximo_intento__isnull=True) | Q(proximo_intento__lte=ahora))
        .order_by("creado_en", "pk").values_list("pk", flat=True)[:limite]
    )
    procesados = 0
    for pk in candidatos:
        ahora = timezone.now()
        reclamado = NotificacionSalida.objects.filter(
            pk=pk, estado=NotificacionSalida.Procesamiento.PENDIENTE
        ).filter(Q(proximo_intento__isnull=True) | Q(proximo_intento__lte=ahora)).update(
            estado=NotificacionSalida.Procesamiento.PROCESANDO,
            ultimo_intento=ahora, intentos=F("intentos") + 1, actualizado_en=ahora,
        )
        if not reclamado:
            continue
        procesados += 1
        notificacion = NotificacionSalida.objects.select_related("pedido", "encargado").get(pk=pk)
        intento = IntentoNotificacion.objects.create(
            notificacion=notificacion, numero=notificacion.intentos,
            iniciado_en=notificacion.ultimo_intento,
        )
        if not _autorizada(notificacion):
            NotificacionSalida.objects.filter(
                pk=pk, estado=NotificacionSalida.Procesamiento.PROCESANDO
            ).update(
                estado=NotificacionSalida.Procesamiento.CANCELADO,
                error="Consentimiento revocado o destinatario modificado.",
                actualizado_en=timezone.now(),
            )
            intento.resultado = "cancelado"
            intento.finalizado_en = timezone.now()
            intento.error = "Consentimiento revocado o destinatario modificado."
            intento.save(update_fields=["resultado", "finalizado_en", "error"])
            continue
        try:
            resultado = proveedor.enviar(notificacion)
        except ErrorEnvio as error:
            if error.incierto:
                estado = NotificacionSalida.Procesamiento.INCIERTO
            elif error.temporal and notificacion.intentos < MAX_INTENTOS:
                estado = NotificacionSalida.Procesamiento.PENDIENTE
            else:
                estado = NotificacionSalida.Procesamiento.FALLIDO
            proximo = (
                timezone.now() + timedelta(seconds=30 * 2 ** (notificacion.intentos - 1))
                if estado == NotificacionSalida.Procesamiento.PENDIENTE else None
            )
            NotificacionSalida.objects.filter(
                pk=pk, estado=NotificacionSalida.Procesamiento.PROCESANDO
            ).update(
                estado=estado, codigo_error=error.codigo[:40], error=str(error)[:2000],
                proximo_intento=proximo, actualizado_en=timezone.now(),
            )
            intento.resultado = estado
            intento.codigo_error = error.codigo[:40]
            intento.error = str(error)[:2000]
            intento.finalizado_en = timezone.now()
            intento.save(update_fields=["resultado", "codigo_error", "error", "finalizado_en"])
        else:
            correlacionado = actualizar_estado_proveedor(
                pk, resultado.identificador, resultado.estado
            )
            if not correlacionado:
                logger.error("No se pudo correlacionar el envío de notificación %s", pk)
                NotificacionSalida.objects.filter(
                    pk=pk, estado=NotificacionSalida.Procesamiento.PROCESANDO
                ).update(
                    estado=NotificacionSalida.Procesamiento.INCIERTO,
                    error="No se pudo correlacionar la respuesta del proveedor.",
                    actualizado_en=timezone.now(),
                )
            intento.resultado = "aceptado" if correlacionado else "incierto"
            intento.finalizado_en = timezone.now()
            intento.save(update_fields=["resultado", "finalizado_en"])
    return procesados

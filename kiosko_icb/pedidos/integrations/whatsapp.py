"""Contrato y adaptador para el envío de notificaciones."""

import json
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from requests.exceptions import RequestException
from twilio.base.exceptions import TwilioRestException
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client


@dataclass(frozen=True)
class ResultadoEnvio:
    identificador: str
    estado: str


class ErrorEnvio(Exception):
    def __init__(self, mensaje, codigo="", temporal=False, incierto=False):
        super().__init__(mensaje)
        self.codigo = str(codigo or "")
        self.temporal = temporal
        self.incierto = incierto


class ProveedorMensajeria(Protocol):
    def enviar(self, notificacion) -> ResultadoEnvio: ...


PLANTILLAS = {
    ("N", "encargado"): ("nuevo_encargado", ("1", "2", "3", "4")),
    ("T", "encargado"): ("tomado_encargado", ("1", "2")),
    ("P", "encargado"): ("pago_encargado", ("1", "2", "3")),
    ("L", "cliente"): ("listo_cliente", ("1", "2")),
    ("A", "encargado"): ("anulado_encargado", ("1", "2")),
    ("A", "cliente"): ("anulado_cliente", ("1", "2")),
}


class TwilioWhatsApp:
    def enviar(self, notificacion):
        plantilla = PLANTILLAS.get((notificacion.evento, notificacion.tipo_destinatario))
        if not plantilla:
            raise ErrorEnvio("Evento sin plantilla configurada.")
        clave, requeridas = plantilla
        content_sid = settings.TWILIO_CONTENT_TEMPLATES.get(clave)
        if not content_sid or not re.fullmatch(r"HX[0-9a-fA-F]{32}", content_sid):
            raise ErrorEnvio("Content SID ausente o inválido.")
        parametros = notificacion.parametros
        if not isinstance(parametros, dict) or any(
            not isinstance(parametros.get(clave), str) or not parametros[clave].strip()
            for clave in requeridas
        ):
            raise ErrorEnvio("Faltan variables requeridas para la plantilla.")
        if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_WHATSAPP_FROM
                and settings.TWILIO_MESSAGING_SERVICE_SID):
            raise ErrorEnvio("Configuración Twilio incompleta.")
        if not re.fullmatch(r"whatsapp:\+[1-9][0-9]{7,14}", settings.TWILIO_WHATSAPP_FROM):
            raise ErrorEnvio("Remitente WhatsApp inválido.")
        api_key, api_secret = settings.TWILIO_API_KEY_SID, settings.TWILIO_API_KEY_SECRET
        if bool(api_key) != bool(api_secret):
            raise ErrorEnvio("Configuración de API Key Twilio incompleta.")
        if not settings.TWILIO_AUTH_TOKEN and (
            not api_key or settings.TWILIO_STATUS_CALLBACK_ENABLED
        ):
            raise ErrorEnvio("Auth Token Twilio requerido para autenticación o callbacks.")
        argumentos = {
            "from_": settings.TWILIO_WHATSAPP_FROM,
            "to": f"whatsapp:{notificacion.telefono}",
            "messaging_service_sid": settings.TWILIO_MESSAGING_SERVICE_SID,
            "content_sid": content_sid,
            "content_variables": json.dumps(parametros),
        }
        if settings.TWILIO_STATUS_CALLBACK_ENABLED:
            callback = settings.TWILIO_STATUS_CALLBACK_URL
            try:
                url = urlsplit(callback)
                _ = url.port
            except ValueError as error:
                raise ErrorEnvio("URL de callback inválida; se requiere una URL HTTPS pública.") from error
            if (url.scheme != "https" or not url.hostname or url.username
                    or url.password or url.query or url.fragment):
                raise ErrorEnvio("URL de callback inválida; se requiere una URL HTTPS pública.")
            argumentos["status_callback"] = (
                f"{callback}?{urlencode({'n': str(notificacion.token_callback)})}"
            )
        http_client = TwilioHttpClient(timeout=15, max_retries=0)
        client = Client(
            api_key or settings.TWILIO_ACCOUNT_SID,
            api_secret or settings.TWILIO_AUTH_TOKEN,
            account_sid=settings.TWILIO_ACCOUNT_SID,
            http_client=http_client,
        )
        try:
            mensaje = client.messages.create(**argumentos)
        except TwilioRestException as error:
            if error.status == 429:
                raise ErrorEnvio("Twilio limitó las solicitudes.", error.code, temporal=True) from error
            if error.status is None or error.status == 408 or error.status >= 500:
                raise ErrorEnvio("Resultado Twilio desconocido.", error.code, incierto=True) from error
            raise ErrorEnvio("Twilio rechazó la solicitud.", error.code) from error
        except RequestException as error:
            raise ErrorEnvio("Resultado de comunicación desconocido.", incierto=True) from error
        except (ValueError, AttributeError) as error:
            raise ErrorEnvio("Respuesta de Twilio inválida.", incierto=True) from error
        if not mensaje.sid or not re.fullmatch(r"(SM|MM)[0-9a-fA-F]{32}", mensaje.sid):
            raise ErrorEnvio("Respuesta de Twilio sin SID válido.", incierto=True)
        if mensaje.status not in ("accepted", "queued", "sending", "sent", "delivered", "read"):
            raise ErrorEnvio("Respuesta de Twilio con estado inesperado.", incierto=True)
        return ResultadoEnvio(mensaje.sid, mensaje.status)

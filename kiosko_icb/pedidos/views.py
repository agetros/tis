import re
import uuid
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from twilio.request_validator import RequestValidator

from .models import NotificacionSalida
from .procesamiento import ORDEN_ESTADOS, actualizar_estado_proveedor


@csrf_exempt
@require_POST
def twilio_status_callback(request):
    base = settings.TWILIO_STATUS_CALLBACK_URL
    parsed = urlsplit(base)
    if not settings.TWILIO_AUTH_TOKEN or not base or parsed.query or parsed.fragment:
        return HttpResponse(status=503)
    if request.path != parsed.path:
        return HttpResponse(status=403)
    query = request.META.get("QUERY_STRING", "")
    if set(request.GET) != {"n"} or len(request.GET.getlist("n")) != 1:
        return HttpResponse(status=400)
    try:
        token = uuid.UUID(request.GET["n"])
    except ValueError:
        return HttpResponse(status=400)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not RequestValidator(settings.TWILIO_AUTH_TOKEN).validate(
        f"{base}?{query}", request.POST, signature
    ):
        return HttpResponse(status=403)
    sid = request.POST.get("MessageSid", "")
    estado = request.POST.get("MessageStatus", "")
    if request.POST.get("EventType") == "READ" and estado == "delivered":
        estado = "read"
    codigo = request.POST.get("ErrorCode", "")
    if (not re.fullmatch(r"(SM|MM)[0-9a-fA-F]{32}", sid)
            or estado not in ORDEN_ESTADOS
            or (codigo and not re.fullmatch(r"[0-9]{1,20}", codigo))):
        return HttpResponse(status=400)
    pk = NotificacionSalida.objects.filter(token_callback=token).values_list("pk", flat=True).first()
    if pk is None:
        return HttpResponse(status=404)
    if not actualizar_estado_proveedor(pk, sid, estado, codigo):
        return HttpResponse(status=409)
    return HttpResponse(status=204)

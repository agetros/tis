from urllib.parse import quote
from django.conf import settings

def generar_link_whatsapp(pedido):
    mensaje = f"Hola, quiero realizar un pedido: #PED-{pedido.id}\n\n"

    for detalle in pedido.detalles.all():
        mensaje += f"- {detalle.cantidad} x {detalle.producto.nombre}\n"

    mensaje += f"\nTotal: ${pedido.total}\n"

    mensaje = quote(mensaje)
    return f"https://wa.me/{settings.WHATSAPP_NUMBER}?text={quote(mensaje)}"

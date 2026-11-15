import requests
from django.conf import settings


def enviar_template_whatsapp(telefono, evento, parametros):

    token = getattr(settings, "WHATSAPP_TOKEN", None)
    phone_number_id = getattr(
        settings,
        "WHATSAPP_PHONE_NUMBER_ID",
        None,
    )
    api_version = getattr(
        settings,
        "WHATSAPP_API_VERSION",
        None,
    )
    templates = getattr(
        settings,
        "WHATSAPP_TEMPLATES",
        {},
    )

    if not all([token, phone_number_id, api_version]):
        raise ValueError("La configuración de WhatsApp está incompleta.")

    template = templates.get(evento)

    if not template:
        raise ValueError(
            f"No existe una plantilla configurada para el evento {evento}."
        )

    url = f"https://graph.facebook.com/" f"{api_version}/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": telefono,
        "type": "template",
        "template": {
            "name": template,
            "language": {
                "code": getattr(
                    settings,
                    "WHATSAPP_TEMPLATE_LANGUAGE",
                    "es",
                )
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": str(valor),
                        }
                        for valor in parametros
                    ],
                }
            ],
        },
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=15,
    )

    response.raise_for_status()

    return response.json()

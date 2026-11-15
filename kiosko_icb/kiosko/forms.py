import json
from json import JSONDecodeError

from django import forms


class CheckoutForm(forms.Form):
    items = forms.CharField(required=False, strip=False, widget=forms.HiddenInput)
    acepta_notificaciones_whatsapp = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    cliente = forms.CharField(
        required=False,
        strip=False,
        widget=forms.TextInput(attrs={
            "class": "text-field form-control",
            "id": "customer-name",
            "maxlength": "100",
            "autocomplete": "name",
            "placeholder": "Tu nombre",
        }),
    )
    telefono_cliente = forms.CharField(
        required=False,
        strip=False,
        widget=forms.TextInput(attrs={
            "type": "tel",
            "class": "text-field form-control",
            "id": "customer-phone",
            "maxlength": "20",
            "autocomplete": "tel",
            "inputmode": "tel",
            "placeholder": "+56 9 1234 5678",
        }),
    )
    medio_pago_id = forms.CharField(
        required=False,
        strip=False,
        widget=forms.RadioSelect(attrs={"class": "form-check-input", "required": True}),
    )

    def __init__(self, *args, payment_methods=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["medio_pago_id"].widget.choices = [
            (method.pk, method.nombre) for method in payment_methods
        ]

    def clean_items(self):
        try:
            return json.loads(self.cleaned_data["items"])
        except JSONDecodeError as error:
            raise forms.ValidationError(
                "El detalle del pedido no tiene un formato válido."
            ) from error

    def clean_acepta_notificaciones_whatsapp(self):
        consentimiento = self.data.get("acepta_notificaciones_whatsapp")
        if consentimiento not in (None, "on"):
            raise forms.ValidationError("La autorización de WhatsApp no es válida.")
        return consentimiento == "on"

    def clean_medio_pago_id(self):
        try:
            return int(self.cleaned_data["medio_pago_id"])
        except (TypeError, ValueError):
            return None

from decimal import Decimal, ROUND_HALF_UP

from django import template

register = template.Library()


@register.filter
def clp(value):
    amount = int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"${amount:,}".replace(",", ".")

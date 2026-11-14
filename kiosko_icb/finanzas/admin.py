from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import MedioPago, MovimientoFinanciero


@admin.register(MedioPago)
class MedioPagoAdmin(ModelAdmin):

    list_display = ("nombre", "tipo")
    list_display_links = ("nombre",)
    list_filter = ("tipo",)
    search_fields = ("nombre",)


@admin.register(MovimientoFinanciero)
class MovimientoFinancieroAdmin(ModelAdmin):

    list_display = (
        "fecha",
        "pedido",
        "tipo",
        "medio_pago",
        "monto",
    )

    list_display_links = ("pedido",)

    list_filter = (
        "tipo",
        "medio_pago",
        "fecha",
    )

    search_fields = (
        "pedido__numero_pedido",
        "descripcion",
    )

    list_per_page = 20

    # Los movimientos se generan desde el proceso de pago.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

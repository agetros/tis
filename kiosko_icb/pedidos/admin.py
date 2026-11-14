from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import DetallePedido, Pedido


@admin.register(Pedido)
class PedidoAdmin(ModelAdmin):
    list_display = (
        "numero_pedido",
        "fecha",
        "cliente",
        "origen",
        "estado",
        "estado_pago",
        "total",
    )
    list_display_links = ("numero_pedido",)
    list_filter = (
        "origen",
        "estado",
        "estado_pago",
        "medio_pago",
    )
    search_fields = (
        "numero_pedido",
        "cliente",
    )
    list_per_page = 15


@admin.register(DetallePedido)
class DetallePedidoAdmin(ModelAdmin):
    list_display = (
        "pedido",
        "producto",
        "cantidad",
        "precio_unitario",
    )
    list_display_links = ("pedido",)
    list_per_page = 20

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from unfold.admin import ModelAdmin

from .models import (
    DetallePedido,
    NotificacionWhatsApp,
    Pedido,
)
from .services import (
    completar_pedido,
    marcar_como_listo,
)


@admin.action(description="Marcar como listo para retirar")
def accion_marcar_como_listo(modeladmin, request, queryset):

    exitosos = 0

    for pedido in queryset:

        try:
            marcar_como_listo(pedido.pk)
            exitosos += 1

        except ValidationError as error:
            modeladmin.message_user(
                request,
                f"{pedido}: {error}",
                level=messages.WARNING,
            )

    if exitosos:
        modeladmin.message_user(
            request,
            f"{exitosos} pedido(s) marcado(s) como listo(s).",
            level=messages.SUCCESS,
        )


@admin.action(description="Completar pedidos listos")
def accion_completar_pedido(modeladmin, request, queryset):

    exitosos = 0

    for pedido in queryset:

        try:
            completar_pedido(pedido.pk)
            exitosos += 1

        except ValidationError as error:
            modeladmin.message_user(
                request,
                f"{pedido}: {error}",
                level=messages.WARNING,
            )

    if exitosos:
        modeladmin.message_user(
            request,
            f"{exitosos} pedido(s) completado(s).",
            level=messages.SUCCESS,
        )


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
        "estado",
        "estado_pago",
        "origen",
        "fecha",
    )

    search_fields = (
        "numero_pedido",
        "cliente",
        "telefono_cliente",
    )

    list_per_page = 10

    actions = (
        accion_marcar_como_listo,
        accion_completar_pedido,
    )


@admin.register(DetallePedido)
class DetallePedidoAdmin(ModelAdmin):

    list_display = (
        "pedido",
        "producto",
        "cantidad",
        "precio_unitario",
    )

    list_display_links = ("pedido",)

    search_fields = (
        "pedido__numero_pedido",
        "producto__nombre",
    )

    list_per_page = 10


@admin.register(NotificacionWhatsApp)
class NotificacionWhatsAppAdmin(ModelAdmin):

    list_display = (
        "pedido",
        "evento",
        "telefono",
        "estado",
        "creado_en",
    )

    list_filter = (
        "evento",
        "estado",
        "creado_en",
    )

    search_fields = (
        "pedido__numero_pedido",
        "telefono",
        "identificador_whatsapp",
    )

    list_per_page = 20

    readonly_fields = (
        "pedido",
        "evento",
        "telefono",
        "estado",
        "identificador_whatsapp",
        "error",
        "creado_en",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

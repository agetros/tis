from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.template.response import TemplateResponse
from unfold.admin import ModelAdmin

from .models import DetallePedido, Pedido
from .services import (
    anular_pedido,
    completar_pedido,
    marcar_como_listo,
    marcar_como_pagado,
    tomar_pedido,
)


@admin.action(permissions=["view"], description="Tomar pedidos disponibles")
def accion_tomar_pedido(modeladmin, request, queryset):
    exitosos = 0
    for pedido in queryset:
        try:
            tomar_pedido(pedido.pk, request.user)
            exitosos += 1
        except ValidationError as error:
            modeladmin.message_user(request, f"{pedido}: {error}", level=messages.WARNING)
    if exitosos:
        modeladmin.message_user(
            request, f"{exitosos} pedido(s) tomado(s).", level=messages.SUCCESS
        )


class AsignacionPedidoFilter(admin.SimpleListFilter):
    title = "asignación"
    parameter_name = "asignacion"

    def lookups(self, request, modeladmin):
        return (
            ("disponibles", "Disponibles"),
            ("mios", "Asignados a mí"),
            ("otros", "Asignados a otros"),
        )

    def queryset(self, request, queryset):
        if self.value() == "disponibles":
            return queryset.filter(estado="P", responsable__isnull=True)
        if self.value() == "mios":
            return queryset.filter(responsable=request.user)
        if self.value() == "otros":
            return queryset.filter(responsable__isnull=False).exclude(
                responsable=request.user
            )
        return queryset


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


@admin.action(description="Anular pedidos")
def accion_anular_pedido(modeladmin, request, queryset):
    if request.POST.get("confirmar_anulacion") != "si":
        return TemplateResponse(
            request,
            "admin/pedidos/confirmar_anulacion.html",
            {
                **modeladmin.admin_site.each_context(request),
                "title": "Confirmar anulación de pedidos",
                "queryset": queryset,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            },
        )
    exitosos = 0
    for pedido in queryset:
        try:
            anular_pedido(
                pedido.pk, reembolso_confirmado=request.POST.get("reembolso_confirmado") == "on"
            )
            exitosos += 1
        except ValidationError as error:
            modeladmin.message_user(request, f"{pedido}: {error}", level=messages.WARNING)
    if exitosos:
        modeladmin.message_user(
            request, f"{exitosos} pedido(s) anulado(s).", level=messages.SUCCESS
        )


@admin.action(description="Confirmar pago de pedidos")
def accion_confirmar_pago(modeladmin, request, queryset):
    if request.POST.get("confirmar_pago") != "si":
        return TemplateResponse(
            request,
            "admin/pedidos/confirmar_pago.html",
            {
                **modeladmin.admin_site.each_context(request),
                "title": "Confirmar pago de pedidos",
                "queryset": queryset.select_related("medio_pago"),
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            },
        )
    exitosos = 0
    for pedido in queryset:
        try:
            marcar_como_pagado(pedido.pk, pedido.medio_pago_id)
            exitosos += 1
        except ValidationError as error:
            modeladmin.message_user(request, f"{pedido}: {error}", level=messages.WARNING)
    if exitosos:
        modeladmin.message_user(
            request, f"{exitosos} pago(s) confirmado(s).", level=messages.SUCCESS
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
        "responsable",
        "asignado_en",
        "total",
    )

    list_display_links = ("numero_pedido",)

    list_filter = (
        AsignacionPedidoFilter,
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
    list_select_related = ("responsable",)
    readonly_fields = ("estado", "estado_pago", "responsable", "asignado_en")

    actions = (
        accion_tomar_pedido,
        accion_marcar_como_listo,
        accion_completar_pedido,
        accion_anular_pedido,
        accion_confirmar_pago,
    )

    def has_add_permission(self, request):
        return False


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

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.template.response import TemplateResponse
from django.utils import timezone
from unfold.admin import ModelAdmin

from .models import (
    DetallePedido,
    EncargadoWhatsApp,
    IntentoNotificacion,
    NotificacionSalida,
    NotificacionWhatsApp,
    Pedido,
)
from .services import (
    anular_pedido,
    completar_pedido,
    marcar_como_listo,
    marcar_como_pagado,
)
from .notificaciones import normalizar_telefono


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
    readonly_fields = ("estado", "estado_pago")

    actions = (
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


class EncargadoWhatsAppForm(forms.ModelForm):
    class Meta:
        model = EncargadoWhatsApp
        fields = "__all__"

    def clean_telefono(self):
        try:
            return normalizar_telefono(self.cleaned_data["telefono"])
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error


@admin.register(EncargadoWhatsApp)
class EncargadoWhatsAppAdmin(ModelAdmin):
    form = EncargadoWhatsAppForm
    list_display = ("nombre", "telefono", "autorizado")
    list_filter = ("autorizado",)
    search_fields = ("nombre", "telefono")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NotificacionSalida)
class NotificacionSalidaAdmin(ModelAdmin):
    list_display = (
        "pedido", "evento", "tipo_destinatario", "telefono", "estado",
        "estado_proveedor", "creado_en", "ultimo_intento", "intentos",
    )
    list_filter = ("estado", "estado_proveedor", "evento", "tipo_destinatario", "creado_en")
    search_fields = ("pedido__numero_pedido", "telefono", "identificador_proveedor")
    readonly_fields = tuple(field.name for field in NotificacionSalida._meta.fields)
    list_per_page = 20
    actions = ("reintentar_rechazadas",)

    @admin.action(permissions=["reintentar"], description="Reintentar fallos sin SID")
    def reintentar_rechazadas(self, request, queryset):
        actualizadas = queryset.filter(
            estado=NotificacionSalida.Procesamiento.FALLIDO,
            identificador_proveedor__isnull=True,
        ).update(
            estado=NotificacionSalida.Procesamiento.PENDIENTE,
            proximo_intento=None,
            actualizado_en=timezone.now(),
        )
        self.message_user(
            request, f"{actualizadas} notificación(es) puestas en cola.", level=messages.SUCCESS
        )

    def has_reintentar_permission(self, request):
        return request.user.has_perm("pedidos.change_notificacionsalida")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IntentoNotificacion)
class IntentoNotificacionAdmin(ModelAdmin):
    list_display = ("notificacion", "numero", "iniciado_en", "finalizado_en", "resultado")
    list_filter = ("resultado", "iniciado_en")
    readonly_fields = tuple(field.name for field in IntentoNotificacion._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

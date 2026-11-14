from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import Categoria, Producto


@admin.register(Producto)
class ProductoAdmin(ModelAdmin):
    list_display = (
        "mostrar_imagen",
        "nombre",
        "descripcion",
        "categoria",
    )
    list_display_links = ("nombre",)
    list_filter = ("categoria",)
    list_per_page = 15
    search_fields = ("nombre", "descripcion")

    @admin.display(description="Imagen")
    def mostrar_imagen(self, obj):
        if obj.imagen:
            return format_html(
                '<img src="{}" width="60" height="60" '
                'style="object-fit: cover; border-radius: 8px;" />',
                obj.imagen.url,
            )

        return "Sin imagen"


@admin.register(Categoria)
class CategoriaAdmin(ModelAdmin):
    list_display = (
        "mostrar_imagen",
        "nombre",
        "descripcion",
    )
    list_per_page = 10
    list_display_links = ("nombre",)

    @admin.display(description="Imagen")
    def mostrar_imagen(self, obj):
        if obj.imagen:
            return format_html(
                '<img src="{}" width="60" height="60" '
                'style="object-fit: cover; border-radius: 8px;" />',
                obj.imagen.url,
            )

        return "Sin imagen"

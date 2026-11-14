from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import MedioPago


# Register your models here.
@admin.register(MedioPago)
class MedioPagoAdmin(ModelAdmin):
    list_display = ("nombre",)
    list_display_links = ("nombre",)
    list_per_page = 10

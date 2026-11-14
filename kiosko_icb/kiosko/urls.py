from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('pedido/crear/', views.crear_pedido, name='crear_pedido'),
    path('pedido/<int:pedido_id>/', views.confirmacion_pedido, name='pedido_confirmacion'),
]

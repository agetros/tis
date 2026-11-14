import json
from decimal import Decimal, ROUND_HALF_UP
from json import JSONDecodeError

from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from finanzas.models import MedioPago
from pedidos.models import Pedido
from pedidos.services import crear_pedido_autoservicio
from productos.models import Categoria, Producto


def _catalog_context():
    categories = list(Categoria.objects.order_by("id"))
    products = list(Producto.objects.select_related("categoria").order_by("id"))
    products_by_category = {category.pk: [] for category in categories}
    for product in products:
        products_by_category.setdefault(product.categoria_id, []).append(product)
    for category in categories:
        category.productos_catalogo = products_by_category.get(category.pk, [])

    available_products = [product for product in products if product.stock > 0]
    featured_products = []
    featured_categories = set()
    for product in available_products:
        if product.categoria_id in featured_categories:
            continue
        featured_products.append(product)
        featured_categories.add(product.categoria_id)
        if len(featured_products) == 4:
            break

    product_data = [
        {
            "id": product.pk,
            "name": product.nombre,
            "description": product.descripcion,
            "image": (
                product.imagen.url
                if product.imagen
                else product.categoria.imagen.url
                if product.categoria.imagen
                else ""
            ),
            "price": int(product.precio.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
            "stock": product.stock,
            "category": product.categoria.nombre,
        }
        for product in products
    ]
    hero_product = next(
        (
            product for product in available_products
            if "sándwich" in product.categoria.nombre.lower()
            or "sandwich" in product.categoria.nombre.lower()
        ),
        available_products[0] if available_products else None,
    )
    return {
        "categories": categories,
        "featured_products": featured_products,
        "hero_product": hero_product,
        "payment_methods": MedioPago.objects.order_by("nombre"),
        "product_data": product_data,
    }


def index(request):
    return render(request, "kiosko/index.html", _catalog_context())


@require_POST
def crear_pedido(request):
    try:
        items = json.loads(request.POST.get("items", ""))
    except JSONDecodeError:
        return JsonResponse(
            {"error": "El detalle del pedido no tiene un formato válido."},
            status=400,
        )

    try:
        medio_pago_id = int(request.POST.get("medio_pago_id", ""))
    except (TypeError, ValueError):
        medio_pago_id = None

    try:
        pedido = crear_pedido_autoservicio(
            items=items,
            medio_pago_id=medio_pago_id,
            cliente=request.POST.get("cliente", ""),
        )
    except ValidationError as error:
        return JsonResponse({"error": error.messages[0]}, status=400)

    pedidos_autorizados = request.session.get("pedidos_kiosko", [])
    pedidos_autorizados.append(pedido.pk)
    request.session["pedidos_kiosko"] = pedidos_autorizados[-50:]
    return JsonResponse(
        {"redirect_url": reverse("pedido_confirmacion", args=[pedido.pk])}
    )


def confirmacion_pedido(request, pedido_id):
    if pedido_id not in request.session.get("pedidos_kiosko", []):
        raise Http404

    pedido = get_object_or_404(
        Pedido.objects.select_related("medio_pago").prefetch_related(
            "detalle__producto"
        ),
        pk=pedido_id,
    )
    detalles = list(pedido.detalle.all())
    for detalle in detalles:
        detalle.subtotal = detalle.cantidad * detalle.precio_unitario
    return render(
        request,
        "kiosko/confirmacion.html",
        {"pedido": pedido, "detalles": detalles},
    )

(() => {
    const productDataElement = document.getElementById("product-data");
    const products = new Map(JSON.parse(productDataElement?.textContent || "[]").map((product) => [String(product.id), product]));
    const storageKey = "kiosko-icb-cart-v1";
    const formatter = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
    const cart = new Map();
    const productDialog = document.getElementById("product-dialog");
    const cartDialog = document.getElementById("cart-dialog");
    const cartView = document.getElementById("cart-view");
    const checkoutView = document.getElementById("checkout-view");
    const checkoutForm = document.getElementById("checkout-form");
    const checkoutError = document.getElementById("checkout-error");
    const toastDialog = document.getElementById("toast-dialog");
    const toastMessage = document.getElementById("toast-message");
    let activeProduct = null;
    let detailQuantity = 1;
    let toastTimer;

    function formatPrice(amount) {
        return `$${formatter.format(amount)}`;
    }

    function showToast(message) {
        toastMessage.textContent = message;
        if (!toastDialog.open) toastDialog.show();
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toastDialog.close(), 2400);
    }

    function saveCart() {
        try {
            localStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(cart)));
        } catch {
            showToast("No pudimos guardar tu pedido en este dispositivo.");
        }
    }

    function loadCart() {
        let savedCart;
        try {
            savedCart = localStorage.getItem(storageKey);
        } catch {
            showToast("No pudimos recuperar tu pedido guardado.");
            return;
        }
        if (!savedCart) return;

        try {
            const saved = JSON.parse(savedCart);
            if (!saved || typeof saved !== "object" || Array.isArray(saved)) throw new Error("Formato de carrito inválido.");
            for (const [id, quantity] of Object.entries(saved)) {
                const product = products.get(id);
                if (product && Number.isInteger(quantity) && quantity > 0 && product.stock > 0) {
                    cart.set(id, Math.min(quantity, product.stock));
                }
            }
        } catch {
            showToast("No pudimos recuperar tu pedido guardado.");
            try {
                localStorage.removeItem(storageKey);
            } catch {
                showToast("No pudimos borrar el pedido guardado inválido.");
            }
        }
    }

    function createImage(source, alt, className) {
        const wrapper = document.createElement("div");
        wrapper.className = className;
        if (source) {
            const image = document.createElement("img");
            image.src = source;
            image.alt = alt;
            image.loading = "lazy";
            wrapper.append(image);
        } else {
            const fallback = document.createElement("span");
            fallback.className = "image-fallback";
            fallback.textContent = "ICB";
            wrapper.append(fallback);
        }
        return wrapper;
    }

    function totalQuantity() {
        return [...cart.values()].reduce((total, quantity) => total + quantity, 0);
    }

    function totalPrice() {
        return [...cart.entries()].reduce((total, [id, quantity]) => {
            const product = products.get(id);
            return total + (product ? product.price * quantity : 0);
        }, 0);
    }

    function renderCart() {
        const quantity = totalQuantity();
        const total = totalPrice();
        const cartItems = document.getElementById("cart-items");
        const isEmpty = quantity === 0;
        document.getElementById("header-cart-count").textContent = String(quantity);
        document.getElementById("mobile-cart-count").textContent = String(quantity);
        document.getElementById("mobile-cart-total").textContent = formatPrice(total);
        document.getElementById("mobile-cart-bar").hidden = isEmpty;
        document.getElementById("cart-title-count").textContent = quantity ? `· ${quantity} ${quantity === 1 ? "producto" : "productos"}` : "";
        document.getElementById("cart-empty").hidden = !isEmpty;
        document.getElementById("cart-summary").hidden = isEmpty;
        cartItems.replaceChildren();

        for (const [id, itemQuantity] of cart) {
            const product = products.get(id);
            if (!product) continue;

            const item = document.createElement("article");
            item.className = "cart-item";
            item.append(createImage(product.image, product.name, "cart-item-photo"));

            const copy = document.createElement("div");
            copy.className = "cart-item-copy";
            const name = document.createElement("strong");
            name.textContent = product.name;
            const price = document.createElement("span");
            price.textContent = `${formatPrice(product.price)} c/u`;
            const controls = document.createElement("div");
            controls.className = "cart-line-controls";
            controls.append(
                actionButton("−", "decrease", id, `Quitar una unidad de ${product.name}`),
                Object.assign(document.createElement("span"), { textContent: String(itemQuantity) }),
                actionButton("+", "increase", id, `Agregar una unidad de ${product.name}`)
            );
            copy.append(name, price, controls);

            const end = document.createElement("div");
            end.className = "cart-item-end";
            const lineTotal = document.createElement("strong");
            lineTotal.textContent = formatPrice(product.price * itemQuantity);
            const remove = document.createElement("button");
            remove.className = "remove-item";
            remove.type = "button";
            remove.dataset.cartAction = "remove";
            remove.dataset.productId = id;
            remove.textContent = "Quitar";
            end.append(lineTotal, remove);
            item.append(copy, end);
            cartItems.append(item);
        }

        document.getElementById("cart-subtotal").textContent = formatPrice(total);
        document.getElementById("cart-total").textContent = formatPrice(total);
        document.getElementById("checkout-total").textContent = formatPrice(total);
        renderCheckoutReview();
    }

    function actionButton(label, action, id, accessibleLabel) {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.cartAction = action;
        button.dataset.productId = id;
        button.setAttribute("aria-label", accessibleLabel);
        button.textContent = label;
        return button;
    }

    function renderCheckoutReview() {
        const review = document.getElementById("checkout-review");
        review.replaceChildren();
        for (const [id, quantity] of cart) {
            const product = products.get(id);
            if (!product) continue;
            const line = document.createElement("div");
            line.className = "checkout-review-line";
            const description = document.createElement("span");
            description.textContent = `${quantity} × ${product.name}`;
            const amount = document.createElement("span");
            amount.textContent = formatPrice(quantity * product.price);
            line.append(description, amount);
            review.append(line);
        }
    }

    function changeQuantity(id, amount) {
        const product = products.get(id);
        if (!product) return false;
        const nextQuantity = (cart.get(id) || 0) + amount;
        if (nextQuantity > product.stock) {
            showToast(`Solo quedan ${product.stock} unidades de ${product.name}.`);
            return false;
        }
        if (nextQuantity <= 0) cart.delete(id);
        else cart.set(id, nextQuantity);
        saveCart();
        renderCart();
        return true;
    }

    function showProduct(id) {
        const product = products.get(String(id));
        if (!product) return;
        activeProduct = product;
        detailQuantity = 1;
        document.getElementById("detail-name").textContent = product.name;
        document.getElementById("detail-category").textContent = product.category;
        document.getElementById("detail-description").textContent = product.description || "Una opción rica para seguir con tu día.";
        document.getElementById("detail-price").textContent = formatPrice(product.price);
        document.getElementById("detail-quantity").textContent = String(detailQuantity);
        document.getElementById("detail-photo").replaceChildren(createImage(product.image, product.name, "detail-image"));
        const remaining = Math.max(0, product.stock - (cart.get(String(product.id)) || 0));
        const soldOut = remaining < 1;
        const stockLabel = document.getElementById("detail-stock");
        stockLabel.textContent = soldOut
            ? product.stock < 1 ? "Agotado por ahora" : "Ya agregaste todas las unidades disponibles"
            : `Disponible · ${remaining} en stock`;
        stockLabel.classList.toggle("is-sold-out", soldOut);
        document.getElementById("detail-minus").disabled = true;
        document.getElementById("detail-plus").disabled = soldOut || remaining < 2;
        document.getElementById("detail-add").disabled = soldOut;
        document.getElementById("detail-add").textContent = soldOut ? "Agotado" : "Agregar al pedido";
        productDialog.showModal();
    }

    function openCart() {
        cartView.hidden = false;
        checkoutView.hidden = true;
        renderCart();
        cartDialog.showModal();
    }

    function filterProducts(categoryId) {
        for (const section of document.querySelectorAll("[data-category-section]")) {
            section.hidden = categoryId !== "all" && section.dataset.categorySection !== categoryId;
        }
        for (const pill of document.querySelectorAll("[data-category-filter]")) {
            pill.classList.toggle("is-active", pill.dataset.categoryFilter === categoryId);
        }
    }

    loadCart();
    renderCart();

    document.addEventListener("click", (event) => {
        const target = event.target instanceof Element ? event.target : null;
        if (!target) return;

        const productButton = target.closest(".js-product-detail");
        if (productButton) {
            showProduct(productButton.dataset.productId);
            return;
        }

        const addButton = target.closest(".js-add-product");
        if (addButton) {
            if (changeQuantity(addButton.dataset.productId, 1)) showToast("Agregado a tu pedido.");
            return;
        }

        if (target.closest(".js-open-cart")) {
            openCart();
            return;
        }

        const closeButton = target.closest("[data-close-dialog]");
        if (closeButton) {
            closeButton.closest("dialog")?.close();
            return;
        }

        const cartAction = target.closest("[data-cart-action]");
        if (cartAction) {
            const id = cartAction.dataset.productId;
            if (cartAction.dataset.cartAction === "remove") {
                cart.delete(id);
                saveCart();
                renderCart();
            } else {
                changeQuantity(id, cartAction.dataset.cartAction === "increase" ? 1 : -1);
            }
            return;
        }

        const categoryPill = target.closest("[data-category-filter]");
        if (categoryPill) {
            document.getElementById("product-search").value = "";
            document.querySelectorAll("[data-product-card]").forEach((card) => { card.hidden = false; });
            filterProducts(categoryPill.dataset.categoryFilter);
            const section = document.querySelector(`[data-category-section="${categoryPill.dataset.categoryFilter}"]`);
            if (section) section.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    });

    document.getElementById("detail-minus").addEventListener("click", () => {
        detailQuantity = Math.max(1, detailQuantity - 1);
        document.getElementById("detail-quantity").textContent = String(detailQuantity);
        document.getElementById("detail-minus").disabled = detailQuantity === 1;
        const remaining = activeProduct.stock - (cart.get(String(activeProduct.id)) || 0);
        document.getElementById("detail-plus").disabled = detailQuantity >= remaining;
    });

    document.getElementById("detail-plus").addEventListener("click", () => {
        const remaining = activeProduct
            ? activeProduct.stock - (cart.get(String(activeProduct.id)) || 0)
            : 0;
        if (!activeProduct || detailQuantity >= remaining) return;
        detailQuantity += 1;
        document.getElementById("detail-quantity").textContent = String(detailQuantity);
        document.getElementById("detail-minus").disabled = false;
        document.getElementById("detail-plus").disabled = detailQuantity >= remaining;
    });

    document.getElementById("detail-add").addEventListener("click", () => {
        if (!activeProduct || activeProduct.stock < 1) return;
        if (!changeQuantity(String(activeProduct.id), detailQuantity)) return;
        productDialog.close();
        showToast("Agregado a tu pedido.");
    });

    document.getElementById("start-checkout").addEventListener("click", () => {
        if (!totalQuantity()) return;
        renderCheckoutReview();
        checkoutError.hidden = true;
        cartView.hidden = true;
        checkoutView.hidden = false;
        checkoutView.scrollTop = 0;
    });

    document.getElementById("back-to-cart").addEventListener("click", () => {
        checkoutView.hidden = true;
        cartView.hidden = false;
    });

    document.getElementById("product-search").addEventListener("input", (event) => {
        const query = event.target.value.trim().toLocaleLowerCase("es-CL");
        let visibleCount = 0;
        for (const card of document.querySelectorAll("[data-product-card]")) {
            const matches = !query || `${card.dataset.name} ${card.dataset.description}`.toLocaleLowerCase("es-CL").includes(query);
            card.hidden = !matches;
            if (matches) visibleCount += 1;
        }
        for (const section of document.querySelectorAll("[data-category-section]")) {
            section.hidden = !section.querySelector("[data-product-card]:not([hidden])");
        }
        filterProducts("all");
        if (query) {
            for (const section of document.querySelectorAll("[data-category-section]")) {
                section.hidden = !section.querySelector("[data-product-card]:not([hidden])");
            }
        }
        const noResults = document.getElementById("no-search-results");
        if (noResults) noResults.remove();
        if (query && visibleCount === 0) {
            const message = document.createElement("p");
            message.className = "empty-catalog";
            message.id = "no-search-results";
            message.textContent = "No encontramos productos con ese nombre. Prueba otra búsqueda.";
            document.querySelector(".product-list").append(message);
        }
    });

    for (const dialog of [productDialog, cartDialog]) {
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) dialog.close();
        });
    }
    cartDialog.addEventListener("close", () => {
        cartView.hidden = false;
        checkoutView.hidden = true;
    });

    checkoutForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!cart.size) {
            checkoutError.textContent = "Agrega al menos un producto antes de confirmar.";
            checkoutError.hidden = false;
            return;
        }
        const selectedPayment = checkoutForm.querySelector('input[name="medio_pago_id"]:checked');
        if (!selectedPayment) {
            checkoutError.textContent = "Elige un medio de pago para continuar.";
            checkoutError.hidden = false;
            return;
        }

        const submitButton = checkoutForm.querySelector('[type="submit"]');
        submitButton.disabled = true;
        submitButton.textContent = "Registrando tu pedido…";
        checkoutError.hidden = true;
        const formData = new FormData(checkoutForm);
        formData.set("items", JSON.stringify([...cart.entries()].map(([productId, quantity]) => ({
            product_id: Number(productId),
            quantity
        }))));

        let result;
        try {
            const response = await fetch(checkoutForm.action, {
                method: "POST",
                body: formData,
                headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" }
            });
            result = await response.json();
            if (!response.ok) throw new Error(result.error || "No pudimos registrar tu pedido.");
            if (!result.redirect_url) throw new Error("No recibimos la confirmación del pedido.");
        } catch (error) {
            checkoutError.textContent = error instanceof Error ? error.message : "Ocurrió un error inesperado. Inténtalo nuevamente.";
            checkoutError.hidden = false;
            submitButton.disabled = false;
            submitButton.innerHTML = 'Confirmar pedido <span aria-hidden="true">→</span>';
            return;
        }

        try {
            localStorage.removeItem(storageKey);
        } catch {
            showToast("Tu pedido quedó registrado, pero no pudimos limpiar el carrito guardado.");
        }
        window.location.assign(result.redirect_url);
    });
})();

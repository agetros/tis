import sqlite3
import threading
import time
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import ValidationError
from django.db import OperationalError, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from finanzas.models import MedioPago
from productos.models import Categoria, Producto

from .models import Pedido
from .services import (
    crear_pedido_autoservicio,
    marcar_como_pagado,
    tomar_pedido,
)


class PedidoFixture:
    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Bebidas")
        self.producto = Producto.objects.create(
            nombre="Agua", precio=Decimal("1000"), categoria=self.categoria, stock=10,
        )
        self.medio = MedioPago.objects.create(nombre="Efectivo", tipo="EF")

    def crear(self):
        return crear_pedido_autoservicio(
            [{"product_id": self.producto.pk, "quantity": 2}],
            self.medio.pk,
            cliente="Ana",
            telefono_cliente="9 2222 2222",
        )


class PedidoAdminActionsTests(PedidoFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser(
            username="admin", password="admin-test"
        ))

    def test_accion_anula_por_el_servicio(self):
        pedido = self.crear()
        url = reverse("admin:pedidos_pedido_changelist")
        seleccion = {"action": "accion_anular_pedido", "_selected_action": [pedido.pk]}
        response = self.client.post(url, seleccion)
        self.assertContains(response, "Confirmar anulación")
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, "P")

        response = self.client.post(url, {**seleccion, "confirmar_anulacion": "si"})

        self.assertEqual(response.status_code, 302)
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, "A")

    def test_accion_confirma_pago_por_el_servicio(self):
        pedido = self.crear()
        url = reverse("admin:pedidos_pedido_changelist")
        seleccion = {"action": "accion_confirmar_pago", "_selected_action": [pedido.pk]}
        self.assertContains(self.client.post(url, seleccion), "Confirmar pago de pedidos")

        response = self.client.post(url, {**seleccion, "confirmar_pago": "si"})

        self.assertEqual(response.status_code, 302)
        pedido.refresh_from_db()
        self.producto.refresh_from_db()
        self.assertEqual(pedido.estado_pago, "G")
        self.assertEqual(self.producto.stock, 8)
        self.assertTrue(pedido.movimientos.filter(tipo="I").exists())


class TomaPedidoTests(PedidoFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.usuario = get_user_model().objects.create_superuser(
            username="responsable", password=None, first_name="Ana", last_name="Pérez",
        )
        self.otro = get_user_model().objects.create_superuser(
            username="otro", password=None,
        )
        self.pedido = self.crear()

    def test_toma_registra_responsable_fecha_y_estado(self):
        resultado = tomar_pedido(self.pedido.pk, self.usuario)
        self.pedido.refresh_from_db()

        self.assertEqual(resultado.pk, self.pedido.pk)
        self.assertEqual(self.pedido.responsable, self.usuario)
        self.assertEqual(self.pedido.estado, "E")
        self.assertIsNotNone(self.pedido.asignado_en)
        self.assertIsNone(self.pedido.creado_por)

    def test_toma_reutiliza_acceso_admin_existente(self):
        for codename in ("view_pedido", "change_pedido"):
            with self.subTest(codename=codename):
                usuario = get_user_model().objects.create_user(
                    username=codename, is_staff=True,
                )
                usuario.user_permissions.add(Permission.objects.get(
                    content_type__app_label="pedidos", codename=codename,
                ))
                pedido = self.crear()

                tomar_pedido(pedido.pk, usuario)
                pedido.refresh_from_db()

                self.assertEqual(pedido.responsable, usuario)

    def test_usuarios_sin_acceso_admin_no_pueden_tomar(self):
        sin_acceso = get_user_model().objects.create_user(username="sin_acceso", is_staff=True)
        inactivo = get_user_model().objects.create_superuser(
            username="inactivo", password=None, is_active=False,
        )
        no_staff = get_user_model().objects.create_user(username="no_staff")
        for usuario in (AnonymousUser(), sin_acceso, inactivo, no_staff):
            with self.subTest(usuario=str(usuario)), self.assertRaisesMessage(
                ValidationError, "No tienes acceso",
            ):
                tomar_pedido(self.pedido.pk, usuario)

        self.pedido.refresh_from_db()
        self.assertIsNone(self.pedido.responsable)
        self.assertEqual(self.pedido.estado, "P")

    def test_pedido_inexistente_e_incompatible_devuelven_error_controlado(self):
        with self.assertRaisesMessage(ValidationError, "El pedido no existe"):
            tomar_pedido(self.pedido.pk + 1000, self.usuario)
        for estado in ("E", "L", "C", "A"):
            with self.subTest(estado=estado):
                Pedido.objects.filter(pk=self.pedido.pk).update(estado=estado)
                with self.assertRaisesMessage(ValidationError, "dejó de estar disponible"):
                    tomar_pedido(self.pedido.pk, self.usuario)

        self.pedido.refresh_from_db()
        self.assertIsNone(self.pedido.responsable)

    def test_toma_no_depende_del_pago(self):
        marcar_como_pagado(self.pedido.pk, self.medio.pk)

        tomar_pedido(self.pedido.pk, self.usuario)

        self.pedido.refresh_from_db()
        self.assertEqual((self.pedido.estado, self.pedido.estado_pago), ("E", "G"))

    def test_segunda_toma_no_sobrescribe_la_asignacion(self):
        tomar_pedido(self.pedido.pk, self.usuario)
        self.pedido.refresh_from_db()
        fecha = self.pedido.asignado_en

        with self.assertRaisesMessage(ValidationError, "Otro encargado ya tomó"):
            tomar_pedido(self.pedido.pk, self.otro)

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.responsable, self.usuario)
        self.assertEqual(self.pedido.asignado_en, fecha)
        Pedido.objects.filter(pk=self.pedido.pk).update(estado="P")
        with self.assertRaisesMessage(ValidationError, "Otro encargado ya tomó"):
            tomar_pedido(self.pedido.pk, self.otro)

    def test_bloqueo_sqlite_es_controlado_sin_ocultar_otros_errores(self):
        for codigo in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            causa = sqlite3.OperationalError("database is locked")
            causa.sqlite_errorcode = codigo
            error = OperationalError("database is locked")
            error.__cause__ = causa
            with self.subTest(codigo=codigo), patch(
                "pedidos.services.Pedido.objects.filter"
            ) as consulta, patch("pedidos.services.connection.vendor", "sqlite"):
                consulta.return_value.update.side_effect = error
                with self.assertLogs("pedidos.services", level="WARNING"):
                    with self.assertRaisesMessage(ValidationError, "base de datos está ocupada"):
                        tomar_pedido(self.pedido.pk, self.usuario)

        with patch("pedidos.services.Pedido.objects.filter") as consulta:
            consulta.return_value.update.side_effect = OperationalError("no such column")
            with self.assertRaisesMessage(OperationalError, "no such column"):
                tomar_pedido(self.pedido.pk, self.usuario)

        self.pedido.refresh_from_db()
        self.assertIsNone(self.pedido.responsable)

    def test_accion_admin_y_filtros_de_asignacion(self):
        usuario = get_user_model().objects.create_user(username="consulta", is_staff=True)
        usuario.user_permissions.add(Permission.objects.get(
            content_type__app_label="pedidos", codename="view_pedido",
        ))
        self.client.force_login(usuario)
        otro_pedido = self.crear()
        tomar_pedido(otro_pedido.pk, self.otro)
        disponible = self.crear()
        url = reverse("admin:pedidos_pedido_changelist")

        self.assertContains(self.client.get(url), "Tomar pedidos disponibles")
        seleccion = {"action": "accion_tomar_pedido", "_selected_action": [self.pedido.pk]}
        self.assertEqual(self.client.post(url, seleccion).status_code, 302)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.responsable, usuario)
        for filtro, esperado in (
            ("disponibles", disponible.pk),
            ("mios", self.pedido.pk),
            ("otros", otro_pedido.pk),
        ):
            response = self.client.get(url, {"asignacion": filtro})
            self.assertEqual(
                list(response.context["cl"].queryset.values_list("pk", flat=True)),
                [esperado],
            )
        response = self.client.post(url, seleccion, follow=True)
        self.assertContains(response, "Otro encargado ya tomó")


class TomaPedidoConcurrenciaTests(PedidoFixture, TransactionTestCase):
    def test_bloqueo_real_no_informa_exito_ni_sobrescribe_al_primer_usuario(self):
        pedido = self.crear()
        primero = get_user_model().objects.create_superuser(username="primero", password=None)
        segundo = get_user_model().objects.create_superuser(username="segundo", password=None)
        iniciada = threading.Event()
        terminar = threading.Event()
        errores = []

        def ejecutar():
            try:
                with transaction.atomic():
                    tomar_pedido(pedido.pk, primero)
                    iniciada.set()
                    if not terminar.wait(5):
                        raise RuntimeError("Tiempo de espera en prueba de bloqueo")
            except Exception as error:
                errores.append(error)
            finally:
                connections["default"].close()

        conexion = connections["default"]
        sqlite = conexion.vendor == "sqlite"
        if sqlite:
            with conexion.cursor() as cursor:
                timeout = cursor.execute("PRAGMA busy_timeout").fetchone()[0]
                cursor.execute("PRAGMA busy_timeout = 10")
        hilo = threading.Thread(target=ejecutar)
        try:
            hilo.start()
            self.assertTrue(iniciada.wait(5))
            if sqlite:
                with self.assertLogs("pedidos.services", level="WARNING"):
                    with self.assertRaisesMessage(ValidationError, "base de datos está ocupada"):
                        tomar_pedido(pedido.pk, segundo)
            else:
                empezo = threading.Event()
                resultado = []
                rival_pid = []

                def segundo_intento():
                    def observar(execute, sql, params, many, context):
                        if sql.startswith('UPDATE "pedidos_pedido"'):
                            rival_pid.append(context["connection"].connection.info.backend_pid)
                            empezo.set()
                        return execute(sql, params, many, context)

                    try:
                        with connections["default"].execute_wrapper(observar):
                            tomar_pedido(pedido.pk, segundo)
                        resultado.append("éxito inesperado")
                    except ValidationError as error:
                        resultado.append(error.messages[0])
                    except Exception as error:
                        errores.append(error)
                    finally:
                        connections["default"].close()

                rival = threading.Thread(target=segundo_intento)
                rival.start()
                try:
                    self.assertTrue(empezo.wait(5))
                    limite = time.monotonic() + 5
                    esperando = False
                    while time.monotonic() < limite:
                        with conexion.cursor() as cursor:
                            cursor.execute(
                                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                                [rival_pid[0]],
                            )
                            fila = cursor.fetchone()
                        if fila and fila[0] == "Lock":
                            esperando = True
                            break
                        time.sleep(0.01)
                    self.assertTrue(esperando, "El segundo intento no esperó el bloqueo.")
                finally:
                    terminar.set()
                    rival.join(10)
                self.assertFalse(rival.is_alive())
                self.assertEqual(len(resultado), 1)
                self.assertIn("Otro encargado ya tomó", resultado[0])
        finally:
            terminar.set()
            hilo.join(10)
            if sqlite:
                with conexion.cursor() as cursor:
                    cursor.execute(f"PRAGMA busy_timeout = {timeout}")

        self.assertFalse(hilo.is_alive())
        self.assertFalse(errores, errores)
        pedido.refresh_from_db()
        self.assertEqual(pedido.responsable, primero)
        self.assertEqual(pedido.estado, "E")

    def test_dos_intentos_concurrentes_solo_asignan_a_un_usuario(self):
        pedido = self.crear()
        usuarios = [
            get_user_model().objects.create_superuser(username=nombre, password=None)
            for nombre in ("primero", "segundo")
        ]
        barrera = threading.Barrier(2, timeout=5)
        exitosos = []
        conflictos = []
        errores = []

        def ejecutar(usuario):
            conexion = connections["default"]

            def sincronizar(execute, sql, params, many, context):
                if sql.startswith('UPDATE "pedidos_pedido"'):
                    barrera.wait()
                return execute(sql, params, many, context)

            try:
                with conexion.execute_wrapper(sincronizar):
                    resultado = tomar_pedido(pedido.pk, usuario)
                exitosos.append(resultado.responsable_id)
            except ValidationError as error:
                conflictos.append(error.messages[0])
            except Exception as error:
                errores.append(error)
            finally:
                conexion.close()

        hilos = [threading.Thread(target=ejecutar, args=(usuario,)) for usuario in usuarios]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(10)

        self.assertFalse(any(hilo.is_alive() for hilo in hilos))
        self.assertFalse(errores, errores)
        self.assertEqual(len(exitosos), 1)
        self.assertEqual(len(conflictos), 1)
        pedido.refresh_from_db()
        self.assertEqual(pedido.responsable_id, exitosos[0])
        self.assertEqual(pedido.estado, "E")
        self.assertIsNotNone(pedido.asignado_en)

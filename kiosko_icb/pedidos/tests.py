import json
import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from requests.exceptions import ReadTimeout
from twilio.base.exceptions import TwilioRestException
from twilio.http.response import Response
from twilio.request_validator import RequestValidator

from finanzas.models import MedioPago
from productos.models import Categoria, Producto

from .integrations.whatsapp import ErrorEnvio, ResultadoEnvio, TwilioWhatsApp
from .models import EncargadoWhatsApp, NotificacionSalida, NotificacionWhatsApp, Pedido
from .notificaciones import normalizar_telefono, notificar_pedido_nuevo
from .procesamiento import MAX_INTENTOS, procesar_pendientes, recuperar_abandonadas
from .services import (
    anular_pedido, crear_pedido_autoservicio, marcar_como_listo, marcar_como_pagado,
)


SID = "SM" + "1" * 32
HX = "HX" + "2" * 32
CALLBACK = "https://example.com/webhooks/twilio/status/"
CONFIG = {
    "TWILIO_ENABLED": True,
    "TWILIO_ACCOUNT_SID": "AC" + "3" * 32,
    "TWILIO_AUTH_TOKEN": "test-auth-token",
    "TWILIO_API_KEY_SID": "",
    "TWILIO_API_KEY_SECRET": "",
    "TWILIO_WHATSAPP_FROM": "whatsapp:+56912345678",
    "TWILIO_MESSAGING_SERVICE_SID": "MG" + "4" * 32,
    "TWILIO_STATUS_CALLBACK_ENABLED": True,
    "TWILIO_STATUS_CALLBACK_URL": CALLBACK,
    "TWILIO_CONTENT_TEMPLATES": {
        "nuevo_encargado": HX, "pago_encargado": HX, "listo_cliente": HX,
        "anulado_encargado": HX, "anulado_cliente": HX,
    },
    "SECURE_SSL_REDIRECT": False,
}


class NotificacionesFixture:
    def setUp(self):
        categoria = Categoria.objects.create(nombre="Bebidas")
        self.producto = Producto.objects.create(
            nombre="Agua", precio=Decimal("1000"), categoria=categoria, stock=10,
        )
        self.medio = MedioPago.objects.create(nombre="Efectivo", tipo="EF")
        self.encargado = EncargadoWhatsApp.objects.create(
            nombre="Encargado", telefono="+56911111111", autorizado=True,
        )

    def crear(self, consentimiento=True):
        return crear_pedido_autoservicio(
            [{"product_id": self.producto.pk, "quantity": 2}], self.medio.pk,
            cliente="Ana", telefono_cliente="9 2222 2222",
            acepta_notificaciones_whatsapp=consentimiento,
        )


@override_settings(**CONFIG)
class NotificacionesTests(NotificacionesFixture, TestCase):
    def test_pedido_crea_una_intencion_por_encargado_autorizado(self):
        EncargadoWhatsApp.objects.create(nombre="Otro", telefono="+56933333333", autorizado=True)
        EncargadoWhatsApp.objects.create(nombre="Sin consentimiento", telefono="+56944444444")
        pedido = self.crear()
        salidas = pedido.notificaciones_salida.order_by("telefono")
        self.assertEqual(salidas.count(), 2)
        self.assertEqual(salidas[0].parametros, {
            "1": pedido.numero_pedido, "2": "Ana", "3": "2x Agua", "4": "$2.000",
        })
        notificar_pedido_nuevo(pedido)
        self.assertEqual(salidas.count(), 2)

    def test_listo_y_anulado_respetan_consentimiento_y_roles(self):
        pedido = self.crear()
        marcar_como_listo(pedido.pk)
        anular_pedido(pedido.pk)
        self.assertEqual(
            set(pedido.notificaciones_salida.values_list("evento", "tipo_destinatario")),
            {("N", "encargado"), ("L", "cliente"), ("A", "encargado"), ("A", "cliente")},
        )
        with self.assertRaises(ValidationError):
            marcar_como_listo(pedido.pk)
        self.assertEqual(pedido.notificaciones_salida.count(), 4)

    def test_cliente_y_encargado_con_mismo_numero_se_registran_por_rol(self):
        self.encargado.telefono = "+56922222222"
        self.encargado.save()
        pedido = self.crear()
        anular_pedido(pedido.pk)
        self.assertEqual(
            set(pedido.notificaciones_salida.filter(evento="A").values_list(
                "tipo_destinatario", flat=True
            )),
            {"cliente", "encargado"},
        )

    def test_sin_consentimiento_no_se_avisa_al_cliente(self):
        pedido = self.crear(False)
        marcar_como_listo(pedido.pk)
        anular_pedido(pedido.pk)
        self.assertFalse(pedido.notificaciones_salida.filter(tipo_destinatario="cliente").exists())

    def test_pago_y_deshabilitado(self):
        pedido = self.crear()
        marcar_como_pagado(pedido.pk, self.medio.pk)
        self.assertTrue(pedido.notificaciones_salida.filter(evento="P").exists())
        with override_settings(TWILIO_ENABLED=False):
            otro = self.crear()
            marcar_como_listo(otro.pk)
        self.assertFalse(otro.notificaciones_salida.exists())

    def test_validacion_de_numeros_y_consentimiento(self):
        self.assertEqual(normalizar_telefono("9 1234 5678"), "+56912345678")
        self.assertEqual(normalizar_telefono("+56 (9) 1234-5678"), "+56912345678")
        for numero in ("12345678", "+1 202 555 0123", "00956912345678", "9abcdefghi"):
            with self.subTest(numero=numero), self.assertRaises(ValueError):
                normalizar_telefono(numero)
        with self.assertRaises(ValidationError):
            crear_pedido_autoservicio(
                [{"product_id": self.producto.pk, "quantity": 1}], self.medio.pk,
                telefono_cliente="123", acepta_notificaciones_whatsapp=True,
            )

    def test_historial_meta_no_es_reinterpretado(self):
        pedido = self.crear()
        historico = NotificacionWhatsApp.objects.create(
            pedido=pedido, evento="N", telefono="56911111111", estado="E",
            identificador_whatsapp="meta-id",
        )
        procesar_pendientes(proveedor=Mock(enviar=Mock(return_value=ResultadoEnvio(SID, "queued"))))
        historico.refresh_from_db()
        self.assertEqual((historico.estado, historico.identificador_whatsapp), ("E", "meta-id"))

    def test_pedido_y_outbox_rollback_juntos(self):
        with patch("pedidos.notificaciones.NotificacionSalida.objects.get_or_create",
                   side_effect=RuntimeError("fallo base")):
            with self.assertRaises(RuntimeError):
                self.crear()
        self.assertFalse(Pedido.objects.exists())

    def test_pedido_persiste_antes_de_enviar(self):
        with patch("pedidos.integrations.whatsapp.Client") as cliente:
            pedido = self.crear()
            self.assertTrue(Pedido.objects.filter(pk=pedido.pk).exists())
            cliente.assert_not_called()


@override_settings(**CONFIG)
class WorkerTests(NotificacionesFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.pedido = self.crear()
        self.salida = self.pedido.notificaciones_salida.get()

    def test_exito_y_reprocesamiento_no_duplica(self):
        proveedor = Mock(enviar=Mock(return_value=ResultadoEnvio(SID, "queued")))
        self.assertEqual(procesar_pendientes(proveedor=proveedor), 1)
        self.assertEqual(procesar_pendientes(proveedor=proveedor), 0)
        self.salida.refresh_from_db()
        self.assertEqual(self.salida.estado, "aceptado")
        self.assertEqual(self.salida.estado_proveedor, "queued")
        self.assertEqual(self.salida.identificador_proveedor, SID)
        self.assertEqual(self.salida.historial_intentos.get().resultado, "aceptado")
        proveedor.enviar.assert_called_once()

    def test_comando_worker_procesa_outbox(self):
        salida = StringIO()
        with patch("pedidos.procesamiento.TwilioWhatsApp") as proveedor:
            proveedor.return_value.enviar.return_value = ResultadoEnvio(SID, "queued")
            call_command("procesar_notificaciones", once=True, stdout=salida)
        self.salida.refresh_from_db()
        self.assertEqual(self.salida.estado, "aceptado")
        self.assertIn("Notificaciones procesadas: 1", salida.getvalue())

    def test_reclamacion_concurrente_no_reenvia(self):
        proveedor = Mock()
        proveedor.enviar.side_effect = lambda _: (
            self.assertEqual(procesar_pendientes(proveedor=proveedor), 0)
            or ResultadoEnvio(SID, "queued")
        )
        procesar_pendientes(proveedor=proveedor)
        proveedor.enviar.assert_called_once()

    def test_error_temporal_se_reintenta_con_limite(self):
        proveedor = Mock(enviar=Mock(side_effect=ErrorEnvio("limitado", "20429", temporal=True)))
        for intento in range(1, MAX_INTENTOS + 1):
            procesar_pendientes(proveedor=proveedor)
            self.salida.refresh_from_db()
            self.assertEqual(self.salida.intentos, intento)
            if intento < MAX_INTENTOS:
                self.assertEqual(self.salida.estado, "pendiente")
                self.assertEqual(procesar_pendientes(proveedor=proveedor), 0)
                NotificacionSalida.objects.filter(pk=self.salida.pk).update(proximo_intento=None)
        self.assertEqual(self.salida.estado, "fallido")
        self.assertEqual(self.salida.historial_intentos.count(), MAX_INTENTOS)

    def test_reintento_exitoso_limpia_error_actual_sin_borrar_historial(self):
        proveedor = Mock(enviar=Mock(side_effect=[
            ErrorEnvio("limitado", "20429", temporal=True), ResultadoEnvio(SID, "queued"),
        ]))
        procesar_pendientes(proveedor=proveedor)
        NotificacionSalida.objects.filter(pk=self.salida.pk).update(proximo_intento=None)
        procesar_pendientes(proveedor=proveedor)
        self.salida.refresh_from_db()
        self.assertEqual((self.salida.estado, self.salida.codigo_error, self.salida.error),
                         ("aceptado", "", ""))
        self.assertEqual(self.salida.historial_intentos.get(numero=1).codigo_error, "20429")

    def test_error_definitivo_y_timeout_ambiguo_no_se_reintentan(self):
        for error, esperado in (
            (ErrorEnvio("rechazado"), "fallido"),
            (ErrorEnvio("timeout", incierto=True), "incierto"),
        ):
            with self.subTest(estado=esperado):
                NotificacionSalida.objects.filter(pk=self.salida.pk).update(estado="pendiente")
                proveedor = Mock(enviar=Mock(side_effect=error))
                procesar_pendientes(proveedor=proveedor)
                self.salida.refresh_from_db()
                self.assertEqual(self.salida.estado, esperado)
                self.assertEqual(procesar_pendientes(proveedor=proveedor), 0)
                self.assertTrue(Pedido.objects.filter(pk=self.pedido.pk).exists())

    def test_worker_deshabilitado_no_envia_pendientes(self):
        proveedor = Mock()
        with override_settings(TWILIO_ENABLED=False):
            self.assertEqual(procesar_pendientes(proveedor=proveedor), 0)
        self.salida.refresh_from_db()
        self.assertEqual(self.salida.estado, "pendiente")
        proveedor.enviar.assert_not_called()

    def test_abandonada_pasa_a_incierto_sin_reenvio(self):
        NotificacionSalida.objects.filter(pk=self.salida.pk).update(
            estado="procesando", ultimo_intento=timezone.now() - timedelta(minutes=6),
        )
        self.assertEqual(recuperar_abandonadas(), 1)
        self.salida.refresh_from_db()
        self.assertEqual(self.salida.estado, "incierto")
        self.assertEqual(procesar_pendientes(proveedor=Mock()), 0)

    def test_revocacion_del_encargado_y_cliente(self):
        self.encargado.autorizado = False
        self.encargado.save()
        proveedor = Mock()
        procesar_pendientes(proveedor=proveedor)
        self.salida.refresh_from_db()
        self.assertEqual(self.salida.estado, "cancelado")
        marcar_como_listo(self.pedido.pk)
        self.pedido.acepta_notificaciones_whatsapp = False
        self.pedido.save(update_fields=["acepta_notificaciones_whatsapp"])
        procesar_pendientes(proveedor=proveedor)
        self.assertEqual(self.pedido.notificaciones_salida.get(evento="L").estado, "cancelado")
        proveedor.enviar.assert_not_called()


@override_settings(**CONFIG)
class TwilioAdapterTests(NotificacionesFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.salida = self.crear().notificaciones_salida.get()

    @patch("pedidos.integrations.whatsapp.Client")
    def test_envio_usa_plantilla_y_callback(self, client):
        client.return_value.messages.create.return_value = Mock(sid=SID, status="queued")
        resultado = TwilioWhatsApp().enviar(self.salida)
        self.assertEqual(resultado, ResultadoEnvio(SID, "queued"))
        argumentos = client.return_value.messages.create.call_args.kwargs
        self.assertEqual(argumentos["content_sid"], HX)
        self.assertEqual(json.loads(argumentos["content_variables"]), self.salida.parametros)
        self.assertEqual(argumentos["to"], "whatsapp:+56911111111")
        self.assertEqual(argumentos["status_callback"], f"{CALLBACK}?n={self.salida.token_callback}")

    @patch("pedidos.integrations.whatsapp.Client")
    def test_errores_api_y_timeout(self, client):
        for excepcion, temporal, incierto in (
            (TwilioRestException(401, "/Messages", code=20003), False, False),
            (TwilioRestException(400, "/Messages", code=63016), False, False),
            (TwilioRestException(400, "/Messages", code=21211), False, False),
            (TwilioRestException(429, "/Messages", code=20429), True, False),
            (TwilioRestException(408, "/Messages"), False, True),
            (ReadTimeout(), False, True),
        ):
            with self.subTest(excepcion=type(excepcion).__name__, temporal=temporal):
                client.return_value.messages.create.side_effect = excepcion
                with self.assertRaises(ErrorEnvio) as raised:
                    TwilioWhatsApp().enviar(self.salida)
                self.assertEqual((raised.exception.temporal, raised.exception.incierto), (temporal, incierto))

    @patch("pedidos.integrations.whatsapp.Client")
    def test_respuesta_invalida_es_incierta(self, client):
        client.return_value.messages.create.return_value = Mock(sid=None, status="queued")
        with self.assertRaises(ErrorEnvio) as raised:
            TwilioWhatsApp().enviar(self.salida)
        self.assertTrue(raised.exception.incierto)

    @patch("pedidos.integrations.whatsapp.TwilioHttpClient")
    def test_cliente_real_serializa_solicitud_y_respuesta(self, http):
        http.return_value.request.return_value = Response(
            201, json.dumps({"sid": SID, "status": "queued"})
        )
        self.assertEqual(TwilioWhatsApp().enviar(self.salida), ResultadoEnvio(SID, "queued"))
        argumentos = http.return_value.request.call_args.kwargs
        url = http.return_value.request.call_args.args[1]
        self.assertTrue(url.startswith("https://api.twilio.com/"))
        self.assertEqual(argumentos["data"]["To"], "whatsapp:+56911111111")
        self.assertEqual(argumentos["data"]["ContentSid"], HX)
        self.assertEqual(json.loads(argumentos["data"]["ContentVariables"]), self.salida.parametros)

    @override_settings(TWILIO_STATUS_CALLBACK_ENABLED=False, TWILIO_STATUS_CALLBACK_URL="")
    @patch("pedidos.integrations.whatsapp.TwilioHttpClient")
    def test_worker_envia_y_registra_sin_callback(self, http):
        http.return_value.request.return_value = Response(
            201, json.dumps({"sid": SID, "status": "queued"})
        )
        self.assertEqual(procesar_pendientes(), 1)
        self.salida.refresh_from_db()
        self.assertEqual(
            (self.salida.estado, self.salida.estado_proveedor, self.salida.identificador_proveedor),
            ("aceptado", "queued", SID),
        )
        self.assertNotIn("StatusCallback", http.return_value.request.call_args.kwargs["data"])
        self.assertEqual(self.salida.historial_intentos.get().resultado, "aceptado")

    @override_settings(
        TWILIO_STATUS_CALLBACK_ENABLED=False, TWILIO_STATUS_CALLBACK_URL="no-es-una-url",
        TWILIO_AUTH_TOKEN="", TWILIO_API_KEY_SID="SK" + "5" * 32,
        TWILIO_API_KEY_SECRET="test-api-secret",
    )
    @patch("pedidos.integrations.whatsapp.Client")
    def test_envio_con_api_key_no_requiere_token_ni_url_sin_callback(self, client):
        client.return_value.messages.create.return_value = Mock(sid=SID, status="queued")
        self.assertEqual(TwilioWhatsApp().enviar(self.salida), ResultadoEnvio(SID, "queued"))
        self.assertNotIn("status_callback", client.return_value.messages.create.call_args.kwargs)

    @override_settings(
        TWILIO_STATUS_CALLBACK_ENABLED=True, TWILIO_AUTH_TOKEN="",
        TWILIO_API_KEY_SID="SK" + "5" * 32, TWILIO_API_KEY_SECRET="test-api-secret",
    )
    def test_callback_habilitado_exige_token_aun_con_api_key(self):
        with self.assertRaises(ErrorEnvio):
            TwilioWhatsApp().enviar(self.salida)

    @override_settings(TWILIO_STATUS_CALLBACK_ENABLED=True, TWILIO_STATUS_CALLBACK_URL="")
    def test_callback_habilitado_exige_url_https(self):
        with self.assertRaises(ErrorEnvio):
            TwilioWhatsApp().enviar(self.salida)
        with override_settings(TWILIO_STATUS_CALLBACK_URL="http://localhost:8000/callback/"):
            with self.assertRaises(ErrorEnvio):
                TwilioWhatsApp().enviar(self.salida)
        with override_settings(TWILIO_STATUS_CALLBACK_URL="https://[invalida"):
            with self.assertRaises(ErrorEnvio):
                TwilioWhatsApp().enviar(self.salida)

    @patch("pedidos.integrations.whatsapp.TwilioHttpClient")
    def test_json_invalido_del_sdk_es_resultado_incierto(self, http):
        http.return_value.request.return_value = Response(201, "not-json")
        with self.assertRaises(ErrorEnvio) as raised:
            TwilioWhatsApp().enviar(self.salida)
        self.assertTrue(raised.exception.incierto)

    def test_plantilla_y_variables_requeridas(self):
        with override_settings(TWILIO_CONTENT_TEMPLATES={}):
            with self.assertRaises(ErrorEnvio):
                TwilioWhatsApp().enviar(self.salida)
        self.salida.parametros.pop("4")
        with self.assertRaises(ErrorEnvio):
            TwilioWhatsApp().enviar(self.salida)


@override_settings(**CONFIG)
class CallbackTests(NotificacionesFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.salida = self.crear().notificaciones_salida.get()
        NotificacionSalida.objects.filter(pk=self.salida.pk).update(estado="procesando")

    def callback(self, estado, *, token=None, sid=SID, firma=True, extra=None):
        query = urlencode({"n": str(token or self.salida.token_callback)})
        datos = {"MessageSid": sid, "MessageStatus": estado, **(extra or {})}
        signature = RequestValidator(CONFIG["TWILIO_AUTH_TOKEN"]).compute_signature(
            f"{CALLBACK}?{query}", datos,
        )
        return self.client.post(
            reverse("twilio_status_callback") + "?" + query, datos,
            HTTP_X_TWILIO_SIGNATURE=signature if firma else "invalid",
        )

    def test_firma_y_mensaje_desconocido(self):
        self.assertEqual(self.callback("sent", firma=False).status_code, 403)
        self.assertEqual(self.callback("sent", token=uuid.uuid4()).status_code, 404)
        self.assertEqual(self.callback("sent", sid="bad").status_code, 400)
        self.assertEqual(self.client.get(reverse("twilio_status_callback")).status_code, 405)

    def test_activar_y_desactivar_callback_no_omite_la_firma(self):
        with override_settings(TWILIO_STATUS_CALLBACK_ENABLED=False):
            self.assertEqual(self.callback("sent").status_code, 404)
        self.salida.refresh_from_db()
        self.assertEqual(self.salida.estado_proveedor, "")
        url = reverse("twilio_status_callback") + "?" + urlencode(
            {"n": str(self.salida.token_callback)}
        )
        self.assertEqual(self.client.post(
            url, {"MessageSid": SID, "MessageStatus": "sent"}
        ).status_code, 403)
        self.assertEqual(self.callback("sent", firma=False).status_code, 403)
        self.assertEqual(self.callback("sent").status_code, 204)
        self.salida.refresh_from_db()
        self.assertEqual(self.salida.estado_proveedor, "sent")

    @override_settings(TWILIO_ENABLED=False)
    def test_callback_habilitado_funciona_con_envios_deshabilitados(self):
        self.assertEqual(self.callback("sent").status_code, 204)
        self.salida.refresh_from_db()
        self.assertEqual(self.salida.estado_proveedor, "sent")

    @override_settings(TWILIO_AUTH_TOKEN="")
    def test_callback_habilitado_sin_token_no_procesa_solicitudes(self):
        self.assertEqual(self.callback("sent").status_code, 503)

    @override_settings(TWILIO_STATUS_CALLBACK_URL="https://[invalida")
    def test_callback_habilitado_con_url_invalida_no_procesa_solicitudes(self):
        self.assertEqual(self.callback("sent").status_code, 503)

    def test_callback_temprano_duplicado_y_fuera_de_orden(self):
        self.assertEqual(self.callback("delivered").status_code, 204)
        self.assertEqual(self.callback("delivered").status_code, 204)
        self.assertEqual(self.callback("sent").status_code, 204)
        self.salida.refresh_from_db()
        self.assertEqual((self.salida.estado, self.salida.estado_proveedor), ("aceptado", "delivered"))
        self.assertIsNotNone(self.salida.entregado_en)
        self.assertEqual(self.callback("read").status_code, 204)
        self.assertEqual(self.callback("undelivered", extra={"ErrorCode": "63000"}).status_code, 204)
        self.salida.refresh_from_db()
        self.assertEqual(self.salida.estado_proveedor, "read")
        self.assertIsNotNone(self.salida.leido_en)

    def test_fallo_y_sid_diferente(self):
        self.assertEqual(self.callback("failed", extra={"ErrorCode": "63000"}).status_code, 204)
        self.salida.refresh_from_db()
        self.assertEqual((self.salida.estado, self.salida.codigo_error), ("fallido", "63000"))
        self.assertEqual(self.callback("sent", sid="SM" + "9" * 32).status_code, 409)

    def test_callback_llega_antes_de_respuesta_del_worker(self):
        NotificacionSalida.objects.filter(pk=self.salida.pk).update(estado="pendiente")

        def enviar(_):
            self.assertEqual(self.callback("delivered").status_code, 204)
            return ResultadoEnvio(SID, "queued")

        procesar_pendientes(proveedor=Mock(enviar=Mock(side_effect=enviar)))
        self.salida.refresh_from_db()
        self.assertEqual(self.salida.estado_proveedor, "delivered")


@override_settings(**CONFIG)
class WorkerConcurrenciaTests(NotificacionesFixture, TransactionTestCase):
    def test_dos_workers_no_reclaman_el_mismo_registro(self):
        self.crear()
        iniciada = threading.Event()
        terminar = threading.Event()
        errores = []
        proveedor = Mock()

        def enviar(_):
            iniciada.set()
            if not terminar.wait(5):
                raise RuntimeError("Tiempo de espera en prueba de concurrencia")
            return ResultadoEnvio(SID, "queued")

        proveedor.enviar.side_effect = enviar

        def ejecutar():
            try:
                procesar_pendientes(proveedor=proveedor)
            except Exception as error:
                errores.append(error)

        hilo = threading.Thread(target=ejecutar)
        hilo.start()
        try:
            self.assertTrue(iniciada.wait(5))
            self.assertEqual(procesar_pendientes(proveedor=proveedor), 0)
        finally:
            terminar.set()
            hilo.join(5)
        self.assertFalse(hilo.is_alive())
        self.assertFalse(errores)
        proveedor.enviar.assert_called_once()


@override_settings(**CONFIG)
class AdminNotificacionesTests(NotificacionesFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser(
            username="admin", password="admin-test"
        ))

    def test_accion_anula_por_el_servicio_y_notifica(self):
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
        self.assertTrue(pedido.notificaciones_salida.filter(evento="A", tipo_destinatario="cliente").exists())

    def test_accion_confirma_pago_por_el_servicio(self):
        pedido = self.crear()
        url = reverse("admin:pedidos_pedido_changelist")
        seleccion = {"action": "accion_confirmar_pago", "_selected_action": [pedido.pk]}
        self.assertContains(self.client.post(url, seleccion), "Confirmar pago de pedidos")
        self.assertEqual(self.client.post(url, {**seleccion, "confirmar_pago": "si"}).status_code, 302)
        pedido.refresh_from_db()
        self.producto.refresh_from_db()
        self.assertEqual(pedido.estado_pago, "G")
        self.assertEqual(self.producto.stock, 8)
        self.assertTrue(pedido.movimientos.filter(tipo="I").exists())
        self.assertTrue(pedido.notificaciones_salida.filter(evento="P").exists())

    def test_reintento_admin_solo_si_no_hay_sid_ni_ambiguedad(self):
        salida = self.crear().notificaciones_salida.get()
        salida.estado = "fallido"
        salida.save(update_fields=["estado"])
        url = reverse("admin:pedidos_notificacionsalida_changelist")
        response = self.client.post(url, {
            "action": "reintentar_rechazadas", "_selected_action": [salida.pk],
        })
        self.assertEqual(response.status_code, 302)
        salida.refresh_from_db()
        self.assertEqual(salida.estado, "pendiente")
        salida.estado = "incierto"
        salida.save(update_fields=["estado"])
        self.client.post(url, {
            "action": "reintentar_rechazadas", "_selected_action": [salida.pk],
        })
        salida.refresh_from_db()
        self.assertEqual(salida.estado, "incierto")

import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from pedidos.procesamiento import procesar_pendientes


class Command(BaseCommand):
    help = "Procesa la outbox de notificaciones de WhatsApp."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Procesa un lote y termina.")
        parser.add_argument("--interval", type=int, default=10)
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if options["interval"] < 1 or options["limit"] < 1:
            raise CommandError("El intervalo y el límite deben ser positivos.")
        while True:
            close_old_connections()
            cantidad = procesar_pendientes(limite=options["limit"])
            if options["once"]:
                self.stdout.write(f"Notificaciones procesadas: {cantidad}")
                return
            if cantidad == 0:
                time.sleep(options["interval"])

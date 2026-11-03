"""Register this app's PayPal webhook (once per environment) and print its id."""

from django.core.management.base import BaseCommand

from payments import webhooks


class Command(BaseCommand):
    help = "Create or find the PayPal webhook for https://<host>/api/webhooks/paypal/ and print its id."

    def add_arguments(self, parser):
        parser.add_argument("base_url", help="public base URL, e.g. https://thuma.onrender.com")

    def handle(self, base_url, **options):
        url = base_url.rstrip("/") + webhooks.WEBHOOK_PATH
        self.stdout.write(f"{webhooks.register(url)}  {url}")

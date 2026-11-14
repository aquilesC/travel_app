from django.core.management.base import BaseCommand

from api.openapi import schema_json


class Command(BaseCommand):
    help = "Print the API's OpenAPI schema (the contract with the iPhone app). Commit it as api/openapi.json."

    def add_arguments(self, parser):
        parser.add_argument("--output", help="Write to this file instead of stdout.")

    def handle(self, *args, output=None, **options):
        text = schema_json()
        if output:
            with open(output, "w") as fh:
                fh.write(text)
        else:
            self.stdout.write(text, ending="")

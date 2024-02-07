from django.apps import AppConfig


class FrontendConfig(AppConfig):
    name = "frontend"

    def ready(self):
        print("I'm ready and starting")

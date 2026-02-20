from django.apps import AppConfig


class FrontendConfig(AppConfig):
    """Configuration for frontend app."""

    name = "frontend"

    def ready(self) -> None:
        """Initialize frontend app — configure PIL settings."""
        from quickbbs.settings import configure_pil

        configure_pil()
        print("I'm ready and starting")

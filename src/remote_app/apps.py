from django.apps import AppConfig


class RemoteAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'remote_app'

    def ready(self):
        # Register pre_save snapshot signal for Entry versioning.
        from . import signals  # noqa: F401
        # Register the sign-in hook that rewrites organization membership.
        from . import authority  # noqa: F401

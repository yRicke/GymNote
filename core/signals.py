from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .db_security import database_user_context
from .default_presets import create_default_workout_presets


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_presets_for_new_user(sender, instance, created, **kwargs):
    if created and not kwargs.get("raw"):
        with database_user_context(instance):
            create_default_workout_presets(instance)

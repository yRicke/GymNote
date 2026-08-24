from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify

from core.catalog import (
    CATALOG,
    EXERCISE_GROUPS,
    PRIMARY_GROUP_OVERRIDES,
    RENAMED_SYSTEM_EXERCISES,
    SYSTEM_EXERCISE_NAMES,
)
from core.models import Exercise, MuscleGroup


class Command(BaseCommand):
    help = "Sincroniza o catálogo padrão de grupos e exercícios."

    @transaction.atomic
    def handle(self, *args, **options):
        groups = {}
        for order, group_name in enumerate(CATALOG, start=1):
            group, _ = MuscleGroup.objects.update_or_create(
                slug=slugify(group_name),
                defaults={
                    "name": group_name,
                    "order": order,
                    "is_active": True,
                    "tracking_type": (
                        MuscleGroup.TrackingType.CARDIO
                        if group_name == "Cardio"
                        else MuscleGroup.TrackingType.STRENGTH
                    ),
                },
            )
            groups[group_name] = group

        for old_name, new_name in RENAMED_SYSTEM_EXERCISES.items():
            old_exercise = Exercise.objects.filter(
                user__isnull=True, name=old_name
            ).first()
            target_exists = Exercise.objects.filter(
                user__isnull=True, name=new_name
            ).exists()
            if old_exercise is not None and not target_exists:
                old_exercise.name = new_name
                old_exercise.save(update_fields=["name"])

        for exercise_name, group_names in EXERCISE_GROUPS.items():
            primary_group_name = PRIMARY_GROUP_OVERRIDES.get(
                exercise_name, group_names[0]
            )
            exercise, _ = Exercise.objects.update_or_create(
                name=exercise_name,
                user=None,
                defaults={
                    "is_active": True,
                    "primary_muscle_group": groups[primary_group_name],
                },
            )
            exercise.muscle_groups.set(
                [groups[group_name] for group_name in group_names]
            )

        Exercise.objects.filter(user__isnull=True).exclude(
            name__in=SYSTEM_EXERCISE_NAMES
        ).filter(
            Q(workout_entries__isnull=True),
            Q(preset_entries__isnull=True),
        ).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Catálogo atualizado: {len(groups)} grupos e "
                f"{len(SYSTEM_EXERCISE_NAMES)} exercícios."
            )
        )

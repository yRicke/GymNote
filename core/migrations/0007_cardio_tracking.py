import django.core.validators
from django.db import migrations, models


CARDIO_EXERCISES = (
    "Caminhada",
    "Corrida",
    "Bicicleta Ergométrica",
    "Elíptico",
    "Escada",
    "Remo Ergométrico",
    "Pular Corda",
    "HIIT",
)


def add_cardio_catalog(apps, schema_editor):
    Exercise = apps.get_model("core", "Exercise")
    MuscleGroup = apps.get_model("core", "MuscleGroup")
    cardio, _ = MuscleGroup.objects.update_or_create(
        slug="cardio",
        defaults={
            "name": "Cardio",
            "order": 11,
            "is_active": True,
            "tracking_type": "cardio",
        },
    )
    for exercise_name in CARDIO_EXERCISES:
        exercise, _ = Exercise.objects.update_or_create(
            name=exercise_name,
            user=None,
            defaults={"is_active": True},
        )
        exercise.muscle_groups.add(cardio)


def remove_cardio_catalog(apps, schema_editor):
    Exercise = apps.get_model("core", "Exercise")
    MuscleGroup = apps.get_model("core", "MuscleGroup")
    cardio = MuscleGroup.objects.filter(slug="cardio").first()
    if not cardio:
        return
    Exercise.objects.filter(
        user__isnull=True,
        name__in=CARDIO_EXERCISES,
        workout_entries__isnull=True,
    ).delete()
    if not cardio.workout_entries.exists() and not cardio.workout_presets.exists():
        cardio.delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0006_workoutpreset_workoutpresetexercise_exercise_user_and_more")]

    operations = [
        migrations.AddField(
            model_name="musclegroup",
            name="tracking_type",
            field=models.CharField(
                choices=[("strength", "Força"), ("cardio", "Cardio")],
                default="strength",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="exerciseset",
            name="duration_minutes",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.AddField(
            model_name="exerciseset",
            name="distance_km",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=7,
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.AddField(
            model_name="exerciseset",
            name="perceived_exertion",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(10),
                ],
            ),
        ),
        migrations.RunPython(add_cardio_catalog, remove_cardio_catalog),
    ]

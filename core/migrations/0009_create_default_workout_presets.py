from django.conf import settings
from django.db import migrations


DEFAULT_WORKOUT_PRESETS = (
    (
        "Treino A — Peito, ombros e tríceps",
        (
            "Supino Reto com Barra",
            "Supino Inclinado com Halteres",
            "Peck Deck",
            "Desenvolvimento com Halteres",
            "Elevação Lateral",
            "Tríceps Corda",
        ),
    ),
    (
        "Treino B — Costas e bíceps",
        (
            "Puxada Alta",
            "Remada Baixa",
            "Remada Unilateral",
            "Face Pull",
            "Rosca Direta",
            "Rosca Martelo",
        ),
    ),
    (
        "Treino C — Pernas",
        (
            "Agachamento Livre",
            "Leg Press",
            "Cadeira Extensora",
            "Stiff",
            "Mesa Flexora",
            "Panturrilha em Pé",
        ),
    ),
)


def create_default_workout_presets(apps, schema_editor):
    user_app, user_model = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(user_app, user_model)
    Exercise = apps.get_model("core", "Exercise")
    WorkoutPreset = apps.get_model("core", "WorkoutPreset")
    WorkoutPresetExercise = apps.get_model("core", "WorkoutPresetExercise")

    exercise_names = {
        name
        for _, preset_exercises in DEFAULT_WORKOUT_PRESETS
        for name in preset_exercises
    }
    exercises_by_name = {
        exercise.name: exercise
        for exercise in Exercise.objects.filter(
            user__isnull=True,
            is_active=True,
            name__in=exercise_names,
        )
    }

    for user in User.objects.iterator():
        for preset_name, exercise_names in DEFAULT_WORKOUT_PRESETS:
            exercises = [exercises_by_name.get(name) for name in exercise_names]
            if any(exercise is None for exercise in exercises):
                continue

            preset, created = WorkoutPreset.objects.get_or_create(
                user_id=user.pk,
                name=preset_name,
            )
            if not created:
                continue

            WorkoutPresetExercise.objects.bulk_create(
                [
                    WorkoutPresetExercise(
                        preset_id=preset.pk,
                        exercise_id=exercise.pk,
                        muscle_group_id=exercise.primary_muscle_group_id,
                        order=order,
                    )
                    for order, exercise in enumerate(exercises, start=1)
                ]
            )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0008_daily_workout_flow"),
    ]

    operations = [
        migrations.RunPython(
            create_default_workout_presets,
            migrations.RunPython.noop,
        ),
    ]

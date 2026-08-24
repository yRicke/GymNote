from django.db import migrations


PRESET_UPDATES = (
    {
        "old_name": "Treino A — Peito, ombros e tríceps",
        "old_exercises": (
            "Supino Reto com Barra",
            "Supino Inclinado com Halteres",
            "Peck Deck",
            "Desenvolvimento com Halteres",
            "Elevação Lateral",
            "Tríceps Corda",
        ),
        "new_name": "Push",
        "new_exercises": (
            "Supino Reto com Barra",
            "Supino Inclinado com Halteres",
            "Desenvolvimento com Halteres",
            "Elevação Lateral",
            "Tríceps na Polia",
            "Tríceps Francês",
        ),
    },
    {
        "old_name": "Treino B — Costas e bíceps",
        "old_exercises": (
            "Puxada Alta",
            "Remada Baixa",
            "Remada Unilateral com Halter",
            "Face Pull",
            "Rosca Direta com Barra",
            "Rosca Martelo",
        ),
        "new_name": "Pull",
        "new_exercises": (
            "Puxada Alta",
            "Remada Baixa",
            "Remada Unilateral com Halter",
            "Face Pull",
            "Rosca Direta com Barra",
            "Rosca Martelo",
        ),
    },
    {
        "old_name": "Treino C — Pernas",
        "old_exercises": (
            "Agachamento Livre",
            "Leg Press",
            "Cadeira Extensora",
            "Stiff",
            "Mesa Flexora",
            "Panturrilha em Pé",
        ),
        "new_name": "Legs",
        "new_exercises": (
            "Agachamento Livre",
            "Leg Press",
            "Cadeira Extensora",
            "Stiff",
            "Mesa Flexora",
            "Panturrilha em Pé",
        ),
    },
)


def update_default_workout_presets(apps, schema_editor):
    Exercise = apps.get_model("core", "Exercise")
    WorkoutPreset = apps.get_model("core", "WorkoutPreset")
    WorkoutPresetExercise = apps.get_model("core", "WorkoutPresetExercise")

    target_names = {
        exercise_name
        for preset_update in PRESET_UPDATES
        for exercise_name in preset_update["new_exercises"]
    }
    exercises_by_name = {
        exercise.name: exercise
        for exercise in Exercise.objects.filter(
            user__isnull=True,
            is_active=True,
            name__in=target_names,
        )
    }

    for preset_update in PRESET_UPDATES:
        new_exercises = [
            exercises_by_name.get(name)
            for name in preset_update["new_exercises"]
        ]
        if any(exercise is None for exercise in new_exercises):
            continue

        candidates = WorkoutPreset.objects.filter(
            name=preset_update["old_name"]
        ).order_by("pk")
        for preset in candidates:
            entries = list(
                preset.exercise_entries.select_related("exercise").order_by(
                    "order", "pk"
                )
            )
            if [entry.order for entry in entries] != list(
                range(1, len(preset_update["old_exercises"]) + 1)
            ):
                continue
            if [entry.exercise.name for entry in entries] != list(
                preset_update["old_exercises"]
            ):
                continue
            if any(entry.exercise.user_id is not None for entry in entries):
                continue

            name_conflict = WorkoutPreset.objects.filter(
                user_id=preset.user_id,
                name=preset_update["new_name"],
            ).exclude(pk=preset.pk)
            if name_conflict.exists():
                preset.delete()
                continue

            preset.name = preset_update["new_name"]
            preset.save(update_fields=["name", "updated_at"])
            preset.exercise_entries.all().delete()
            WorkoutPresetExercise.objects.bulk_create(
                [
                    WorkoutPresetExercise(
                        preset_id=preset.pk,
                        exercise_id=exercise.pk,
                        muscle_group_id=exercise.primary_muscle_group_id,
                        order=order,
                    )
                    for order, exercise in enumerate(new_exercises, start=1)
                ]
            )


class Migration(migrations.Migration):
    dependencies = [("core", "0010_reconcile_system_exercise_catalog")]

    operations = [
        migrations.RunPython(
            update_default_workout_presets,
            migrations.RunPython.noop,
        ),
    ]

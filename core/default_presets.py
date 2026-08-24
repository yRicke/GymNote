from django.db import transaction

from .models import Exercise, WorkoutPreset, WorkoutPresetExercise


DEFAULT_WORKOUT_PRESETS = (
    {
        "name": "Push",
        "exercises": (
            "Supino Reto com Barra",
            "Supino Inclinado com Halteres",
            "Desenvolvimento com Halteres",
            "Elevação Lateral",
            "Tríceps na Polia",
            "Tríceps Francês",
        ),
    },
    {
        "name": "Pull",
        "exercises": (
            "Puxada Alta",
            "Remada Baixa",
            "Remada Unilateral com Halter",
            "Face Pull",
            "Rosca Direta com Barra",
            "Rosca Martelo",
        ),
    },
    {
        "name": "Legs",
        "exercises": (
            "Agachamento Livre",
            "Leg Press",
            "Cadeira Extensora",
            "Stiff",
            "Mesa Flexora",
            "Panturrilha em Pé",
        ),
    },
)


@transaction.atomic
def create_default_workout_presets(user):
    """Cria as predefinições iniciais sem alterar combinações já existentes."""
    exercise_names = {
        name
        for preset_data in DEFAULT_WORKOUT_PRESETS
        for name in preset_data["exercises"]
    }
    exercises_by_name = {
        exercise.name: exercise
        for exercise in Exercise.objects.filter(
            user__isnull=True,
            is_active=True,
            name__in=exercise_names,
        ).select_related("primary_muscle_group")
    }

    created_presets = []
    for preset_data in DEFAULT_WORKOUT_PRESETS:
        exercises = [
            exercises_by_name.get(name) for name in preset_data["exercises"]
        ]
        if any(exercise is None for exercise in exercises):
            continue

        preset, created = WorkoutPreset.objects.get_or_create(
            user=user,
            name=preset_data["name"],
        )
        if not created:
            continue

        WorkoutPresetExercise.objects.bulk_create(
            [
                WorkoutPresetExercise(
                    preset=preset,
                    exercise=exercise,
                    muscle_group=exercise.primary_muscle_group,
                    order=order,
                )
                for order, exercise in enumerate(exercises, start=1)
            ]
        )
        created_presets.append(preset)

    return created_presets

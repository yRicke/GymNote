from collections import defaultdict

from django.db import migrations
from django.db.models import F
from django.utils.text import slugify


CATALOG = {
    "Peito": [
        "Supino Reto com Barra",
        "Supino Reto com Halteres",
        "Supino Inclinado com Barra",
        "Supino Inclinado com Halteres",
        "Crucifixo com Halteres",
        "Crossover na Polia",
        "Peck Deck",
        "Paralelas",
        "Supino Fechado",
    ],
    "Costas": [
        "Puxada Alta",
        "Barra Fixa",
        "Remada Curvada com Barra",
        "Remada Baixa",
        "Remada Unilateral com Halter",
        "Remada Máquina",
        "Pulldown",
        "Pullover na Polia",
        "Face Pull",
        "Levantamento Terra",
    ],
    "Ombros": [
        "Desenvolvimento com Halteres",
        "Desenvolvimento com Barra",
        "Desenvolvimento Máquina",
        "Elevação Lateral",
        "Elevação Frontal",
        "Crucifixo Inverso",
        "Face Pull",
        "Desenvolvimento Militar",
    ],
    "Bíceps": [
        "Rosca Direta com Barra",
        "Rosca Direta com Halteres",
        "Rosca Alternada",
        "Rosca Martelo",
        "Rosca Scott",
        "Rosca Inclinada",
        "Rosca na Polia",
    ],
    "Tríceps": [
        "Tríceps na Polia",
        "Tríceps Francês",
        "Tríceps Testa",
        "Tríceps Corda",
        "Tríceps Unilateral",
        "Paralelas",
        "Supino Fechado",
    ],
    "Quadríceps": [
        "Agachamento Livre",
        "Agachamento no Smith",
        "Leg Press",
        "Hack Squat",
        "Cadeira Extensora",
        "Afundo",
        "Agachamento Búlgaro",
        "Passada",
    ],
    "Posterior de Coxa": [
        "Stiff",
        "Levantamento Terra Romeno",
        "Mesa Flexora",
        "Cadeira Flexora",
        "Flexora Unilateral",
        "Good Morning",
        "Levantamento Terra",
    ],
    "Glúteos": [
        "Elevação Pélvica",
        "Hip Thrust",
        "Coice na Polia",
        "Abdução de Quadril",
        "Passada",
        "Agachamento Livre",
    ],
    "Panturrilhas": [
        "Panturrilha em Pé",
        "Panturrilha Sentada",
        "Panturrilha no Leg Press",
        "Panturrilha Unilateral",
    ],
    "Abdômen": [
        "Abdominal Tradicional",
        "Abdominal Máquina",
        "Abdominal na Polia",
        "Elevação de Pernas",
        "Prancha",
        "Abdominal Infra",
    ],
    "Cardio": [
        "Caminhada",
        "Corrida",
        "Bicicleta Ergométrica",
        "Elíptico",
        "Escada",
        "Remo Ergométrico",
        "Pular Corda",
        "HIIT",
    ],
}

PRIMARY_GROUP_OVERRIDES = {
    "Face Pull": "Ombros",
    "Paralelas": "Tríceps",
    "Passada": "Glúteos",
    "Supino Fechado": "Tríceps",
}

RENAMED_SYSTEM_EXERCISES = {
    "Crucifixo": "Crucifixo com Halteres",
    "Crossover": "Crossover na Polia",
    "Remada Curvada": "Remada Curvada com Barra",
    "Remada Unilateral": "Remada Unilateral com Halter",
    "Remada na Máquina": "Remada Máquina",
    "Desenvolvimento na Máquina": "Desenvolvimento Máquina",
    "Rosca Direta": "Rosca Direta com Barra",
    "Tríceps Barra": "Tríceps na Polia",
    "Tríceps Unilateral na Polia": "Tríceps Unilateral",
    "Búlgaro": "Agachamento Búlgaro",
    "Panturrilha Sentado": "Panturrilha Sentada",
    "Panturrilha Unilateral em Pé": "Panturrilha Unilateral",
    "Abdominal Crunch": "Abdominal Tradicional",
    "Abdução de Quadril na Máquina": "Abdução de Quadril",
}


def normalize_orders(model, parent_field, parent_id):
    entries = list(
        model.objects.filter(**{parent_field: parent_id}).order_by("order", "pk")
    )
    if not entries:
        return
    model.objects.filter(pk__in=[entry.pk for entry in entries]).update(
        order=F("order") + 1_000_000
    )
    for order, entry in enumerate(entries, start=1):
        entry.order = order
        entry.save(update_fields=["order"])


def move_workout_references(
    WorkoutExercise,
    ExerciseSet,
    source_exercise_id,
    target_exercise_id,
    user_id=None,
):
    source_entries = WorkoutExercise.objects.filter(
        exercise_id=source_exercise_id
    ).select_related("workout")
    if user_id is not None:
        source_entries = source_entries.filter(workout__user_id=user_id)

    for source_entry in list(source_entries.order_by("workout_id", "order", "pk")):
        target_entry = WorkoutExercise.objects.filter(
            workout_id=source_entry.workout_id,
            exercise_id=target_exercise_id,
        ).first()
        if target_entry is None:
            source_entry.exercise_id = target_exercise_id
            source_entry.save(update_fields=["exercise"])
            continue

        last_set_order = (
            ExerciseSet.objects.filter(workout_exercise_id=target_entry.pk)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
            or 0
        )
        for offset, exercise_set in enumerate(
            ExerciseSet.objects.filter(
                workout_exercise_id=source_entry.pk
            ).order_by("order", "pk"),
            start=1,
        ):
            exercise_set.workout_exercise_id = target_entry.pk
            exercise_set.order = last_set_order + offset
            exercise_set.save(update_fields=["workout_exercise", "order"])

        workout_id = source_entry.workout_id
        source_entry.delete()
        normalize_orders(WorkoutExercise, "workout_id", workout_id)


def move_preset_references(
    WorkoutPresetExercise,
    source_exercise_id,
    target_exercise_id,
    user_id=None,
):
    source_entries = WorkoutPresetExercise.objects.filter(
        exercise_id=source_exercise_id
    ).select_related("preset")
    if user_id is not None:
        source_entries = source_entries.filter(preset__user_id=user_id)

    for source_entry in list(source_entries.order_by("preset_id", "order", "pk")):
        target_exists = WorkoutPresetExercise.objects.filter(
            preset_id=source_entry.preset_id,
            exercise_id=target_exercise_id,
        ).exists()
        if not target_exists:
            source_entry.exercise_id = target_exercise_id
            source_entry.save(update_fields=["exercise"])
            continue

        preset_id = source_entry.preset_id
        source_entry.delete()
        normalize_orders(WorkoutPresetExercise, "preset_id", preset_id)


def move_all_references(
    WorkoutExercise,
    ExerciseSet,
    WorkoutPresetExercise,
    source_exercise_id,
    target_exercise_id,
    user_id=None,
):
    move_workout_references(
        WorkoutExercise,
        ExerciseSet,
        source_exercise_id,
        target_exercise_id,
        user_id,
    )
    move_preset_references(
        WorkoutPresetExercise,
        source_exercise_id,
        target_exercise_id,
        user_id,
    )


def reconcile_system_exercise_catalog(apps, schema_editor):
    MuscleGroup = apps.get_model("core", "MuscleGroup")
    Exercise = apps.get_model("core", "Exercise")
    WorkoutExercise = apps.get_model("core", "WorkoutExercise")
    ExerciseSet = apps.get_model("core", "ExerciseSet")
    WorkoutPresetExercise = apps.get_model("core", "WorkoutPresetExercise")

    if not Exercise.objects.filter(user__isnull=True).exclude(
        primary_muscle_group__tracking_type="cardio"
    ).exists():
        return

    groups = {}
    for order, group_name in enumerate(CATALOG, start=1):
        group, _ = MuscleGroup.objects.update_or_create(
            slug=slugify(group_name),
            defaults={
                "name": group_name,
                "order": order,
                "is_active": True,
                "tracking_type": "cardio" if group_name == "Cardio" else "strength",
            },
        )
        groups[group_name] = group

    for old_name, new_name in RENAMED_SYSTEM_EXERCISES.items():
        source = Exercise.objects.filter(user__isnull=True, name=old_name).first()
        if source is None:
            continue
        target = Exercise.objects.filter(user__isnull=True, name=new_name).first()
        if target is not None:
            move_all_references(
                WorkoutExercise,
                ExerciseSet,
                WorkoutPresetExercise,
                target.pk,
                source.pk,
            )
            target.delete()
        source.name = new_name
        source.save(update_fields=["name"])

    exercise_groups = defaultdict(list)
    for group_name, exercise_names in CATALOG.items():
        for exercise_name in exercise_names:
            exercise_groups[exercise_name].append(group_name)

    for exercise_name, group_names in exercise_groups.items():
        primary_group_name = PRIMARY_GROUP_OVERRIDES.get(
            exercise_name, group_names[0]
        )
        exercise, _ = Exercise.objects.update_or_create(
            user=None,
            name=exercise_name,
            defaults={
                "is_active": True,
                "primary_muscle_group_id": groups[primary_group_name].pk,
            },
        )
        exercise.muscle_groups.set(
            [groups[group_name].pk for group_name in group_names]
        )

    target_names = set(exercise_groups)
    stale_exercises = list(
        Exercise.objects.filter(user__isnull=True)
        .exclude(name__in=target_names)
        .order_by("pk")
    )
    for stale_exercise in stale_exercises:
        group_ids = list(
            stale_exercise.muscle_groups.values_list("pk", flat=True)
        )
        workout_user_ids = WorkoutExercise.objects.filter(
            exercise_id=stale_exercise.pk
        ).values_list("workout__user_id", flat=True)
        preset_user_ids = WorkoutPresetExercise.objects.filter(
            exercise_id=stale_exercise.pk
        ).values_list("preset__user_id", flat=True)
        user_ids = set(workout_user_ids).union(preset_user_ids)

        for user_id in user_ids:
            personal_exercise = (
                Exercise.objects.filter(
                    user_id=user_id,
                    is_active=True,
                    name__iexact=stale_exercise.name,
                )
                .order_by("pk")
                .first()
            )
            if personal_exercise is None:
                personal_exercise = Exercise.objects.create(
                    user_id=user_id,
                    name=stale_exercise.name,
                    primary_muscle_group_id=stale_exercise.primary_muscle_group_id,
                    is_active=True,
                )
            personal_exercise.muscle_groups.add(*group_ids)
            move_all_references(
                WorkoutExercise,
                ExerciseSet,
                WorkoutPresetExercise,
                stale_exercise.pk,
                personal_exercise.pk,
                user_id,
            )

        stale_exercise.delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0009_create_default_workout_presets")]

    operations = [
        migrations.RunPython(
            reconcile_system_exercise_catalog,
            migrations.RunPython.noop,
        ),
    ]

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Max


def migrate_daily_workout_data(apps, schema_editor):
    Exercise = apps.get_model("core", "Exercise")
    ExerciseSet = apps.get_model("core", "ExerciseSet")
    WorkoutExercise = apps.get_model("core", "WorkoutExercise")
    WorkoutPresetExercise = apps.get_model("core", "WorkoutPresetExercise")

    for exercise in Exercise.objects.all().iterator():
        primary_group = exercise.muscle_groups.order_by("order", "pk").first()
        if primary_group is None:
            raise RuntimeError(
                f"O exercício {exercise.pk} não possui grupo muscular para a migração."
            )
        exercise.primary_muscle_group_id = primary_group.pk
        exercise.save(update_fields=["primary_muscle_group"])

    for entry in WorkoutPresetExercise.objects.select_related("preset").iterator():
        entry.muscle_group_id = entry.preset.muscle_group_id
        entry.save(update_fields=["muscle_group"])

    entries = WorkoutExercise.objects.select_related("workout_muscle_group").order_by(
        "workout_muscle_group__workout_id",
        "workout_muscle_group__order",
        "order",
        "pk",
    )
    workout_orders = {}
    canonical_entries = {}
    for entry in entries.iterator():
        workout_group = entry.workout_muscle_group
        workout_id = workout_group.workout_id
        duplicate_key = (workout_id, entry.exercise_id)
        canonical = canonical_entries.get(duplicate_key)
        if canonical is not None:
            next_set_order = (
                ExerciseSet.objects.filter(workout_exercise_id=canonical.pk).aggregate(
                    maximum=Max("order")
                )["maximum"]
                or 0
            )
            for exercise_set in ExerciseSet.objects.filter(
                workout_exercise_id=entry.pk
            ).order_by("order", "pk"):
                next_set_order += 1
                exercise_set.workout_exercise_id = canonical.pk
                exercise_set.order = next_set_order
                exercise_set.save(update_fields=["workout_exercise", "order"])
            entry.delete()
            continue

        next_order = workout_orders.get(workout_id, 0) + 1
        workout_orders[workout_id] = next_order
        entry.workout_id = workout_id
        entry.muscle_group_id = workout_group.muscle_group_id
        entry.order = next_order
        entry.save(update_fields=["workout", "muscle_group", "order"])
        canonical_entries[duplicate_key] = entry


class Migration(migrations.Migration):

    dependencies = [("core", "0007_cardio_tracking")]

    operations = [
        migrations.AddField(
            model_name="exercise",
            name="primary_muscle_group",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="primary_exercises",
                to="core.musclegroup",
            ),
        ),
        migrations.AddField(
            model_name="workoutpresetexercise",
            name="muscle_group",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="preset_exercise_entries",
                to="core.musclegroup",
            ),
        ),
        migrations.AddField(
            model_name="workoutexercise",
            name="muscle_group",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workout_exercise_entries",
                to="core.musclegroup",
            ),
        ),
        migrations.AddField(
            model_name="workoutexercise",
            name="workout",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="workout_exercises",
                to="core.workout",
            ),
        ),
        migrations.RunPython(migrate_daily_workout_data, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="workoutexercise",
            name="unique_exercise_per_workout_muscle_group",
        ),
        migrations.RemoveConstraint(
            model_name="workoutexercise",
            name="unique_exercise_order_per_workout_muscle_group",
        ),
        migrations.RemoveField(
            model_name="workoutexercise",
            name="workout_muscle_group",
        ),
        migrations.DeleteModel(name="WorkoutMuscleGroup"),
        migrations.RemoveField(
            model_name="workoutpreset",
            name="muscle_group",
        ),
        migrations.AlterField(
            model_name="exercise",
            name="primary_muscle_group",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="primary_exercises",
                to="core.musclegroup",
            ),
        ),
        migrations.AlterField(
            model_name="workoutpresetexercise",
            name="muscle_group",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="preset_exercise_entries",
                to="core.musclegroup",
            ),
        ),
        migrations.AlterField(
            model_name="workoutexercise",
            name="muscle_group",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workout_exercise_entries",
                to="core.musclegroup",
            ),
        ),
        migrations.AlterField(
            model_name="workoutexercise",
            name="workout",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="workout_exercises",
                to="core.workout",
            ),
        ),
        migrations.AddConstraint(
            model_name="workoutexercise",
            constraint=models.UniqueConstraint(
                fields=("workout", "exercise"),
                name="unique_exercise_per_workout",
            ),
        ),
        migrations.AddConstraint(
            model_name="workoutexercise",
            constraint=models.UniqueConstraint(
                fields=("workout", "order"),
                name="unique_exercise_order_per_workout",
            ),
        ),
    ]

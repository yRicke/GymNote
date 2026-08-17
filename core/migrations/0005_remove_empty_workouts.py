from django.db import migrations


def remove_empty_workouts(apps, schema_editor):
    Workout = apps.get_model("core", "Workout")
    Workout.objects.filter(workout_muscle_groups__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_ratelimitcounter"),
    ]

    operations = [
        migrations.RunPython(remove_empty_workouts, migrations.RunPython.noop),
    ]

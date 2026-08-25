from django.db import migrations


def update_policy(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            DROP POLICY IF EXISTS gymnote_tenant_isolation
                ON core_exercise_muscle_groups;
            DROP POLICY IF EXISTS gymnote_exercise_groups_read
                ON core_exercise_muscle_groups;
            DROP POLICY IF EXISTS gymnote_exercise_groups_write
                ON core_exercise_muscle_groups;
            CREATE POLICY gymnote_exercise_groups_read
                ON core_exercise_muscle_groups
                FOR SELECT
                USING (
                    public.gymnote_current_user_is_staff()
                    OR EXISTS (
                        SELECT 1
                        FROM core_exercise
                        WHERE core_exercise.id =
                              core_exercise_muscle_groups.exercise_id
                          AND (
                              core_exercise.user_id IS NULL
                              OR core_exercise.user_id =
                                 public.gymnote_current_user_id()
                          )
                    )
                );
            CREATE POLICY gymnote_exercise_groups_write
                ON core_exercise_muscle_groups
                FOR ALL
                USING (
                    public.gymnote_current_user_is_staff()
                    OR EXISTS (
                        SELECT 1
                        FROM core_exercise
                        WHERE core_exercise.id =
                              core_exercise_muscle_groups.exercise_id
                          AND core_exercise.user_id =
                              public.gymnote_current_user_id()
                    )
                )
                WITH CHECK (
                    public.gymnote_current_user_is_staff()
                    OR EXISTS (
                        SELECT 1
                        FROM core_exercise
                        WHERE core_exercise.id =
                              core_exercise_muscle_groups.exercise_id
                          AND core_exercise.user_id =
                              public.gymnote_current_user_id()
                    )
                );
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_enable_row_level_security"),
    ]

    operations = [
        migrations.RunPython(update_policy, migrations.RunPython.noop),
    ]

from django.db import migrations


TENANT_POLICIES = {
    "core_workout": "user_id = public.gymnote_current_user_id()",
    "core_workoutpreset": "user_id = public.gymnote_current_user_id()",
    "core_workoutexercise": """
        EXISTS (
            SELECT 1
            FROM core_workout
            WHERE core_workout.id = core_workoutexercise.workout_id
              AND core_workout.user_id = public.gymnote_current_user_id()
        )
    """,
    "core_exerciseset": """
        EXISTS (
            SELECT 1
            FROM core_workoutexercise
            JOIN core_workout
              ON core_workout.id = core_workoutexercise.workout_id
            WHERE core_workoutexercise.id = core_exerciseset.workout_exercise_id
              AND core_workout.user_id = public.gymnote_current_user_id()
        )
    """,
    "core_workoutpresetexercise": """
        EXISTS (
            SELECT 1
            FROM core_workoutpreset
            WHERE core_workoutpreset.id = core_workoutpresetexercise.preset_id
              AND core_workoutpreset.user_id = public.gymnote_current_user_id()
        )
    """,
}

APPLICATION_TABLES = (
    *TENANT_POLICIES,
    "core_exercise",
    "core_exercise_muscle_groups",
    "core_musclegroup",
    "core_ratelimitcounter",
)


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION public.gymnote_current_user_id()
            RETURNS bigint
            LANGUAGE sql
            STABLE
            PARALLEL SAFE
            AS $$
                SELECT NULLIF(current_setting('gymnote.user_id', true), '')::bigint
            $$;

            CREATE OR REPLACE FUNCTION public.gymnote_current_user_is_staff()
            RETURNS boolean
            LANGUAGE sql
            STABLE
            PARALLEL SAFE
            AS $$
                SELECT COALESCE(
                    current_setting('gymnote.is_staff', true) = 'true',
                    false
                )
            $$;
            """
        )

        for table, ownership_check in TENANT_POLICIES.items():
            policy_check = (
                f"public.gymnote_current_user_is_staff() OR ({ownership_check})"
            )
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            cursor.execute(
                f'DROP POLICY IF EXISTS gymnote_tenant_isolation ON "{table}"'
            )
            cursor.execute(
                f"""
                CREATE POLICY gymnote_tenant_isolation ON "{table}"
                FOR ALL
                USING ({policy_check})
                WITH CHECK ({policy_check})
                """
            )

        cursor.execute(
            """
            ALTER TABLE core_exercise ENABLE ROW LEVEL SECURITY;
            ALTER TABLE core_exercise FORCE ROW LEVEL SECURITY;
            DROP POLICY IF EXISTS gymnote_exercise_read ON core_exercise;
            DROP POLICY IF EXISTS gymnote_exercise_write ON core_exercise;
            CREATE POLICY gymnote_exercise_read ON core_exercise
                FOR SELECT
                USING (
                    public.gymnote_current_user_is_staff()
                    OR user_id IS NULL
                    OR user_id = public.gymnote_current_user_id()
                );
            CREATE POLICY gymnote_exercise_write ON core_exercise
                FOR ALL
                USING (
                    public.gymnote_current_user_is_staff()
                    OR user_id = public.gymnote_current_user_id()
                )
                WITH CHECK (
                    public.gymnote_current_user_is_staff()
                    OR user_id = public.gymnote_current_user_id()
                );

            ALTER TABLE core_exercise_muscle_groups ENABLE ROW LEVEL SECURITY;
            ALTER TABLE core_exercise_muscle_groups FORCE ROW LEVEL SECURITY;
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

            ALTER TABLE core_musclegroup ENABLE ROW LEVEL SECURITY;
            ALTER TABLE core_musclegroup FORCE ROW LEVEL SECURITY;
            DROP POLICY IF EXISTS gymnote_musclegroup_read ON core_musclegroup;
            DROP POLICY IF EXISTS gymnote_musclegroup_write ON core_musclegroup;
            CREATE POLICY gymnote_musclegroup_read ON core_musclegroup
                FOR SELECT USING (true);
            CREATE POLICY gymnote_musclegroup_write ON core_musclegroup
                FOR ALL
                USING (public.gymnote_current_user_is_staff())
                WITH CHECK (public.gymnote_current_user_is_staff());

            ALTER TABLE core_ratelimitcounter ENABLE ROW LEVEL SECURITY;
            ALTER TABLE core_ratelimitcounter FORCE ROW LEVEL SECURITY;
            DROP POLICY IF EXISTS gymnote_rate_limit_service ON core_ratelimitcounter;
            CREATE POLICY gymnote_rate_limit_service ON core_ratelimitcounter
                FOR ALL USING (true) WITH CHECK (true);
            """
        )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        for table in APPLICATION_TABLES:
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
        cursor.execute(
            """
            DROP FUNCTION IF EXISTS public.gymnote_current_user_is_staff();
            DROP FUNCTION IF EXISTS public.gymnote_current_user_id();
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_update_default_workout_presets"),
    ]

    operations = [
        migrations.RunPython(enable_rls, disable_rls),
    ]

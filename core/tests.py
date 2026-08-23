import json
from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from . import error_views
from .management.commands.seed_gym_data import CATALOG
from .models import (
    Exercise,
    ExerciseSet,
    MuscleGroup,
    Workout,
    WorkoutExercise,
    WorkoutPreset,
    WorkoutPresetExercise,
)


def create_exercise(name, group, *, user=None, secondary_groups=()):
    exercise = Exercise.objects.create(
        name=name,
        user=user,
        primary_muscle_group=group,
    )
    exercise.muscle_groups.set([group, *secondary_groups])
    return exercise


class LandingPageTests(TestCase):
    def test_landing_page_is_public(self):
        response = self.client.get(reverse("core:landing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Seu treino.")
        self.assertContains(response, "data-parallax-speed")
        self.assertContains(response, reverse("accounts:register"))

    def test_authenticated_landing_links_to_calendar_without_bottom_nav(self):
        user = User.objects.create_user("landing_user", password="senha-teste-123")
        self.client.force_login(user)

        response = self.client.get(reverse("core:landing"))

        self.assertContains(response, "Abrir meu calendário")
        self.assertContains(response, reverse("core:calendar"))
        self.assertNotContains(response, 'class="bottom-nav"')

    def test_calendar_is_protected(self):
        response = self.client.get(reverse("core:calendar"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)


@override_settings(DEBUG=False)
class ErrorPageTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")

    def test_not_found_handler_uses_custom_page(self):
        response = self.client.get("/pagina-que-nao-existe/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "404", status_code=404)
        self.assertContains(response, "Esse caminho não existe", status_code=404)

    def test_standard_error_handlers_share_layout(self):
        cases = (
            (error_views.bad_request, 400, "Não conseguimos processar isso"),
            (error_views.permission_denied, 403, "Esta área não está disponível"),
            (error_views.server_error, 500, "Algo saiu do lugar"),
        )
        for handler, status_code, heading in cases:
            with self.subTest(status_code=status_code):
                response = handler(self.request)
                self.assertEqual(response.status_code, status_code)
                self.assertIn(heading, response.content.decode())

    def test_csrf_failure_uses_forbidden_page(self):
        response = error_views.csrf_failure(self.request, reason="CSRF inválido")
        self.assertContains(response, "Acesso não permitido", status_code=403)


class WorkoutFlowTests(TestCase):
    workout_date = date(2026, 8, 14)

    def setUp(self):
        self.user = User.objects.create_user("user_a", password="senha-teste-123")
        self.other_user = User.objects.create_user(
            "user_b", password="senha-teste-123"
        )
        self.quadriceps = MuscleGroup.objects.create(
            name="Quadríceps", slug="quadriceps", order=1
        )
        self.chest = MuscleGroup.objects.create(name="Peito", slug="peito", order=2)
        self.cardio = MuscleGroup.objects.get(slug="cardio")
        self.squat = create_exercise("Agachamento Livre", self.quadriceps)
        self.bench = create_exercise("Supino Reto", self.chest)
        self.run = Exercise.objects.get(name="Corrida", user__isnull=True)
        self.client.force_login(self.user)

    def create_entry(self, exercise=None, *, user=None, order=1, group=None):
        workout = Workout.objects.create(
            user=user or self.user,
            date=self.workout_date,
        )
        exercise = exercise or self.squat
        entry = WorkoutExercise.objects.create(
            workout=workout,
            exercise=exercise,
            muscle_group=group or exercise.primary_muscle_group,
            order=order,
        )
        return workout, entry

    def test_workout_day_requires_authentication(self):
        self.client.logout()
        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_opening_empty_day_does_not_create_workout(self):
        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nenhum exercício adicionado")
        self.assertFalse(Workout.objects.exists())

    def test_add_single_exercise_creates_workout_and_opens_logging(self):
        response = self.client.post(
            reverse("core:add_exercises", kwargs={"date_str": "2026-08-14"}),
            {"exercises": [self.squat.pk]},
        )
        entry = WorkoutExercise.objects.get()

        self.assertRedirects(
            response,
            reverse(
                "core:workout_exercise",
                kwargs={"date_str": "2026-08-14", "pk": entry.pk},
            ),
        )
        self.assertEqual(entry.muscle_group, self.quadriceps)
        self.assertEqual(entry.order, 1)

    def test_add_multiple_groups_builds_one_global_order(self):
        response = self.client.post(
            reverse("core:add_exercises", kwargs={"date_str": "2026-08-14"}),
            {"exercises": [self.squat.pk, self.bench.pk]},
        )
        workout = Workout.objects.get()

        self.assertRedirects(
            response,
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"}),
        )
        self.assertEqual(workout.workout_exercises.count(), 2)
        self.assertEqual(
            list(workout.workout_exercises.values_list("order", flat=True)), [1, 2]
        )
        self.assertEqual(
            set(workout.workout_exercises.values_list("muscle_group", flat=True)),
            {self.quadriceps.pk, self.chest.pk},
        )

    def test_catalog_contains_system_and_owned_custom_exercises(self):
        owned = create_exercise("Agachamento unilateral", self.quadriceps, user=self.user)
        foreign = create_exercise(
            "Exercício secreto", self.quadriceps, user=self.other_user
        )

        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )

        self.assertContains(response, "Agachamento Livre · Quadríceps")
        self.assertContains(
            response, "Agachamento unilateral · Quadríceps · Meu exercício"
        )
        self.assertNotContains(response, foreign.name)
        self.assertContains(response, f'value="{owned.pk}"')

    def test_added_exercise_is_removed_from_catalog(self):
        _, entry = self.create_entry()
        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )

        self.assertContains(response, entry.exercise.name)
        self.assertNotContains(response, f'value="{entry.exercise_id}"')

    def test_live_search_returns_json_and_keeps_full_catalog_default(self):
        url = reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        response = self.client.get(
            url, {"q": "Supino"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertIn("Supino Reto", response.json()["html"])
        self.assertNotIn("Agachamento Livre", response.json()["html"])

    def test_summary_and_descriptions_adapt_to_strength_and_cardio(self):
        workout = Workout.objects.create(user=self.user, date=self.workout_date)
        squat_entry = WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.squat,
            muscle_group=self.quadriceps,
            order=1,
        )
        run_entry = WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.run,
            muscle_group=self.cardio,
            order=2,
        )
        ExerciseSet.objects.create(
            workout_exercise=squat_entry, order=1, reps=10, is_working_set=True
        )
        ExerciseSet.objects.create(
            workout_exercise=squat_entry, order=2, reps=8, is_working_set=False
        )
        ExerciseSet.objects.create(
            workout_exercise=run_entry, order=1, duration_minutes=35
        )

        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )

        self.assertContains(response, "Grupo/modalidade")
        self.assertContains(response, "2 séries")
        self.assertContains(response, "1 válida")
        self.assertContains(response, "1 registro")
        self.assertContains(response, "35 min")
        self.assertContains(response, "Quadríceps ·")
        self.assertContains(response, "Cardio ·")

    def test_workout_list_ignores_empty_and_foreign_workouts(self):
        workout, _ = self.create_entry()
        Workout.objects.create(user=self.user, date=date(2026, 8, 15))
        foreign_workout = Workout.objects.create(
            user=self.other_user, date=date(2026, 8, 16)
        )
        WorkoutExercise.objects.create(
            workout=foreign_workout,
            exercise=self.squat,
            muscle_group=self.quadriceps,
            order=1,
        )

        response = self.client.get(reverse("core:workouts"))

        self.assertEqual(list(response.context["workouts"]), [workout])
        self.assertContains(response, "Quadríceps")

    def test_workout_list_filters_by_entry_group(self):
        workout, _ = self.create_entry()

        included = self.client.get(
            reverse("core:workouts"), {"muscle_groups": [self.quadriceps.pk]}
        )
        excluded = self.client.get(
            reverse("core:workouts"), {"muscle_groups": [self.chest.pk]}
        )

        self.assertIn(workout, included.context["workouts"])
        self.assertNotIn(workout, excluded.context["workouts"])

    def test_calendar_indicator_requires_an_exercise(self):
        Workout.objects.create(user=self.user, date=self.workout_date)
        empty_response = self.client.get(
            reverse("core:calendar"), {"year": 2026, "month": 8}
        )
        self.assertNotContains(empty_response, "com treino registrado")

        empty_workout = Workout.objects.get()
        WorkoutExercise.objects.create(
            workout=empty_workout,
            exercise=self.squat,
            muscle_group=self.quadriceps,
            order=1,
        )
        filled_response = self.client.get(
            reverse("core:calendar"), {"year": 2026, "month": 8}
        )
        self.assertContains(filled_response, "com treino registrado")

    def test_reorder_accepts_entries_from_any_group(self):
        workout = Workout.objects.create(user=self.user, date=self.workout_date)
        first = WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.squat,
            muscle_group=self.quadriceps,
            order=1,
        )
        second = WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.bench,
            muscle_group=self.chest,
            order=2,
        )

        response = self.client.post(
            reverse("core:reorder_exercises", kwargs={"date_str": "2026-08-14"}),
            data=json.dumps({"order": [second.pk, first.pk]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((second.order, first.order), (1, 2))

    def test_reorder_rejects_incomplete_or_foreign_order(self):
        _, entry = self.create_entry()
        url = reverse("core:reorder_exercises", kwargs={"date_str": "2026-08-14"})

        self.assertEqual(
            self.client.post(
                url,
                data=json.dumps({"order": []}),
                content_type="application/json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                url,
                data=json.dumps({"order": [entry.pk, 99999]}),
                content_type="application/json",
            ).status_code,
            400,
        )

    def test_removing_last_exercise_removes_workout_and_sets(self):
        workout, entry = self.create_entry()
        ExerciseSet.objects.create(workout_exercise=entry, order=1, reps=10)
        url = reverse(
            "core:remove_exercise",
            kwargs={"date_str": "2026-08-14", "pk": entry.pk},
        )

        confirmation = self.client.get(url)
        response = self.client.post(url)

        self.assertContains(confirmation, "Todas as séries")
        self.assertRedirects(
            response,
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"}),
        )
        self.assertFalse(Workout.objects.filter(pk=workout.pk).exists())
        self.assertFalse(ExerciseSet.objects.exists())

    def test_workout_day_exercise_removal_uses_modal_and_returns_json(self):
        workout, entry = self.create_entry()
        url = reverse(
            "core:remove_exercise",
            kwargs={"date_str": "2026-08-14", "pk": entry.pk},
        )

        page = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )
        response = self.client.post(
            url,
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertContains(page, 'data-dialog-open="delete-dialog"')
        self.assertContains(page, f'data-delete-url="{url}"')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(Workout.objects.filter(pk=workout.pk).exists())

    def test_set_deletion_uses_modal_and_returns_json(self):
        _, entry = self.create_entry()
        exercise_set = ExerciseSet.objects.create(
            workout_exercise=entry,
            order=1,
            weight_kg=80,
            reps=8,
        )
        url = reverse("core:delete_set", kwargs={"pk": exercise_set.pk})

        page = self.client.get(
            reverse(
                "core:workout_exercise",
                kwargs={"date_str": "2026-08-14", "pk": entry.pk},
            )
        )
        response = self.client.post(
            url,
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertContains(page, f'data-delete-url="{url}"')
        self.assertContains(page, "Excluir série 1?")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Série excluída.")
        self.assertFalse(ExerciseSet.objects.filter(pk=exercise_set.pk).exists())

    def test_exercise_detail_checks_owner_and_date(self):
        _, entry = self.create_entry(user=self.other_user)
        response = self.client.get(
            reverse(
                "core:workout_exercise",
                kwargs={"date_str": "2026-08-14", "pk": entry.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_strength_and_cardio_sets_use_their_group_tracking(self):
        workout = Workout.objects.create(user=self.user, date=self.workout_date)
        strength_entry = WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.squat,
            muscle_group=self.quadriceps,
            order=1,
        )
        cardio_entry = WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.run,
            muscle_group=self.cardio,
            order=2,
        )

        strength_response = self.client.post(
            reverse(
                "core:add_set",
                kwargs={"date_str": "2026-08-14", "pk": strength_entry.pk},
            ),
            {"weight_kg": "80", "reps": "8", "is_working_set": "on"},
        )
        cardio_response = self.client.post(
            reverse(
                "core:add_set",
                kwargs={"date_str": "2026-08-14", "pk": cardio_entry.pk},
            ),
            {"duration_minutes": "30", "distance_km": "5.5"},
        )

        self.assertEqual(strength_response.status_code, 302)
        self.assertEqual(cardio_response.status_code, 302)
        strength_set = strength_entry.sets.get()
        cardio_set = cardio_entry.sets.get()
        self.assertTrue(strength_set.is_working_set)
        self.assertIsNone(strength_set.duration_minutes)
        self.assertEqual(cardio_set.duration_minutes, 30)
        self.assertFalse(cardio_set.is_working_set)


class WorkoutModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("model_user")
        self.other_user = User.objects.create_user("other_model_user")
        self.group = MuscleGroup.objects.create(name="Peito", slug="peito")
        self.other_group = MuscleGroup.objects.create(name="Costas", slug="costas")
        self.exercise = create_exercise("Supino", self.group)
        self.workout = Workout.objects.create(user=self.user, date=date(2026, 8, 14))

    def test_workout_exercise_constraints_are_global_per_day(self):
        WorkoutExercise.objects.create(
            workout=self.workout,
            exercise=self.exercise,
            muscle_group=self.group,
            order=1,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkoutExercise.objects.create(
                workout=self.workout,
                exercise=self.exercise,
                muscle_group=self.group,
                order=2,
            )
        second = create_exercise("Crucifixo", self.group)
        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkoutExercise.objects.create(
                workout=self.workout,
                exercise=second,
                muscle_group=self.group,
                order=1,
            )

    def test_workout_exercise_validates_group_and_owner(self):
        foreign = create_exercise("Remada privada", self.group, user=self.other_user)
        wrong_group_entry = WorkoutExercise(
            workout=self.workout,
            exercise=self.exercise,
            muscle_group=self.other_group,
            order=1,
        )
        foreign_entry = WorkoutExercise(
            workout=self.workout,
            exercise=foreign,
            muscle_group=self.group,
            order=2,
        )

        with self.assertRaises(ValidationError):
            wrong_group_entry.full_clean()
        with self.assertRaises(ValidationError):
            foreign_entry.full_clean()

    def test_workout_date_is_unique_per_user(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Workout.objects.create(user=self.user, date=date(2026, 8, 14))


class PersonalizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("personal", password="senha-teste-123")
        self.other_user = User.objects.create_user(
            "other_personal", password="senha-teste-123"
        )
        self.chest = MuscleGroup.objects.create(name="Peito", slug="peito", order=1)
        self.triceps = MuscleGroup.objects.create(
            name="Tríceps", slug="triceps", order=2
        )
        self.system_chest = create_exercise("Supino Reto", self.chest)
        self.system_triceps = create_exercise("Tríceps Corda", self.triceps)
        self.client.force_login(self.user)

    def create_custom(self, name="Crossover unilateral", group=None, user=None):
        return create_exercise(
            name,
            group or self.chest,
            user=user or self.user,
        )

    def create_preset(self, name="Push A", entries=()):
        preset = WorkoutPreset.objects.create(user=self.user, name=name)
        for order, exercise in enumerate(entries, start=1):
            WorkoutPresetExercise.objects.create(
                preset=preset,
                exercise=exercise,
                muscle_group=exercise.primary_muscle_group,
                order=order,
            )
        return preset

    def test_user_creates_custom_exercise_with_primary_group(self):
        response = self.client.post(
            reverse("core:personalization_exercise_create"),
            {"name": "Supino convergente", "muscle_group": self.chest.pk},
        )
        exercise = Exercise.objects.get(name="Supino convergente")

        self.assertRedirects(response, reverse("core:personalization"))
        self.assertEqual(exercise.primary_muscle_group, self.chest)
        self.assertEqual(list(exercise.muscle_groups.all()), [self.chest])

    def test_personalization_renders_quick_create_and_delete_dialogs(self):
        custom = self.create_custom()
        delete_url = reverse(
            "core:personalization_exercise_delete", kwargs={"pk": custom.pk}
        )

        response = self.client.get(reverse("core:personalization"))

        self.assertContains(response, 'data-dialog-open="create-exercise-dialog"')
        self.assertContains(response, 'id="create-exercise-dialog"')
        self.assertContains(response, 'id="delete-dialog"')
        self.assertContains(response, f'data-delete-url="{delete_url}"')
        self.assertContains(response, "Nome do exercício")
        self.assertContains(response, "Grupo ou modalidade")

    def test_quick_create_exercise_returns_json_and_reuses_validation(self):
        url = reverse("core:personalization_exercise_create")
        headers = {
            "HTTP_ACCEPT": "application/json",
            "HTTP_X_REQUESTED_WITH": "XMLHttpRequest",
        }

        success = self.client.post(
            url,
            {"name": "Crucifixo no cabo", "muscle_group": self.chest.pk},
            **headers,
        )
        duplicate = self.client.post(
            url,
            {"name": "crucifixo no cabo", "muscle_group": self.triceps.pk},
            **headers,
        )
        exercise = Exercise.objects.get(name="Crucifixo no cabo")

        self.assertEqual(success.status_code, 201)
        self.assertTrue(success.json()["ok"])
        self.assertEqual(success.json()["exercise_id"], exercise.pk)
        self.assertEqual(exercise.primary_muscle_group, self.chest)
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("name", duplicate.json()["errors"])
        self.assertEqual(
            Exercise.objects.filter(user=self.user, name__iexact="Crucifixo no cabo").count(),
            1,
        )

    def test_changing_custom_group_updates_presets_but_not_history(self):
        custom = self.create_custom()
        preset = self.create_preset(entries=[custom])
        workout = Workout.objects.create(user=self.user, date=date(2026, 8, 14))
        history = WorkoutExercise.objects.create(
            workout=workout,
            exercise=custom,
            muscle_group=self.chest,
            order=1,
        )

        response = self.client.post(
            reverse("core:personalization_exercise_edit", kwargs={"pk": custom.pk}),
            {"name": custom.name, "muscle_group": self.triceps.pk},
        )
        custom.refresh_from_db()
        history.refresh_from_db()

        self.assertRedirects(response, reverse("core:personalization"))
        self.assertEqual(custom.primary_muscle_group, self.triceps)
        self.assertEqual(preset.exercise_entries.get().muscle_group, self.triceps)
        self.assertEqual(history.muscle_group, self.chest)

    def test_deleting_used_custom_exercise_preserves_history(self):
        custom = self.create_custom()
        preset = self.create_preset(entries=[custom])
        workout = Workout.objects.create(user=self.user, date=date(2026, 8, 14))
        history = WorkoutExercise.objects.create(
            workout=workout,
            exercise=custom,
            muscle_group=self.chest,
            order=1,
        )

        response = self.client.post(
            reverse("core:personalization_exercise_delete", kwargs={"pk": custom.pk}),
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        custom.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(custom.is_active)
        self.assertTrue(WorkoutExercise.objects.filter(pk=history.pk).exists())
        self.assertFalse(preset.exercise_entries.exists())

    def test_user_cannot_delete_another_users_exercise_asynchronously(self):
        foreign = self.create_custom(user=self.other_user)

        response = self.client.post(
            reverse(
                "core:personalization_exercise_delete", kwargs={"pk": foreign.pk}
            ),
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Exercise.objects.filter(pk=foreign.pk, is_active=True).exists())

    def test_create_preset_accepts_multiple_groups_and_order(self):
        response = self.client.post(
            reverse("core:personalization_preset_create"),
            {
                "name": "Push completo",
                "exercises": [self.system_triceps.pk, self.system_chest.pk],
                "exercise_order": f"{self.system_chest.pk},{self.system_triceps.pk}",
            },
        )
        preset = WorkoutPreset.objects.get(name="Push completo")

        self.assertRedirects(response, reverse("core:personalization_presets"))
        self.assertEqual(
            list(
                preset.exercise_entries.values_list(
                    "exercise_id", "muscle_group_id"
                )
            ),
            [
                (self.system_chest.pk, self.chest.pk),
                (self.system_triceps.pk, self.triceps.pk),
            ],
        )

    def test_preset_form_separates_name_card_and_searchable_catalog(self):
        response = self.client.get(reverse("core:personalization_preset_create"))

        self.assertContains(response, 'class="panel preset-builder__card"', count=2)
        self.assertContains(response, 'data-preset-builder')
        self.assertContains(response, 'data-preset-exercise-search')
        self.assertContains(response, 'placeholder="Buscar exercício por nome..."')
        self.assertContains(response, 'data-preset-selected-count')
        self.assertContains(response, 'data-preset-results-count')
        self.assertContains(response, self.system_chest.name)
        self.assertContains(response, self.system_triceps.name)

    def test_edit_preset_renders_search_and_keeps_current_selections(self):
        preset = self.create_preset(
            entries=[self.system_triceps, self.system_chest]
        )

        response = self.client.get(
            reverse("core:personalization_preset_edit", kwargs={"pk": preset.pk})
        )

        self.assertContains(response, 'data-preset-exercise-search')
        self.assertContains(
            response,
            f'value="{self.system_triceps.pk}" id="id_exercises_0" checked',
            html=False,
        )
        self.assertContains(
            response,
            f'value="{self.system_chest.pk}" id="id_exercises_1" checked',
            html=False,
        )
        self.assertContains(response, "2 selecionados")

    def test_preset_rejects_another_users_custom_exercise(self):
        foreign = self.create_custom(user=self.other_user)
        response = self.client.post(
            reverse("core:personalization_preset_create"),
            {"name": "Inválida", "exercises": [foreign.pk]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(WorkoutPreset.objects.filter(name="Inválida").exists())

    def test_preset_list_reports_group_and_exercise_counts(self):
        preset = self.create_preset(entries=[self.system_chest, self.system_triceps])
        response = self.client.get(reverse("core:personalization_presets"))

        self.assertContains(response, "2 grupos")
        self.assertContains(response, "2 exercícios")
        self.assertContains(response, 'data-dialog-open="delete-dialog"')
        self.assertContains(
            response,
            f'data-delete-url="{reverse("core:personalization_preset_delete", kwargs={"pk": preset.pk})}"',
        )

    def test_preset_deletion_returns_json_and_is_isolated_by_user(self):
        preset = self.create_preset(entries=[self.system_chest])
        foreign = WorkoutPreset.objects.create(user=self.other_user, name="Privada")
        headers = {
            "HTTP_ACCEPT": "application/json",
            "HTTP_X_REQUESTED_WITH": "XMLHttpRequest",
        }

        response = self.client.post(
            reverse("core:personalization_preset_delete", kwargs={"pk": preset.pk}),
            **headers,
        )
        foreign_response = self.client.post(
            reverse("core:personalization_preset_delete", kwargs={"pk": foreign.pk}),
            **headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(foreign_response.status_code, 404)
        self.assertFalse(WorkoutPreset.objects.filter(pk=preset.pk).exists())
        self.assertTrue(WorkoutPreset.objects.filter(pk=foreign.pk).exists())

    def test_save_workout_as_preset_preserves_full_order_and_historical_group(self):
        multigroup = create_exercise(
            "Supino Fechado", self.chest, secondary_groups=[self.triceps]
        )
        workout = Workout.objects.create(user=self.user, date=date(2026, 8, 14))
        first = WorkoutExercise.objects.create(
            workout=workout,
            exercise=multigroup,
            muscle_group=self.triceps,
            order=1,
        )
        second = WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.system_chest,
            muscle_group=self.chest,
            order=2,
        )
        url = reverse("core:personalization_preset_create")

        form_response = self.client.get(url, {"source_workout": workout.pk})
        save_response = self.client.post(
            url,
            {
                "name": "Treino do dia",
                "source_workout": workout.pk,
                "exercises": [first.exercise_id, second.exercise_id],
                "exercise_order": f"{first.exercise_id},{second.exercise_id}",
            },
        )
        preset = WorkoutPreset.objects.get(name="Treino do dia")

        self.assertContains(form_response, first.exercise.name)
        self.assertEqual(save_response.status_code, 302)
        self.assertEqual(
            list(
                preset.exercise_entries.values_list(
                    "exercise_id", "muscle_group_id"
                )
            ),
            [
                (first.exercise_id, self.triceps.pk),
                (second.exercise_id, self.chest.pk),
            ],
        )

    def test_workout_day_renders_compact_preset_actions_and_dialogs(self):
        workout = Workout.objects.create(user=self.user, date=date(2026, 8, 14))
        WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.system_chest,
            muscle_group=self.chest,
            order=1,
        )
        self.create_preset(entries=[self.system_chest, self.system_triceps])

        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )

        self.assertContains(response, 'data-dialog-open="save-preset-dialog"')
        self.assertContains(response, 'data-dialog-open="load-preset-dialog"')
        self.assertContains(response, '<dialog class="preset-dialog', count=3)
        self.assertContains(response, "1 exercício")
        self.assertContains(response, "1 grupo")
        self.assertContains(response, 'name="preset_id"')
        self.assertNotContains(response, "button--compact")
        self.assertNotContains(response, "playlist_add_check")

    def test_workout_day_hides_quick_actions_when_their_resources_are_absent(self):
        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )

        self.assertNotContains(response, 'data-dialog-open="save-preset-dialog"')
        self.assertNotContains(response, 'data-dialog-open="load-preset-dialog"')

    def test_quick_save_returns_json_and_preserves_order_and_historical_groups(self):
        multigroup = create_exercise(
            "Supino Fechado", self.chest, secondary_groups=[self.triceps]
        )
        workout = Workout.objects.create(user=self.user, date=date(2026, 8, 14))
        WorkoutExercise.objects.create(
            workout=workout,
            exercise=multigroup,
            muscle_group=self.triceps,
            order=1,
        )
        WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.system_chest,
            muscle_group=self.chest,
            order=2,
        )

        response = self.client.post(
            reverse(
                "core:save_workout_preset", kwargs={"date_str": "2026-08-14"}
            ),
            {"name": "Treino rápido"},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        preset = WorkoutPreset.objects.get(name="Treino rápido")

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["preset_id"], preset.pk)
        self.assertEqual(
            list(
                preset.exercise_entries.values_list(
                    "exercise_id", "muscle_group_id", "order"
                )
            ),
            [
                (multigroup.pk, self.triceps.pk, 1),
                (self.system_chest.pk, self.chest.pk, 2),
            ],
        )
        page = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )
        self.assertContains(page, 'Predefinição &quot;Treino rápido&quot; criada.')

    def test_quick_save_rejects_duplicate_name_with_field_errors(self):
        self.create_preset(name="Push A", entries=[self.system_chest])
        workout = Workout.objects.create(user=self.user, date=date(2026, 8, 14))
        WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.system_chest,
            muscle_group=self.chest,
            order=1,
        )

        response = self.client.post(
            reverse(
                "core:save_workout_preset", kwargs={"date_str": "2026-08-14"}
            ),
            {"name": "push a"},
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json()["errors"])
        self.assertEqual(WorkoutPreset.objects.filter(user=self.user).count(), 1)

    def test_quick_save_rejects_empty_or_another_users_workout(self):
        Workout.objects.create(user=self.user, date=date(2026, 8, 14))
        foreign_workout = Workout.objects.create(
            user=self.other_user, date=date(2026, 8, 15)
        )
        WorkoutExercise.objects.create(
            workout=foreign_workout,
            exercise=self.system_chest,
            muscle_group=self.chest,
            order=1,
        )
        headers = {
            "HTTP_ACCEPT": "application/json",
            "HTTP_X_REQUESTED_WITH": "XMLHttpRequest",
        }

        empty_response = self.client.post(
            reverse(
                "core:save_workout_preset", kwargs={"date_str": "2026-08-14"}
            ),
            {"name": "Vazia"},
            **headers,
        )
        foreign_response = self.client.post(
            reverse(
                "core:save_workout_preset", kwargs={"date_str": "2026-08-15"}
            ),
            {"name": "Privada"},
            **headers,
        )

        self.assertEqual(empty_response.status_code, 404)
        self.assertEqual(foreign_response.status_code, 404)
        self.assertFalse(WorkoutPreset.objects.filter(name__in=["Vazia", "Privada"]).exists())

    def test_quick_save_without_javascript_redirects_to_the_same_day(self):
        workout = Workout.objects.create(user=self.user, date=date(2026, 8, 14))
        WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.system_chest,
            muscle_group=self.chest,
            order=1,
        )

        response = self.client.post(
            reverse(
                "core:save_workout_preset", kwargs={"date_str": "2026-08-14"}
            ),
            {"name": "Fallback"},
        )

        self.assertRedirects(
            response,
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"}),
        )
        self.assertTrue(WorkoutPreset.objects.filter(name="Fallback").exists())

    def test_loading_preset_merges_and_skips_duplicates(self):
        preset = self.create_preset(
            entries=[self.system_chest, self.system_triceps]
        )
        workout = Workout.objects.create(user=self.user, date=date(2026, 8, 14))
        existing = WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.system_chest,
            muscle_group=self.chest,
            order=1,
        )
        ExerciseSet.objects.create(
            workout_exercise=existing, order=1, reps=8, is_working_set=True
        )

        response = self.client.post(
            reverse(
                "core:load_workout_preset", kwargs={"date_str": "2026-08-14"}
            ),
            {"preset_id": preset.pk},
        )

        self.assertRedirects(
            response,
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"}),
        )
        self.assertEqual(workout.workout_exercises.count(), 2)
        self.assertEqual(existing.sets.count(), 1)
        self.assertEqual(
            list(workout.workout_exercises.values_list("exercise_id", flat=True)),
            [self.system_chest.pk, self.system_triceps.pk],
        )

    def test_loading_preset_asynchronously_returns_json_and_message(self):
        preset = self.create_preset(
            entries=[self.system_chest, self.system_triceps]
        )

        response = self.client.post(
            reverse(
                "core:load_workout_preset", kwargs={"date_str": "2026-08-14"}
            ),
            {"preset_id": preset.pk},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["added_count"], 2)
        self.assertEqual(
            list(
                Workout.objects.get(user=self.user).workout_exercises.values_list(
                    "exercise_id", flat=True
                )
            ),
            [self.system_chest.pk, self.system_triceps.pk],
        )
        page = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )
        self.assertContains(page, 'Predefinição &quot;Push A&quot; carregada com 2 exercícios.')

    def test_loading_preset_skips_inactive_exercise(self):
        preset = self.create_preset(entries=[self.system_chest])
        self.system_chest.is_active = False
        self.system_chest.save(update_fields=["is_active"])

        self.client.post(
            reverse(
                "core:load_workout_preset", kwargs={"date_str": "2026-08-14"}
            ),
            {"preset_id": preset.pk},
        )

        self.assertFalse(WorkoutExercise.objects.exists())
        self.assertFalse(Workout.objects.exists())

    def test_user_cannot_load_another_users_preset(self):
        foreign = WorkoutPreset.objects.create(user=self.other_user, name="Privada")
        response = self.client.post(
            reverse(
                "core:load_workout_preset", kwargs={"date_str": "2026-08-14"}
            ),
            {"preset_id": foreign.pk},
        )
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_load_another_users_preset_as_json(self):
        foreign = WorkoutPreset.objects.create(user=self.other_user, name="Privada")
        response = self.client.post(
            reverse(
                "core:load_workout_preset", kwargs={"date_str": "2026-08-14"}
            ),
            {"preset_id": foreign.pk},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["ok"])
        self.assertFalse(Workout.objects.exists())


class SeedGymDataTests(TestCase):
    def test_seed_creates_catalog_and_primary_groups_idempotently(self):
        call_command("seed_gym_data")
        call_command("seed_gym_data")

        self.assertEqual(MuscleGroup.objects.count(), len(CATALOG))
        expected_exercises = {name for names in CATALOG.values() for name in names}
        self.assertEqual(Exercise.objects.count(), len(expected_exercises))
        squat = Exercise.objects.get(name="Agachamento Livre")
        bench = Exercise.objects.get(name="Supino Fechado")
        self.assertEqual(squat.primary_muscle_group.name, "Quadríceps")
        self.assertEqual(bench.primary_muscle_group.name, "Peito")
        self.assertEqual(squat.muscle_groups.count(), 2)
        self.assertEqual(bench.muscle_groups.count(), 2)


class DailyWorkoutMigrationTests(TransactionTestCase):
    migrate_from = [("core", "0007_cardio_tracking")]
    migrate_to = [("core", "0008_daily_workout_flow")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        UserModel = old_apps.get_model("auth", "User")
        MuscleGroupOld = old_apps.get_model("core", "MuscleGroup")
        ExerciseOld = old_apps.get_model("core", "Exercise")
        WorkoutOld = old_apps.get_model("core", "Workout")
        WorkoutGroupOld = old_apps.get_model("core", "WorkoutMuscleGroup")
        WorkoutExerciseOld = old_apps.get_model("core", "WorkoutExercise")
        ExerciseSetOld = old_apps.get_model("core", "ExerciseSet")
        PresetOld = old_apps.get_model("core", "WorkoutPreset")
        PresetEntryOld = old_apps.get_model("core", "WorkoutPresetExercise")

        user = UserModel.objects.create(username="migration_user")
        primary = MuscleGroupOld.objects.create(
            name="Peito", slug="peito", order=1
        )
        secondary = MuscleGroupOld.objects.create(
            name="Tríceps", slug="triceps", order=2
        )
        exercise = ExerciseOld.objects.create(name="Supino Fechado")
        exercise.muscle_groups.set([primary, secondary])
        workout = WorkoutOld.objects.create(user=user, date=date(2026, 8, 14))
        workout_group = WorkoutGroupOld.objects.create(
            workout=workout, muscle_group=secondary, order=1
        )
        workout_entry = WorkoutExerciseOld.objects.create(
            workout_muscle_group=workout_group, exercise=exercise, order=1
        )
        exercise_set = ExerciseSetOld.objects.create(
            workout_exercise=workout_entry,
            order=1,
            reps=8,
            is_working_set=True,
        )
        duplicate_group = WorkoutGroupOld.objects.create(
            workout=workout, muscle_group=primary, order=2
        )
        duplicate_entry = WorkoutExerciseOld.objects.create(
            workout_muscle_group=duplicate_group, exercise=exercise, order=1
        )
        duplicate_set = ExerciseSetOld.objects.create(
            workout_exercise=duplicate_entry,
            order=1,
            reps=12,
            is_working_set=False,
        )
        preset = PresetOld.objects.create(
            user=user, name="Push", muscle_group=secondary
        )
        preset_entry = PresetEntryOld.objects.create(
            preset=preset, exercise=exercise, order=1
        )
        self.ids = {
            "exercise": exercise.pk,
            "workout": workout.pk,
            "workout_entry": workout_entry.pk,
            "set": exercise_set.pk,
            "duplicate_set": duplicate_set.pk,
            "preset": preset.pk,
            "preset_entry": preset_entry.pk,
            "primary": primary.pk,
            "secondary": secondary.pk,
        }

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def test_migration_preserves_workout_sets_groups_order_and_preset(self):
        ExerciseNew = self.apps.get_model("core", "Exercise")
        WorkoutExerciseNew = self.apps.get_model("core", "WorkoutExercise")
        ExerciseSetNew = self.apps.get_model("core", "ExerciseSet")
        PresetNew = self.apps.get_model("core", "WorkoutPreset")
        PresetEntryNew = self.apps.get_model("core", "WorkoutPresetExercise")

        exercise = ExerciseNew.objects.get(pk=self.ids["exercise"])
        workout_entry = WorkoutExerciseNew.objects.get(pk=self.ids["workout_entry"])
        exercise_set = ExerciseSetNew.objects.get(pk=self.ids["set"])
        preset = PresetNew.objects.get(pk=self.ids["preset"])
        preset_entry = PresetEntryNew.objects.get(pk=self.ids["preset_entry"])

        self.assertEqual(exercise.primary_muscle_group_id, self.ids["primary"])
        self.assertEqual(workout_entry.workout_id, self.ids["workout"])
        self.assertEqual(workout_entry.muscle_group_id, self.ids["secondary"])
        self.assertEqual(workout_entry.order, 1)
        self.assertEqual(exercise_set.workout_exercise_id, workout_entry.pk)
        duplicate_set = ExerciseSetNew.objects.get(pk=self.ids["duplicate_set"])
        self.assertEqual(duplicate_set.workout_exercise_id, workout_entry.pk)
        self.assertEqual(
            list(
                ExerciseSetNew.objects.filter(
                    workout_exercise_id=workout_entry.pk
                ).values_list("order", flat=True)
            ),
            [1, 2],
        )
        self.assertEqual(preset.name, "Push")
        self.assertEqual(preset_entry.muscle_group_id, self.ids["secondary"])


@override_settings(
    GYMNOTE_RATE_LIMITS={
        "auth": {"limit": 2, "window_seconds": 300},
        "write": {"limit": 2, "window_seconds": 60},
    }
)
class RateLimitTests(TestCase):
    def test_authentication_attempts_are_limited_by_ip(self):
        login_url = reverse("accounts:login")
        payload = {"username": "inexistente", "password": "incorreta"}

        self.assertEqual(self.client.post(login_url, payload).status_code, 200)
        self.assertEqual(self.client.post(login_url, payload).status_code, 200)
        response = self.client.post(login_url, payload)

        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        self.assertEqual(response["X-RateLimit-Remaining"], "0")

    def test_authenticated_writes_are_limited_by_user(self):
        user = User.objects.create_user("rate_user", password="senha-teste-123")
        group = MuscleGroup.objects.create(name="Peito", slug="peito")
        exercise = create_exercise("Supino", group)
        self.client.force_login(user)
        url = reverse("core:add_exercises", kwargs={"date_str": "2026-08-14"})

        self.assertEqual(
            self.client.post(url, {"exercises": [exercise.pk]}).status_code, 302
        )
        self.assertEqual(self.client.post(url, {}).status_code, 302)
        self.assertEqual(self.client.post(url, {}).status_code, 429)

    def test_get_requests_are_not_rate_limited(self):
        user = User.objects.create_user("reader", password="senha-teste-123")
        self.client.force_login(user)
        calendar_url = reverse("core:calendar")
        for _ in range(5):
            response = self.client.get(calendar_url)
        self.assertEqual(response.status_code, 200)

import json
from datetime import date

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.test import override_settings
from django.urls import reverse

from . import error_views
from .management.commands.seed_gym_data import CATALOG
from .models import (
    Exercise,
    ExerciseSet,
    MuscleGroup,
    Workout,
    WorkoutExercise,
    WorkoutMuscleGroup,
    WorkoutPreset,
    WorkoutPresetExercise,
)


class LandingPageTests(TestCase):
    def test_landing_page_is_public_and_includes_parallax(self):
        response = self.client.get(reverse("core:landing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Seu treino.")
        self.assertContains(response, "data-parallax-speed")
        self.assertContains(response, "core/js/landing.js")
        self.assertContains(response, "gsap@3.13.0")
        self.assertContains(response, "data-section-reveal")
        self.assertContains(response, "Uma sequência natural para o seu treino.")
        self.assertNotContains(response, "Fluxo direto")
        self.assertContains(response, reverse("accounts:register"))

    def test_authenticated_landing_links_to_calendar_without_bottom_nav(self):
        user = User.objects.create_user("landing_user", password="senha-teste-123")
        self.client.force_login(user)

        response = self.client.get(reverse("core:landing"))

        self.assertContains(response, "Abrir meu calendário")
        self.assertContains(response, reverse("core:calendar"))
        self.assertNotContains(response, 'class="bottom-nav"')

    def test_calendar_remains_protected_at_dedicated_url(self):
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
        self.assertContains(response, "Voltar ao início", status_code=404)
        self.assertNotContains(response, 'class="bottom-nav"', status_code=404)

    def test_standard_error_handlers_share_the_same_layout(self):
        cases = (
            (error_views.bad_request, 400, "Não conseguimos processar isso"),
            (error_views.permission_denied, 403, "Esta área não está disponível"),
            (error_views.server_error, 500, "Algo saiu do lugar"),
        )

        for handler, status_code, heading in cases:
            with self.subTest(status_code=status_code):
                response = handler(self.request)
                content = response.content.decode()

                self.assertEqual(response.status_code, status_code)
                self.assertIn(heading, content)
                self.assertIn("Voltar ao início", content)
                self.assertIn("GymNote", content)

    def test_csrf_failure_uses_forbidden_page(self):
        response = error_views.csrf_failure(self.request, reason="CSRF inválido")

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            "Acesso não permitido",
            status_code=403,
        )


class WorkoutFlowTests(TestCase):
    workout_date = date(2026, 8, 14)

    def setUp(self):
        self.user_a = User.objects.create_user("user_a", password="senha-teste-123")
        self.user_b = User.objects.create_user("user_b", password="senha-teste-123")
        self.quadriceps = MuscleGroup.objects.create(
            name="Quadríceps", slug="quadriceps", order=1
        )
        self.exercise = Exercise.objects.create(name="Agachamento Livre")
        self.exercise.muscle_groups.add(self.quadriceps)

    def create_exercise_entry(self, user=None):
        workout = Workout.objects.create(
            user=user or self.user_a,
            date=self.workout_date,
        )
        workout_group = WorkoutMuscleGroup.objects.create(
            workout=workout,
            muscle_group=self.quadriceps,
            order=1,
        )
        workout_exercise = WorkoutExercise.objects.create(
            workout_muscle_group=workout_group,
            exercise=self.exercise,
            order=1,
        )
        return workout, workout_group, workout_exercise

    def test_unauthenticated_user_cannot_access_workout(self):
        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_unauthenticated_user_cannot_access_workout_list(self):
        response = self.client.get(reverse("core:workouts"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_workout_list_only_shows_owned_workouts_with_groups(self):
        older_workout = Workout.objects.create(
            user=self.user_a,
            date=self.workout_date,
        )
        WorkoutMuscleGroup.objects.create(
            workout=older_workout,
            muscle_group=self.quadriceps,
            order=1,
        )
        ghost_workout = Workout.objects.create(
            user=self.user_a,
            date=date(2026, 8, 15),
        )
        other_users_workout = Workout.objects.create(
            user=self.user_b,
            date=date(2026, 8, 16),
        )
        WorkoutMuscleGroup.objects.create(
            workout=other_users_workout,
            muscle_group=self.quadriceps,
            order=1,
        )
        newer_workout = Workout.objects.create(
            user=self.user_a,
            date=date(2026, 8, 17),
        )
        WorkoutMuscleGroup.objects.create(
            workout=newer_workout,
            muscle_group=self.quadriceps,
            order=1,
        )
        self.client.force_login(self.user_a)

        response = self.client.get(reverse("core:workouts"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["workouts"]),
            [newer_workout, older_workout],
        )
        self.assertContains(
            response,
            reverse(
                "core:workout_day",
                kwargs={"date_str": older_workout.date.isoformat()},
            ),
        )
        self.assertNotContains(
            response,
            reverse(
                "core:workout_day",
                kwargs={"date_str": ghost_workout.date.isoformat()},
            ),
        )
        self.assertNotContains(
            response,
            reverse(
                "core:workout_day",
                kwargs={"date_str": other_users_workout.date.isoformat()},
            ),
        )

    def test_workout_list_filters_by_multiple_muscle_groups(self):
        posterior = MuscleGroup.objects.create(
            name="Posterior de Coxa",
            slug="posterior-de-coxa",
            order=2,
        )
        chest = MuscleGroup.objects.create(
            name="Peito",
            slug="peito",
            order=3,
        )
        quadriceps_workout = Workout.objects.create(
            user=self.user_a,
            date=self.workout_date,
        )
        WorkoutMuscleGroup.objects.create(
            workout=quadriceps_workout,
            muscle_group=self.quadriceps,
            order=1,
        )
        posterior_workout = Workout.objects.create(
            user=self.user_a,
            date=date(2026, 8, 15),
        )
        WorkoutMuscleGroup.objects.create(
            workout=posterior_workout,
            muscle_group=posterior,
            order=1,
        )
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse("core:workouts"),
            {"muscle_groups": [self.quadriceps.pk]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_groups"], [self.quadriceps])
        self.assertEqual(list(response.context["workouts"]), [quadriceps_workout])
        self.assertContains(response, "Quadríceps")
        self.assertNotContains(
            response,
            reverse(
                "core:workout_day",
                kwargs={"date_str": posterior_workout.date.isoformat()},
            ),
        )

        multiple_results = self.client.get(
            reverse("core:workouts"),
            {"muscle_groups": [self.quadriceps.pk, posterior.pk]},
        )

        self.assertEqual(
            list(multiple_results.context["workouts"]),
            [posterior_workout, quadriceps_workout],
        )

        no_results = self.client.get(
            reverse("core:workouts"),
            {"muscle_groups": [chest.pk]},
        )

        self.assertContains(no_results, "Nenhum treino encontrado")
        self.assertQuerySetEqual(no_results.context["workouts"], [])

    def test_opening_empty_day_does_not_create_workout(self):
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Workout.objects.exists())

    def test_calendar_indicator_requires_a_muscle_group(self):
        workout = Workout.objects.create(user=self.user_a, date=self.workout_date)
        self.client.force_login(self.user_a)

        calendar_url = reverse("core:calendar")
        response = self.client.get(calendar_url, {"year": 2026, "month": 8})

        self.assertNotContains(response, "calendar-day__dot")

        WorkoutMuscleGroup.objects.create(
            workout=workout,
            muscle_group=self.quadriceps,
            order=1,
        )
        response = self.client.get(calendar_url, {"year": 2026, "month": 8})

        self.assertContains(response, "calendar-day__dot", count=1)

    def test_workout_page_has_no_lifecycle_controls(self):
        Workout.objects.create(user=self.user_a, date=self.workout_date)
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )

        self.assertNotContains(response, "Status:")
        self.assertNotContains(response, "Iniciar treino")
        self.assertNotContains(response, "Finalizar treino")

    def test_workout_page_counts_exercises_and_working_sets_per_group(self):
        _, workout_group, first_entry = self.create_exercise_entry()
        second_exercise = Exercise.objects.create(name="Leg Press")
        second_exercise.muscle_groups.add(self.quadriceps)
        second_entry = WorkoutExercise.objects.create(
            workout_muscle_group=workout_group,
            exercise=second_exercise,
            order=2,
        )
        ExerciseSet.objects.create(
            workout_exercise=first_entry,
            order=1,
            is_working_set=False,
        )
        ExerciseSet.objects.create(
            workout_exercise=first_entry,
            order=2,
            is_working_set=True,
        )
        ExerciseSet.objects.create(
            workout_exercise=second_entry,
            order=1,
            is_working_set=True,
        )
        ExerciseSet.objects.create(
            workout_exercise=second_entry,
            order=2,
            is_working_set=True,
        )
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )

        annotated_group = response.context["workout_groups"].get(pk=workout_group.pk)
        self.assertEqual(annotated_group.exercise_count, 2)
        self.assertEqual(annotated_group.working_set_count, 3)
        self.assertContains(response, "2 exercícios e 3 séries válidas")

    def test_user_cannot_access_another_users_workout_group(self):
        _, workout_group, _ = self.create_exercise_entry(user=self.user_b)
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse(
                "core:muscle_group",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_group_page_counts_total_and_working_sets(self):
        _, workout_group, first_entry = self.create_exercise_entry()
        second_exercise = Exercise.objects.create(name="Leg Press")
        second_exercise.muscle_groups.add(self.quadriceps)
        second_entry = WorkoutExercise.objects.create(
            workout_muscle_group=workout_group,
            exercise=second_exercise,
            order=2,
        )
        ExerciseSet.objects.create(
            workout_exercise=first_entry,
            order=1,
            is_working_set=False,
        )
        ExerciseSet.objects.create(
            workout_exercise=first_entry,
            order=2,
            is_working_set=True,
        )
        ExerciseSet.objects.create(
            workout_exercise=second_entry,
            order=1,
            is_working_set=True,
        )
        ExerciseSet.objects.create(
            workout_exercise=second_entry,
            order=2,
            is_working_set=True,
        )
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse(
                "core:muscle_group",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            )
        )

        self.assertEqual(response.context["total_set_count"], 4)
        self.assertEqual(response.context["working_set_count"], 3)
        self.assertContains(response, "<span>Séries</span><strong>4</strong>", html=True)
        self.assertContains(response, "<span>Válidas</span><strong>3</strong>", html=True)

    def test_cannot_create_two_workouts_for_same_user_and_date(self):
        Workout.objects.create(user=self.user_a, date=self.workout_date)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Workout.objects.create(user=self.user_a, date=self.workout_date)

    def test_cannot_duplicate_group_in_same_workout(self):
        workout = Workout.objects.create(user=self.user_a, date=self.workout_date)
        WorkoutMuscleGroup.objects.create(
            workout=workout, muscle_group=self.quadriceps, order=1
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkoutMuscleGroup.objects.create(
                    workout=workout, muscle_group=self.quadriceps, order=2
                )

    def test_adding_group_creates_workout_and_assigns_order(self):
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse(
                "core:add_muscle_groups",
                kwargs={"date_str": "2026-08-14"},
            ),
            {"add-muscle_groups": [self.quadriceps.pk]},
        )

        workout_group = WorkoutMuscleGroup.objects.get(
            workout__user=self.user_a,
            workout__date=self.workout_date,
        )
        self.assertRedirects(
            response,
            reverse(
                "core:muscle_group",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            ),
        )
        self.assertEqual(workout_group.order, 1)

    def test_adding_multiple_groups_redirects_to_workout_day(self):
        posterior = MuscleGroup.objects.create(
            name="Posterior de Coxa", slug="posterior-de-coxa", order=2
        )
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse(
                "core:add_muscle_groups",
                kwargs={"date_str": "2026-08-14"},
            ),
            {"add-muscle_groups": [self.quadriceps.pk, posterior.pk]},
        )

        self.assertRedirects(
            response,
            reverse(
                "core:workout_day",
                kwargs={"date_str": "2026-08-14"},
            ),
        )
        self.assertEqual(
            WorkoutMuscleGroup.objects.filter(
                workout__user=self.user_a,
                workout__date=self.workout_date,
            ).count(),
            2,
        )

    def test_removing_last_group_deletes_empty_workout(self):
        workout = Workout.objects.create(user=self.user_a, date=self.workout_date)
        workout_group = WorkoutMuscleGroup.objects.create(
            workout=workout,
            muscle_group=self.quadriceps,
            order=1,
        )
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse(
                "core:remove_muscle_group",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            ),
        )

        self.assertRedirects(
            response,
            reverse(
                "core:workout_day",
                kwargs={"date_str": "2026-08-14"},
            ),
        )
        self.assertFalse(WorkoutMuscleGroup.objects.filter(pk=workout_group.pk).exists())
        self.assertFalse(Workout.objects.filter(pk=workout.pk).exists())

    def test_removing_one_group_keeps_workout_with_remaining_group(self):
        posterior = MuscleGroup.objects.create(
            name="Posterior de Coxa", slug="posterior-de-coxa", order=2
        )
        workout = Workout.objects.create(user=self.user_a, date=self.workout_date)
        quadriceps_group = WorkoutMuscleGroup.objects.create(
            workout=workout,
            muscle_group=self.quadriceps,
            order=1,
        )
        WorkoutMuscleGroup.objects.create(
            workout=workout,
            muscle_group=posterior,
            order=2,
        )
        self.client.force_login(self.user_a)

        self.client.post(
            reverse(
                "core:remove_muscle_group",
                kwargs={"date_str": "2026-08-14", "pk": quadriceps_group.pk},
            ),
        )

        self.assertTrue(Workout.objects.filter(pk=workout.pk).exists())
        self.assertEqual(workout.workout_muscle_groups.count(), 1)

    def test_user_cannot_remove_another_users_workout_group(self):
        _, workout_group, _ = self.create_exercise_entry(user=self.user_b)
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse(
                "core:remove_muscle_group",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(WorkoutMuscleGroup.objects.filter(pk=workout_group.pk).exists())

    def test_group_removal_requires_confirmation(self):
        _, workout_group, _ = self.create_exercise_entry()
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse(
                "core:remove_muscle_group",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Excluir Quadríceps?")
        self.assertContains(response, "Confirmar exclusão")
        self.assertTrue(WorkoutMuscleGroup.objects.filter(pk=workout_group.pk).exists())

    def test_exercise_removal_requires_confirmation(self):
        _, workout_group, workout_exercise = self.create_exercise_entry()
        self.client.force_login(self.user_a)
        remove_url = reverse(
            "core:remove_exercise",
            kwargs={"date_str": "2026-08-14", "pk": workout_exercise.pk},
        )

        confirmation = self.client.get(remove_url)

        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, "Excluir Agachamento Livre?")
        self.assertTrue(WorkoutExercise.objects.filter(pk=workout_exercise.pk).exists())

        response = self.client.post(remove_url)

        self.assertRedirects(
            response,
            reverse(
                "core:muscle_group",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            ),
        )
        self.assertFalse(WorkoutExercise.objects.filter(pk=workout_exercise.pk).exists())

    def test_adding_exercise_redirects_to_its_logging_page(self):
        workout = Workout.objects.create(user=self.user_a, date=self.workout_date)
        workout_group = WorkoutMuscleGroup.objects.create(
            workout=workout,
            muscle_group=self.quadriceps,
            order=1,
        )
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse(
                "core:add_exercises",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            ),
            {"exercises": [self.exercise.pk]},
        )

        workout_exercise = WorkoutExercise.objects.get(
            workout_muscle_group=workout_group,
            exercise=self.exercise,
        )
        self.assertRedirects(
            response,
            reverse(
                "core:workout_exercise",
                kwargs={"date_str": "2026-08-14", "pk": workout_exercise.pk},
            ),
        )

    def test_adding_multiple_exercises_redirects_to_muscle_group(self):
        second_exercise = Exercise.objects.create(name="Leg Press")
        second_exercise.muscle_groups.add(self.quadriceps)
        workout = Workout.objects.create(user=self.user_a, date=self.workout_date)
        workout_group = WorkoutMuscleGroup.objects.create(
            workout=workout,
            muscle_group=self.quadriceps,
            order=1,
        )
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse(
                "core:add_exercises",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            ),
            {"exercises": [self.exercise.pk, second_exercise.pk]},
        )

        self.assertRedirects(
            response,
            reverse(
                "core:muscle_group",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            ),
        )
        self.assertEqual(workout_group.workout_exercises.count(), 2)

    def test_profile_ignores_workout_without_groups(self):
        Workout.objects.create(user=self.user_a, date=self.workout_date)
        valid_workout = Workout.objects.create(
            user=self.user_a,
            date=date(2026, 8, 15),
        )
        WorkoutMuscleGroup.objects.create(
            workout=valid_workout,
            muscle_group=self.quadriceps,
            order=1,
        )
        self.client.force_login(self.user_a)

        response = self.client.get(reverse("accounts:profile"))

        self.assertEqual(response.context["workout_count"], 1)

    def test_invalid_group_submission_does_not_create_workout(self):
        self.client.force_login(self.user_a)

        self.client.post(
            reverse(
                "core:add_muscle_groups",
                kwargs={"date_str": "2026-08-14"},
            ),
            {},
        )

        self.assertFalse(Workout.objects.exists())

    def test_series_creation_and_working_set_count(self):
        _, _, workout_exercise = self.create_exercise_entry()
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse(
                "core:add_set",
                kwargs={"date_str": "2026-08-14", "pk": workout_exercise.pk},
            ),
            {
                "weight_kg": "60",
                "reps": "4",
                "partial_reps": "",
                "is_working_set": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "core:workout_exercise",
                kwargs={"date_str": "2026-08-14", "pk": workout_exercise.pk},
            ),
        )
        exercise_set = ExerciseSet.objects.get(workout_exercise=workout_exercise)
        self.assertEqual(exercise_set.order, 1)
        self.assertTrue(exercise_set.is_working_set)
        self.assertEqual(workout_exercise.working_set_count, 1)

        detail = self.client.get(
            reverse(
                "core:workout_exercise",
                kwargs={"date_str": "2026-08-14", "pk": workout_exercise.pk},
            )
        )
        self.assertContains(detail, "Séries válidas: 1")

    def test_set_edit_endpoint_rejects_another_users_set(self):
        _, _, workout_exercise = self.create_exercise_entry(user=self.user_b)
        exercise_set = ExerciseSet.objects.create(
            workout_exercise=workout_exercise,
            order=1,
        )
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse("core:edit_set", kwargs={"pk": exercise_set.pk})
        )

        self.assertEqual(response.status_code, 404)


class PersonalizationTests(TestCase):
    workout_date = date(2026, 8, 14)

    def setUp(self):
        self.user_a = User.objects.create_user("owner", password="senha-teste-123")
        self.user_b = User.objects.create_user("visitor", password="senha-teste-123")
        self.quadriceps = MuscleGroup.objects.create(
            name="Quadríceps",
            slug="quadriceps-personalization",
            order=1,
        )
        self.posterior = MuscleGroup.objects.create(
            name="Posterior de Coxa",
            slug="posterior-personalization",
            order=2,
        )
        self.system_exercise = Exercise.objects.create(name="Agachamento Livre")
        self.system_exercise.muscle_groups.add(self.quadriceps)

    def create_custom_exercise(self, user=None, name="Agachamento personalizado"):
        exercise = Exercise.objects.create(
            user=user or self.user_a,
            name=name,
        )
        exercise.muscle_groups.add(self.quadriceps)
        return exercise

    def create_preset(self, user=None, muscle_group=None, name="Treino A"):
        preset = WorkoutPreset.objects.create(
            user=user or self.user_a,
            name=name,
            muscle_group=muscle_group or self.quadriceps,
        )
        return preset

    def test_personalization_requires_authentication(self):
        response = self.client.get(reverse("core:personalization"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_user_creates_custom_exercise_and_only_sees_owned_catalog(self):
        self.client.force_login(self.user_a)
        create_response = self.client.post(
            reverse("core:personalization_exercise_create"),
            {
                "name": "Extensora unilateral",
                "muscle_group": self.quadriceps.pk,
            },
        )
        custom_exercise = Exercise.objects.get(name="Extensora unilateral")
        other_users_exercise = self.create_custom_exercise(
            user=self.user_b,
            name="Exercício privado de outro usuário",
        )
        workout = Workout.objects.create(user=self.user_a, date=self.workout_date)
        workout_group = WorkoutMuscleGroup.objects.create(
            workout=workout,
            muscle_group=self.quadriceps,
            order=1,
        )

        catalog_response = self.client.get(
            reverse(
                "core:muscle_group",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            )
        )

        self.assertRedirects(create_response, reverse("core:personalization"))
        self.assertEqual(custom_exercise.user, self.user_a)
        self.assertEqual(
            list(custom_exercise.muscle_groups.all()),
            [self.quadriceps],
        )
        self.assertContains(catalog_response, self.system_exercise.name)
        self.assertContains(catalog_response, "Extensora unilateral · Meu exercício")
        self.assertNotContains(catalog_response, other_users_exercise.name)

        rejected_response = self.client.post(
            reverse(
                "core:add_exercises",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            ),
            {"exercises": [other_users_exercise.pk]},
        )
        self.assertEqual(rejected_response.status_code, 302)
        self.assertFalse(workout_group.workout_exercises.exists())

    def test_user_cannot_manage_another_users_custom_exercise(self):
        exercise = self.create_custom_exercise(user=self.user_b)
        self.client.force_login(self.user_a)

        edit_response = self.client.get(
            reverse(
                "core:personalization_exercise_edit",
                kwargs={"pk": exercise.pk},
            )
        )
        delete_response = self.client.post(
            reverse(
                "core:personalization_exercise_delete",
                kwargs={"pk": exercise.pk},
            )
        )

        self.assertEqual(edit_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)
        self.assertTrue(Exercise.objects.filter(pk=exercise.pk).exists())

    def test_user_creates_preset_with_system_and_custom_exercises(self):
        custom_exercise = self.create_custom_exercise()
        other_users_exercise = self.create_custom_exercise(
            user=self.user_b,
            name="Exercício de outro usuário",
        )
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse("core:personalization_preset_create"),
            {
                "muscle_group": self.quadriceps.pk,
                "name": "Quadríceps principal",
                "exercises": [self.system_exercise.pk, custom_exercise.pk],
            },
        )
        preset = WorkoutPreset.objects.get(name="Quadríceps principal")

        self.assertRedirects(
            response,
            reverse("core:personalization_presets"),
        )
        self.assertEqual(preset.user, self.user_a)
        self.assertEqual(preset.muscle_group, self.quadriceps)
        self.assertEqual(
            set(preset.exercises.values_list("pk", flat=True)),
            {self.system_exercise.pk, custom_exercise.pk},
        )

        invalid_response = self.client.post(
            reverse("core:personalization_preset_create"),
            {
                "muscle_group": self.quadriceps.pk,
                "name": "Predefinição inválida",
                "exercises": [other_users_exercise.pk],
            },
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assertFalse(
            WorkoutPreset.objects.filter(name="Predefinição inválida").exists()
        )

    def test_adding_group_offers_and_loads_owned_preset(self):
        custom_exercise = self.create_custom_exercise()
        preset = self.create_preset(name="Quadríceps completo")
        WorkoutPresetExercise.objects.create(
            preset=preset,
            exercise=self.system_exercise,
            order=1,
        )
        WorkoutPresetExercise.objects.create(
            preset=preset,
            exercise=custom_exercise,
            order=2,
        )
        self.client.force_login(self.user_a)

        add_group_response = self.client.post(
            reverse(
                "core:add_muscle_groups",
                kwargs={"date_str": "2026-08-14"},
            ),
            {"add-muscle_groups": [self.quadriceps.pk]},
        )
        workout_group = WorkoutMuscleGroup.objects.get(
            workout__user=self.user_a,
            muscle_group=self.quadriceps,
        )
        offer_url = reverse(
            "core:workout_group_preset_offer",
            kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
        )

        self.assertRedirects(add_group_response, offer_url)
        offer_response = self.client.get(offer_url)
        self.assertContains(offer_response, "Carregar uma predefinição?")
        self.assertContains(offer_response, preset.name)

        load_response = self.client.post(offer_url, {"preset_id": preset.pk})
        self.assertRedirects(
            load_response,
            reverse(
                "core:muscle_group",
                kwargs={"date_str": "2026-08-14", "pk": workout_group.pk},
            ),
        )
        self.assertEqual(
            list(
                workout_group.workout_exercises.order_by("order").values_list(
                    "exercise_id",
                    flat=True,
                )
            ),
            [self.system_exercise.pk, custom_exercise.pk],
        )

    def test_multiple_group_offers_return_to_workout_after_last_choice(self):
        posterior_exercise = Exercise.objects.create(name="Stiff")
        posterior_exercise.muscle_groups.add(self.posterior)
        quadriceps_preset = self.create_preset(name="Quadríceps A")
        posterior_preset = self.create_preset(
            muscle_group=self.posterior,
            name="Posterior A",
        )
        WorkoutPresetExercise.objects.create(
            preset=quadriceps_preset,
            exercise=self.system_exercise,
            order=1,
        )
        WorkoutPresetExercise.objects.create(
            preset=posterior_preset,
            exercise=posterior_exercise,
            order=1,
        )
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse(
                "core:add_muscle_groups",
                kwargs={"date_str": "2026-08-14"},
            ),
            {"add-muscle_groups": [self.quadriceps.pk, self.posterior.pk]},
        )
        groups = list(
            WorkoutMuscleGroup.objects.filter(workout__user=self.user_a).order_by(
                "order"
            )
        )
        first_offer = reverse(
            "core:workout_group_preset_offer",
            kwargs={"date_str": "2026-08-14", "pk": groups[0].pk},
        )
        second_offer = reverse(
            "core:workout_group_preset_offer",
            kwargs={"date_str": "2026-08-14", "pk": groups[1].pk},
        )

        self.assertRedirects(response, first_offer)
        skip_response = self.client.post(first_offer, {"action": "skip"})
        self.assertRedirects(skip_response, second_offer)
        final_response = self.client.post(
            second_offer,
            {"preset_id": posterior_preset.pk},
        )
        self.assertRedirects(
            final_response,
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"}),
        )
        self.assertEqual(groups[0].workout_exercises.count(), 0)
        self.assertEqual(groups[1].workout_exercises.count(), 1)

    def test_bottom_navigation_places_personalization_between_workouts_and_profile(self):
        self.client.force_login(self.user_a)

        response = self.client.get(reverse("core:personalization"))
        content = response.content.decode()
        bottom_navigation = content.split('<nav class="bottom-nav"', maxsplit=1)[1]

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            bottom_navigation.index("Treinos"),
            bottom_navigation.index("Personalização"),
        )
        self.assertLess(
            bottom_navigation.index("Personalização"),
            bottom_navigation.index("Perfil"),
        )


class SeedGymDataTests(TestCase):
    def test_seed_is_idempotent_and_keeps_multiple_groups(self):
        call_command("seed_gym_data")
        call_command("seed_gym_data")

        expected_exercises = {
            exercise_name
            for exercise_names in CATALOG.values()
            for exercise_name in exercise_names
        }
        self.assertEqual(MuscleGroup.objects.count(), 11)
        self.assertEqual(Exercise.objects.count(), len(expected_exercises))
        self.assertEqual(Exercise.objects.filter(name="Agachamento Livre").count(), 1)
        self.assertEqual(
            Exercise.objects.get(name="Agachamento Livre").muscle_groups.count(),
            2,
        )
        self.assertTrue(Exercise.objects.filter(name="Crossover Alto").exists())
        self.assertTrue(Exercise.objects.filter(name="Crossover Baixo").exists())
        self.assertEqual(
            Exercise.objects.get(name="Supino Fechado").muscle_groups.count(),
            2,
        )
        cardio = MuscleGroup.objects.get(slug="cardio")
        self.assertEqual(cardio.tracking_type, MuscleGroup.TrackingType.CARDIO)
        self.assertEqual(cardio.exercises.count(), 8)

    def test_seeded_groups_have_corresponding_icons(self):
        call_command("seed_gym_data")

        expected_icons = {
            "peito": "rib_cage",
            "costas": "rowing",
            "ombros": "sports_handball",
            "biceps": "fitness_center",
            "triceps": "exercise",
            "quadriceps": "femur",
            "posterior-de-coxa": "femur_alt",
            "gluteos": "skeleton",
            "panturrilhas": "footprint",
            "abdomen": "body_system",
            "cardio": "directions_run",
        }

        self.assertEqual(
            {
                group.slug: group.icon_name
                for group in MuscleGroup.objects.order_by("order")
            },
            expected_icons,
        )

    def test_unknown_strength_group_uses_fallback_icon(self):
        group = MuscleGroup(name="Antebraços", slug="antebracos")

        self.assertEqual(group.icon_name, "fitness_center")


class TrainingEnhancementTests(TestCase):
    workout_date = date(2026, 8, 19)

    def setUp(self):
        self.user = User.objects.create_user("athlete", password="senha-teste-123")
        self.other_user = User.objects.create_user(
            "other-athlete",
            password="senha-teste-123",
        )
        self.strength_group = MuscleGroup.objects.create(
            name="Quadríceps",
            slug="quadriceps-enhancements",
            order=1,
        )
        self.cardio_group = MuscleGroup.objects.get(slug="cardio")
        self.exercises = []
        for name in ("Agachamento", "Leg Press", "Cadeira Extensora"):
            exercise = Exercise.objects.create(name=name)
            exercise.muscle_groups.add(self.strength_group)
            self.exercises.append(exercise)
        self.cardio_exercise = Exercise.objects.get(name="Corrida", user=None)
        self.client.force_login(self.user)

    def create_workout_group(self, group=None, user=None):
        workout = Workout.objects.create(
            user=user or self.user,
            date=self.workout_date,
        )
        return WorkoutMuscleGroup.objects.create(
            workout=workout,
            muscle_group=group or self.strength_group,
            order=1,
        )

    def test_search_and_workout_filters_are_automatic(self):
        workout_group = self.create_workout_group()

        group_response = self.client.get(
            reverse(
                "core:muscle_group",
                kwargs={"date_str": self.workout_date.isoformat(), "pk": workout_group.pk},
            )
        )
        workout_response = self.client.get(reverse("core:workouts"))

        self.assertContains(group_response, "data-live-search")
        self.assertContains(group_response, "data-exercise-results")
        self.assertContains(workout_response, "data-auto-filter")
        self.assertContains(group_response, "core/js/app.js")

    def test_incremental_exercise_search_returns_only_result_fragment(self):
        workout_group = self.create_workout_group()
        group_url = reverse(
            "core:muscle_group",
            kwargs={"date_str": self.workout_date.isoformat(), "pk": workout_group.pk},
        )

        response = self.client.get(
            group_url,
            {"q": "Leg"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["query"], "Leg")
        self.assertIn("Leg Press", response.json()["html"])
        self.assertNotIn("<html", response.json()["html"])
        self.assertNotContains(response, "Seu treino")

    def test_custom_exercises_are_grouped_by_category(self):
        custom_strength = Exercise.objects.create(
            user=self.user,
            name="Extensora unilateral",
        )
        custom_strength.muscle_groups.add(self.strength_group)
        custom_cardio = Exercise.objects.create(
            user=self.user,
            name="Corrida inclinada",
        )
        custom_cardio.muscle_groups.add(self.cardio_group)

        response = self.client.get(reverse("core:personalization"))

        groups = list(response.context["exercise_groups"])
        self.assertEqual(groups, [self.strength_group, self.cardio_group])
        self.assertContains(response, "Extensora unilateral")
        self.assertContains(response, "Corrida inclinada")
        self.assertContains(response, 'class="exercise-groups"')

    def test_cardio_uses_duration_distance_and_perceived_exertion(self):
        workout_group = self.create_workout_group(group=self.cardio_group)
        workout_exercise = WorkoutExercise.objects.create(
            workout_muscle_group=workout_group,
            exercise=self.cardio_exercise,
            order=1,
        )

        response = self.client.post(
            reverse(
                "core:add_set",
                kwargs={
                    "date_str": self.workout_date.isoformat(),
                    "pk": workout_exercise.pk,
                },
            ),
            {
                "duration_minutes": "35",
                "distance_km": "5.20",
                "perceived_exertion": "7",
                "weight_kg": "80",
                "reps": "10",
                "is_working_set": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        exercise_set = ExerciseSet.objects.get(workout_exercise=workout_exercise)
        self.assertEqual(exercise_set.duration_minutes, 35)
        self.assertEqual(str(exercise_set.distance_km), "5.20")
        self.assertEqual(exercise_set.perceived_exertion, 7)
        self.assertIsNone(exercise_set.weight_kg)
        self.assertIsNone(exercise_set.reps)
        self.assertFalse(exercise_set.is_working_set)

        detail = self.client.get(
            reverse(
                "core:workout_exercise",
                kwargs={
                    "date_str": self.workout_date.isoformat(),
                    "pk": workout_exercise.pk,
                },
            )
        )
        self.assertContains(detail, "Duração em minutos")
        self.assertContains(detail, "35 min")
        self.assertContains(detail, "5,2")
        self.assertNotContains(detail, "Peso em kg")

    def test_cardio_duration_is_summarized_on_workout_day(self):
        workout_group = self.create_workout_group(group=self.cardio_group)
        workout_exercise = WorkoutExercise.objects.create(
            workout_muscle_group=workout_group,
            exercise=self.cardio_exercise,
            order=1,
        )
        ExerciseSet.objects.create(
            workout_exercise=workout_exercise,
            order=1,
            duration_minutes=20,
        )
        ExerciseSet.objects.create(
            workout_exercise=workout_exercise,
            order=2,
            duration_minutes=15,
        )

        response = self.client.get(
            reverse(
                "core:workout_day",
                kwargs={"date_str": self.workout_date.isoformat()},
            )
        )

        self.assertContains(response, "35 min registrados")

    def test_user_can_reorder_all_exercises_in_a_group(self):
        workout_group = self.create_workout_group()
        entries = [
            WorkoutExercise.objects.create(
                workout_muscle_group=workout_group,
                exercise=exercise,
                order=order,
            )
            for order, exercise in enumerate(self.exercises, start=1)
        ]
        reorder_url = reverse(
            "core:reorder_exercises",
            kwargs={"date_str": self.workout_date.isoformat(), "pk": workout_group.pk},
        )

        response = self.client.post(
            reorder_url,
            data=json.dumps({"order": [entries[2].pk, entries[0].pk, entries[1].pk]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(
                workout_group.workout_exercises.order_by("order").values_list(
                    "pk",
                    flat=True,
                )
            ),
            [entries[2].pk, entries[0].pk, entries[1].pk],
        )

    def test_reorder_rejects_incomplete_or_foreign_group(self):
        workout_group = self.create_workout_group()
        entry = WorkoutExercise.objects.create(
            workout_muscle_group=workout_group,
            exercise=self.exercises[0],
            order=1,
        )
        reorder_url = reverse(
            "core:reorder_exercises",
            kwargs={"date_str": self.workout_date.isoformat(), "pk": workout_group.pk},
        )

        invalid = self.client.post(
            reorder_url,
            data=json.dumps({"order": []}),
            content_type="application/json",
        )
        self.assertEqual(invalid.status_code, 400)

        self.client.force_login(self.other_user)
        foreign = self.client.post(
            reorder_url,
            data=json.dumps({"order": [entry.pk]}),
            content_type="application/json",
        )
        self.assertEqual(foreign.status_code, 404)

    def test_group_page_can_prefill_and_save_workout_preset(self):
        workout_group = self.create_workout_group()
        entries = [
            WorkoutExercise.objects.create(
                workout_muscle_group=workout_group,
                exercise=exercise,
                order=order,
            )
            for order, exercise in enumerate(self.exercises[:2], start=1)
        ]
        group_url = reverse(
            "core:muscle_group",
            kwargs={"date_str": self.workout_date.isoformat(), "pk": workout_group.pk},
        )

        group_response = self.client.get(group_url)
        preset_url = group_response.context["save_preset_url"]
        self.assertContains(group_response, "Salvar Predefinição de Treino")

        preset_form = self.client.get(preset_url)
        initial_ids = set(preset_form.context["form"]["exercises"].value())
        self.assertEqual(
            initial_ids,
            {entries[0].exercise_id, entries[1].exercise_id},
        )

        save_response = self.client.post(
            reverse("core:personalization_preset_create"),
            {
                "muscle_group": self.strength_group.pk,
                "name": "Treino do dia",
                "exercises": [entry.exercise_id for entry in entries],
                "return_to": group_url,
            },
        )

        self.assertRedirects(save_response, group_url)
        preset = WorkoutPreset.objects.get(user=self.user, name="Treino do dia")
        self.assertEqual(
            set(preset.exercises.values_list("pk", flat=True)),
            {entry.exercise_id for entry in entries},
        )


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
        self.assertContains(response, "Respire um pouco", status_code=429)
        self.assertContains(response, "Voltar ao início", status_code=429)

    def test_authenticated_writes_are_limited_by_user(self):
        user = User.objects.create_user("rate_user", password="senha-teste-123")
        self.client.force_login(user)
        add_group_url = reverse(
            "core:add_muscle_groups",
            kwargs={"date_str": "2026-08-14"},
        )

        self.assertEqual(self.client.post(add_group_url, {}).status_code, 302)
        self.assertEqual(self.client.post(add_group_url, {}).status_code, 302)
        response = self.client.post(add_group_url, {})

        self.assertEqual(response.status_code, 429)

    def test_get_requests_are_not_rate_limited(self):
        user = User.objects.create_user("reader", password="senha-teste-123")
        self.client.force_login(user)
        calendar_url = reverse("core:calendar")

        for _ in range(5):
            response = self.client.get(calendar_url)

        self.assertEqual(response.status_code, 200)

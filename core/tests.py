from datetime import date

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from .management.commands.seed_gym_data import CATALOG
from .models import (
    Exercise,
    ExerciseSet,
    MuscleGroup,
    Workout,
    WorkoutExercise,
    WorkoutMuscleGroup,
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


class SeedGymDataTests(TestCase):
    def test_seed_is_idempotent_and_keeps_multiple_groups(self):
        call_command("seed_gym_data")
        call_command("seed_gym_data")

        expected_exercises = {
            exercise_name
            for exercise_names in CATALOG.values()
            for exercise_name in exercise_names
        }
        self.assertEqual(MuscleGroup.objects.count(), 10)
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

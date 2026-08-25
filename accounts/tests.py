from pathlib import Path

from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from core.models import Exercise, MuscleGroup, Workout, WorkoutExercise


class AccountsViewsTests(TestCase):
    def test_register_template_does_not_disable_autoescaping(self):
        template = Path(
            finders.find("accounts/register.html")
            or Path(__file__).parent / "templates/accounts/register.html"
        ).read_text(encoding="utf-8")

        self.assertNotIn("|safe", template)

    def test_register_creates_and_authenticates_user(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "novo_usuario",
                "email": "novo@example.com",
                "password1": "uma-senha-segura-123",
                "password2": "uma-senha-segura-123",
            },
        )

        self.assertRedirects(response, reverse("core:calendar"))
        self.assertTrue(User.objects.filter(username="novo_usuario").exists())
        self.assertIn("_auth_user_id", self.client.session)

    def test_profile_counts_only_workouts_with_exercises(self):
        user = User.objects.create_user("perfil", password="senha-teste-123")
        group = MuscleGroup.objects.create(name="Perfil", slug="perfil")
        exercise = Exercise.objects.create(
            name="Exercício de perfil", primary_muscle_group=group
        )
        exercise.muscle_groups.add(group)
        empty_workout = Workout.objects.create(user=user, date="2026-08-22")
        filled_workout = Workout.objects.create(user=user, date="2026-08-23")
        WorkoutExercise.objects.create(
            workout=filled_workout,
            exercise=exercise,
            muscle_group=group,
            order=1,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:profile"))

        self.assertEqual(response.context["workout_count"], 1)
        self.assertTrue(Workout.objects.filter(pk=empty_workout.pk).exists())

    def test_user_can_change_password_without_losing_session(self):
        user = User.objects.create_user("troca_senha", password="senha-antiga-123")
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "old_password": "senha-antiga-123",
                "new_password1": "senha-nova-segura-456",
                "new_password2": "senha-nova-segura-456",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("senha-nova-segura-456"))
        self.assertIn("_auth_user_id", self.client.session)

    def test_password_change_rejects_wrong_current_password(self):
        user = User.objects.create_user("senha_invalida", password="senha-antiga-123")
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "old_password": "senha-errada",
                "new_password1": "senha-nova-segura-456",
                "new_password2": "senha-nova-segura-456",
            },
        )

        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.check_password("senha-antiga-123"))

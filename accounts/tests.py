from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class AccountsViewsTests(TestCase):
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

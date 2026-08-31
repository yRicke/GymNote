import json
from datetime import date
from pathlib import Path

from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils.text import slugify

from . import error_views
from .catalog import (
    EXERCISE_GROUPS,
    PRIMARY_GROUP_OVERRIDES,
    RENAMED_SYSTEM_EXERCISES,
    SYSTEM_EXERCISE_NAMES,
)
from .default_presets import DEFAULT_WORKOUT_PRESETS
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

    def test_security_headers_are_enforced(self):
        response = self.client.get(reverse("core:landing"))

        policy = response.headers["Content-Security-Policy"]
        self.assertIn("default-src 'self'", policy)
        self.assertIn("object-src 'none'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")


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

        self.assertContains(
            response,
            '<span class="exercise-choice__name">Agachamento Livre</span>',
        )
        self.assertContains(
            response,
            '<span class="exercise-choice__name">Agachamento unilateral</span>',
        )
        self.assertContains(
            response,
            '<span class="exercise-choice__group">Quadríceps</span>',
        )
        self.assertContains(
            response,
            'aria-label="Exercício pessoal" title="Exercício pessoal">person</span>',
        )
        self.assertNotContains(response, "Meu exercício")
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
        self.assertEqual(
            response.json()["exercises"],
            [
                {
                    "id": self.bench.pk,
                    "name": "Supino Reto",
                    "is_custom": False,
                    "group": "Peito",
                }
            ],
        )
        self.assertNotIn("html", response.json())

    def test_live_search_keeps_user_content_as_json_data(self):
        unsafe_name = '<img src=x onerror="alert(1)">'
        create_exercise(unsafe_name, self.quadriceps, user=self.user)
        url = reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})

        response = self.client.get(
            url, {"q": "onerror"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exercises"][0]["name"], unsafe_name)
        javascript = Path(finders.find("core/js/app.js")).read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", javascript)
        self.assertIn("name.textContent = exercise.name", javascript)

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

    def test_workout_filters_render_in_modal_without_automatic_submission(self):
        response = self.client.get(reverse("core:workouts"))

        self.assertContains(response, 'data-dialog-open="workout-filter-dialog"')
        self.assertContains(response, 'id="workout-filter-dialog"')
        self.assertContains(response, 'name="date"')
        self.assertContains(response, 'type="date"')
        self.assertContains(response, "Salvar filtros")
        self.assertContains(response, 'data-reset-dialog-form')
        self.assertNotContains(response, 'data-auto-filter')

    def test_workout_list_filters_by_date(self):
        first, _ = self.create_entry()
        second = Workout.objects.create(user=self.user, date=date(2026, 8, 15))
        WorkoutExercise.objects.create(
            workout=second,
            exercise=self.bench,
            muscle_group=self.chest,
            order=1,
        )

        response = self.client.get(
            reverse("core:workouts"), {"date": "2026-08-15"}
        )

        self.assertEqual(response.context["workouts"], [second])
        self.assertNotIn(first, response.context["workouts"])
        self.assertEqual(response.context["selected_date"], date(2026, 8, 15))
        self.assertTrue(response.context["has_filters"])
        self.assertEqual(response.context["selected_filter_count"], 1)
        self.assertContains(response, "15/08/2026")

    def test_workout_list_combines_date_and_group_only_after_request(self):
        first, _ = self.create_entry()
        second = Workout.objects.create(user=self.user, date=date(2026, 8, 15))
        WorkoutExercise.objects.create(
            workout=second,
            exercise=self.bench,
            muscle_group=self.chest,
            order=1,
        )

        matching = self.client.get(
            reverse("core:workouts"),
            {"date": "2026-08-15", "muscle_groups": [self.chest.pk]},
        )
        non_matching = self.client.get(
            reverse("core:workouts"),
            {"date": "2026-08-15", "muscle_groups": [self.quadriceps.pk]},
        )

        self.assertEqual(matching.context["workouts"], [second])
        self.assertNotIn(first, matching.context["workouts"])
        self.assertEqual(matching.context["selected_filter_count"], 2)
        self.assertContains(matching, "Peito")
        self.assertEqual(non_matching.context["workouts"], [])
        self.assertContains(non_matching, "Nenhum treino encontrado")

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

    def test_calendar_explains_that_days_open_workouts(self):
        response = self.client.get(
            reverse("core:calendar"), {"year": 2026, "month": 8}
        )

        self.assertContains(response, 'class="calendar-hint"')
        self.assertContains(
            response,
            "Clique ou toque em um dia para abrir ou registrar um treino.",
        )

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

    def test_reordered_exercises_keep_their_visual_order_after_reload(self):
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

        reorder_response = self.client.post(
            reverse("core:reorder_exercises", kwargs={"date_str": "2026-08-14"}),
            data=json.dumps({"order": [second.pk, first.pk]}),
            content_type="application/json",
        )
        reloaded_page = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )
        rendered_entries = list(reloaded_page.context["added_exercises"])
        html = reloaded_page.content.decode()

        self.assertEqual(reorder_response.status_code, 200)
        self.assertEqual(
            [entry.pk for entry in rendered_entries],
            [second.pk, first.pk],
        )
        self.assertLess(html.index(self.bench.name), html.index(self.squat.name))

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

    def test_mobile_reorder_handle_blocks_native_text_selection(self):
        self.create_entry()
        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )
        css = Path(finders.find("core/css/app.css")).read_text(encoding="utf-8")
        javascript = Path(finders.find("core/js/sortable-list.js")).read_text(
            encoding="utf-8"
        )
        application_javascript = Path(finders.find("core/js/app.js")).read_text(
            encoding="utf-8"
        )
        html = response.content.decode()

        self.assertContains(response, 'aria-hidden="true" draggable="false"')
        self.assertIn("-webkit-touch-callout: none", css)
        self.assertIn(".sortable-placeholder", css)
        self.assertIn('list.addEventListener("contextmenu"', javascript)
        self.assertIn('list.addEventListener("selectstart"', javascript)
        self.assertIn('item.draggable = false', javascript)
        self.assertIn("activationDistance", javascript)
        self.assertIn("updateAutoScroll", javascript)
        self.assertIn("cloneNode", javascript)
        self.assertIn("onOrderChange = () => {}", javascript)
        self.assertIn("this.onOrderChange(this.items(), item", javascript)
        self.assertNotIn("this.onChange", javascript)
        self.assertNotIn("dataTransfer", javascript)
        self.assertNotIn("setPointerCapture", javascript)
        self.assertEqual(application_javascript.count("window.GymNoteSortable.create"), 2)
        self.assertLess(html.index("sortable-list.js"), html.index("app.js"))

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

    def test_exercise_detail_exposes_lazy_previous_workout_dialog(self):
        _, entry = self.create_entry()
        previous_workout = Workout.objects.create(
            user=self.user,
            date=date(2026, 8, 1),
        )
        previous_entry = WorkoutExercise.objects.create(
            workout=previous_workout,
            exercise=self.squat,
            muscle_group=self.quadriceps,
            order=1,
        )
        ExerciseSet.objects.create(
            workout_exercise=previous_entry,
            order=1,
            weight_kg="123.45",
            reps=5,
            is_working_set=True,
        )
        history_url = reverse(
            "core:previous_workout_summary",
            kwargs={"date_str": "2026-08-14", "pk": entry.pk},
        )

        response = self.client.get(
            reverse(
                "core:workout_exercise",
                kwargs={"date_str": "2026-08-14", "pk": entry.pk},
            )
        )

        self.assertContains(response, 'data-dialog-open="previous-workout-dialog"')
        self.assertContains(response, f'data-previous-workout-url="{history_url}"')
        self.assertContains(response, "Ver último treino")
        self.assertContains(response, 'id="previous-workout-dialog"', count=1)
        self.assertContains(
            response,
            '<table class="sets-table previous-workout-table">',
        )
        self.assertNotContains(response, "123,45 kg")
        javascript = Path(finders.find("core/js/app.js")).read_text(encoding="utf-8")
        css = Path(finders.find("core/css/app.css")).read_text(encoding="utf-8")
        self.assertIn("previousWorkoutTrigger.addEventListener", javascript)
        self.assertIn("previousWorkoutLoaded", javascript)
        self.assertIn('row.classList.add("is-working")', javascript)
        self.assertIn("working-mark previous-working-mark", javascript)
        self.assertIn('"set-number"', javascript)
        self.assertIn(
            "grid-template-columns: repeat(3, minmax(0, 1fr))",
            css,
        )

    def test_previous_workout_summary_uses_latest_entry_with_sets(self):
        _, current_entry = self.create_entry()

        previous_workout = Workout.objects.create(
            user=self.user,
            date=date(2026, 8, 1),
        )
        previous_entry = WorkoutExercise.objects.create(
            workout=previous_workout,
            exercise=self.squat,
            muscle_group=self.quadriceps,
            order=1,
        )
        ExerciseSet.objects.bulk_create(
            [
                ExerciseSet(
                    workout_exercise=previous_entry,
                    order=1,
                    weight_kg=120,
                    reps=2,
                    is_working_set=False,
                ),
                ExerciseSet(
                    workout_exercise=previous_entry,
                    order=2,
                    weight_kg=80,
                    reps=10,
                    is_working_set=True,
                ),
                ExerciseSet(
                    workout_exercise=previous_entry,
                    order=3,
                    weight_kg=90,
                    reps=8,
                    partial_reps=1,
                    is_working_set=True,
                ),
            ]
        )

        blank_workout = Workout.objects.create(
            user=self.user,
            date=date(2026, 8, 10),
        )
        WorkoutExercise.objects.create(
            workout=blank_workout,
            exercise=self.squat,
            muscle_group=self.quadriceps,
            order=1,
        )

        other_exercise_workout = Workout.objects.create(
            user=self.user,
            date=date(2026, 8, 12),
        )
        other_exercise_entry = WorkoutExercise.objects.create(
            workout=other_exercise_workout,
            exercise=self.bench,
            muscle_group=self.chest,
            order=1,
        )
        ExerciseSet.objects.create(
            workout_exercise=other_exercise_entry,
            order=1,
            weight_kg=150,
            reps=5,
            is_working_set=True,
        )

        foreign_workout = Workout.objects.create(
            user=self.other_user,
            date=date(2026, 8, 13),
        )
        foreign_entry = WorkoutExercise.objects.create(
            workout=foreign_workout,
            exercise=self.squat,
            muscle_group=self.quadriceps,
            order=1,
        )
        ExerciseSet.objects.create(
            workout_exercise=foreign_entry,
            order=1,
            weight_kg=200,
            reps=5,
            is_working_set=True,
        )

        response = self.client.get(
            reverse(
                "core:previous_workout_summary",
                kwargs={"date_str": "2026-08-14", "pk": current_entry.pk},
            )
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["has_history"])
        self.assertEqual(data["date"], "2026-08-01")
        self.assertEqual(data["relative_label"], "Há 1 semana")
        self.assertEqual(
            data["summary_items"],
            [
                {"label": "Feeder set", "value": "120 kg × 2 reps"},
                {"label": "Work set", "value": "80 kg × 10 reps"},
                {"label": "Top set", "value": "90 kg × 8 reps"},
            ],
        )
        self.assertEqual([item["order"] for item in data["sets"]], [1, 2, 3])
        self.assertEqual(data["sets"][2]["partial_reps"], 1)

    def test_previous_workout_summary_reports_empty_history(self):
        _, current_entry = self.create_entry()
        ExerciseSet.objects.create(
            workout_exercise=current_entry,
            order=1,
            weight_kg=80,
            reps=8,
        )

        response = self.client.get(
            reverse(
                "core:previous_workout_summary",
                kwargs={"date_str": "2026-08-14", "pk": current_entry.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "has_history": False,
                "message": "Nenhuma série anterior encontrada para este exercício.",
            },
        )

    def test_previous_cardio_summary_adapts_metrics_and_rows(self):
        workout = Workout.objects.create(user=self.user, date=self.workout_date)
        current_entry = WorkoutExercise.objects.create(
            workout=workout,
            exercise=self.run,
            muscle_group=self.cardio,
            order=1,
        )
        previous_workout = Workout.objects.create(
            user=self.user,
            date=date(2026, 8, 7),
        )
        previous_entry = WorkoutExercise.objects.create(
            workout=previous_workout,
            exercise=self.run,
            muscle_group=self.cardio,
            order=1,
        )
        ExerciseSet.objects.create(
            workout_exercise=previous_entry,
            order=1,
            duration_minutes=20,
            distance_km="3.25",
            perceived_exertion=6,
        )
        ExerciseSet.objects.create(
            workout_exercise=previous_entry,
            order=2,
            duration_minutes=10,
            perceived_exertion=8,
        )

        response = self.client.get(
            reverse(
                "core:previous_workout_summary",
                kwargs={"date_str": "2026-08-14", "pk": current_entry.pk},
            )
        )
        data = response.json()

        self.assertTrue(data["is_cardio"])
        self.assertEqual(data["relative_label"], "Há 1 semana")
        self.assertEqual(
            data["summary_items"],
            [
                {"label": "Duração total", "value": "30 min"},
                {"label": "Distância total", "value": "3,25 km"},
                {"label": "Esforço médio", "value": "7/10"},
            ],
        )
        self.assertEqual(len(data["sets"]), 2)

    def test_previous_workout_summary_checks_owner_and_date(self):
        _, foreign_entry = self.create_entry(user=self.other_user)
        _, owned_entry = self.create_entry()
        foreign_url = reverse(
            "core:previous_workout_summary",
            kwargs={"date_str": "2026-08-14", "pk": foreign_entry.pk},
        )

        foreign_response = self.client.get(foreign_url)
        wrong_date_response = self.client.get(
            reverse(
                "core:previous_workout_summary",
                kwargs={"date_str": "2026-08-13", "pk": owned_entry.pk},
            )
        )

        self.assertEqual(foreign_response.status_code, 404)
        self.assertEqual(wrong_date_response.status_code, 404)

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

    def test_set_deletion_is_available_inside_edit_modal_and_returns_json(self):
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

        self.assertContains(page, 'class="set-identity"')
        self.assertContains(page, 'class="set-edit-button"')
        self.assertContains(page, 'data-nested-dialog-open="delete-dialog"')
        self.assertContains(page, 'data-set-delete')
        self.assertContains(page, f'data-delete-url="{url}"')
        self.assertContains(page, "Excluir série 1?")
        self.assertNotContains(page, 'data-dialog-open="delete-dialog"')
        html = page.content.decode()
        self.assertLess(html.index('class="set-edit-button"'), html.index('class="set-number"'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Série excluída.")
        self.assertFalse(ExerciseSet.objects.filter(pk=exercise_set.pk).exists())

    def test_set_add_and_edit_share_the_standard_dialog(self):
        _, entry = self.create_entry()
        exercise_set = ExerciseSet.objects.create(
            workout_exercise=entry,
            order=1,
            weight_kg=80,
            reps=8,
            is_working_set=True,
        )
        add_url = reverse(
            "core:add_set",
            kwargs={"date_str": "2026-08-14", "pk": entry.pk},
        )
        edit_url = reverse("core:edit_set", kwargs={"pk": exercise_set.pk})

        response = self.client.get(
            reverse(
                "core:workout_exercise",
                kwargs={"date_str": "2026-08-14", "pk": entry.pk},
            )
        )

        self.assertContains(response, 'id="set-form-dialog"', count=1)
        self.assertContains(response, 'data-set-form-mode="add"')
        self.assertContains(response, 'data-set-form-mode="edit"')
        self.assertContains(response, f'data-set-action="{add_url}"')
        self.assertContains(response, f'data-set-action="{edit_url}"')
        self.assertContains(response, 'data-dialog-form data-set-form')
        self.assertContains(response, 'class="set-form-dialog__actions"')
        self.assertContains(response, 'data-nested-dialog-open="delete-dialog" hidden')
        self.assertNotContains(response, 'class="content-section panel set-entry"')
        javascript = Path(finders.find("core/js/app.js")).read_text(encoding="utf-8")
        self.assertIn("configureSetDialog(dialog, opener)", javascript)
        self.assertIn("configureDeleteDialog(childDialog, opener)", javascript)
        self.assertIn("exerciseSetValues[opener.dataset.setId]", javascript)
        self.assertEqual(
            response.context["exercise_set_values"][str(exercise_set.pk)],
            {
                "weight_kg": "80.00",
                "reps": 8,
                "partial_reps": "",
                "duration_minutes": "",
                "distance_km": "",
                "perceived_exertion": "",
                "is_working_set": True,
            },
        )

    def test_edit_set_link_opens_prefilled_modal_in_exercise_page(self):
        _, entry = self.create_entry()
        exercise_set = ExerciseSet.objects.create(
            workout_exercise=entry,
            order=1,
            weight_kg=72.5,
            reps=10,
        )

        response = self.client.get(
            reverse("core:edit_set", kwargs={"pk": exercise_set.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/workout_exercise.html")
        self.assertContains(response, "data-dialog-auto-open")
        self.assertContains(
            response,
            f'action="{reverse("core:edit_set", kwargs={"pk": exercise_set.pk})}"',
        )
        self.assertContains(response, 'data-set-delete')
        self.assertContains(response, 'data-nested-dialog-open="delete-dialog"')
        self.assertContains(
            response,
            f'data-delete-url="{reverse("core:delete_set", kwargs={"pk": exercise_set.pk})}"',
        )
        self.assertNotContains(response, 'data-nested-dialog-open="delete-dialog" hidden')
        self.assertEqual(response.context["editing_set"], exercise_set)
        self.assertEqual(response.context["set_form"].instance, exercise_set)

    def test_set_modal_create_and_edit_return_json(self):
        _, entry = self.create_entry()
        add_url = reverse(
            "core:add_set",
            kwargs={"date_str": "2026-08-14", "pk": entry.pk},
        )

        created = self.client.post(
            add_url,
            {"weight_kg": "80", "reps": "8", "is_working_set": "on"},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        exercise_set = entry.sets.get()
        edited = self.client.post(
            reverse("core:edit_set", kwargs={"pk": exercise_set.pk}),
            {"weight_kg": "82.5", "reps": "6"},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["set_id"], exercise_set.pk)
        self.assertEqual(edited.status_code, 200)
        self.assertTrue(edited.json()["ok"])
        exercise_set.refresh_from_db()
        self.assertEqual(str(exercise_set.weight_kg), "82.50")
        self.assertEqual(exercise_set.reps, 6)
        self.assertFalse(exercise_set.is_working_set)

    def test_invalid_set_submission_keeps_validation_in_open_modal(self):
        _, entry = self.create_entry()
        url = reverse(
            "core:add_set",
            kwargs={"date_str": "2026-08-14", "pk": entry.pk},
        )

        json_response = self.client.post(
            url,
            {"weight_kg": "-1", "reps": "8"},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        html_response = self.client.post(
            url,
            {"weight_kg": "-1", "reps": "8"},
        )

        self.assertEqual(json_response.status_code, 400)
        self.assertIn("weight_kg", json_response.json()["errors"])
        self.assertEqual(html_response.status_code, 400)
        self.assertTemplateUsed(html_response, "core/workout_exercise.html")
        self.assertContains(html_response, "data-dialog-auto-open", status_code=400)
        self.assertContains(html_response, "Certifique-se que este valor", status_code=400)

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

        cardio_page = self.client.get(
            reverse(
                "core:workout_exercise",
                kwargs={"date_str": "2026-08-14", "pk": cardio_entry.pk},
            )
        )
        self.assertContains(cardio_page, 'data-set-title="Adicionar registro"')
        self.assertContains(cardio_page, 'name="duration_minutes"')
        self.assertNotContains(cardio_page, 'name="weight_kg"')


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
        self.assertEqual(success.json()["exercise"]["id"], exercise.pk)
        self.assertEqual(success.json()["exercise"]["name"], exercise.name)
        self.assertTrue(success.json()["exercise"]["is_custom"])
        self.assertEqual(success.json()["exercise"]["group"]["id"], self.chest.pk)
        self.assertEqual(
            success.json()["exercise"]["label"],
            "Crucifixo no cabo · Peito · Meu exercício",
        )
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
        self.assertContains(response, 'data-dialog-open="exercise-catalog-dialog"')
        self.assertContains(response, 'id="exercise-catalog-dialog"')
        self.assertContains(response, 'data-catalog-mode="preset"')
        self.assertContains(response, 'data-catalog-search')
        self.assertContains(response, 'placeholder="Buscar exercício por nome..."')
        self.assertContains(response, 'data-preset-selected-count')
        self.assertContains(response, 'data-preset-selected-list')
        self.assertContains(response, 'data-catalog-confirm')
        self.assertContains(response, 'data-nested-dialog-open="create-exercise-dialog"')
        self.assertContains(response, self.system_chest.name)
        self.assertContains(response, self.system_triceps.name)

    def test_edit_preset_renders_search_and_keeps_current_selections(self):
        preset = self.create_preset(
            entries=[self.system_triceps, self.system_chest]
        )

        response = self.client.get(
            reverse("core:personalization_preset_edit", kwargs={"pk": preset.pk})
        )

        self.assertContains(response, 'data-catalog-search')
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
        self.assertContains(
            response,
            f'data-selected-exercise-id="{self.system_triceps.pk}"',
        )
        self.assertContains(
            response,
            f'data-selected-exercise-id="{self.system_chest.pk}"',
        )

    def test_selected_preset_exercises_render_tags_remove_and_reorder_controls(self):
        custom = self.create_custom()
        preset = self.create_preset(entries=[self.system_triceps, custom])

        response = self.client.get(
            reverse("core:personalization_preset_edit", kwargs={"pk": preset.pk})
        )

        self.assertContains(response, 'class="exercise-choice__group"')
        self.assertContains(response, 'data-selected-exercise-group="Tríceps"')
        self.assertContains(response, 'data-selected-exercise-custom="true"')
        self.assertContains(response, 'aria-label="Exercício pessoal"', count=2)
        self.assertContains(response, "data-remove-selected-exercise", count=2)
        self.assertContains(response, 'class="drag-handle icon-button"', count=2)
        self.assertContains(response, 'draggable="false"')
        self.assertContains(response, "data-preset-selection-status")

    def test_edit_preset_removes_exercise_and_saves_new_order(self):
        custom = self.create_custom()
        preset = self.create_preset(
            entries=[self.system_chest, self.system_triceps, custom]
        )

        response = self.client.post(
            reverse("core:personalization_preset_edit", kwargs={"pk": preset.pk}),
            {
                "name": preset.name,
                "exercises": [self.system_chest.pk, custom.pk],
                "exercise_order": f"{custom.pk},{self.system_chest.pk}",
            },
        )

        self.assertRedirects(response, reverse("core:personalization_presets"))
        self.assertEqual(
            list(
                preset.exercise_entries.order_by("order").values_list(
                    "exercise_id", flat=True
                )
            ),
            [custom.pk, self.system_chest.pk],
        )

    def test_invalid_preset_rerenders_submitted_selection_and_order(self):
        response = self.client.post(
            reverse("core:personalization_preset_create"),
            {
                "name": "",
                "exercises": [self.system_triceps.pk, self.system_chest.pk],
                "exercise_order": f"{self.system_chest.pk},{self.system_triceps.pk}",
            },
        )

        rows = response.context["form"].selected_exercise_rows
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["exercise"].pk for row in rows],
            [self.system_chest.pk, self.system_triceps.pk],
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
        self.assertEqual(
            form_response.context["form"].selected_exercise_rows[0]["muscle_group"],
            self.triceps,
        )
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
        self.assertContains(response, 'data-dialog-open="exercise-catalog-dialog"')
        self.assertContains(response, 'id="exercise-catalog-dialog"')
        self.assertContains(response, 'data-catalog-mode="workout"')
        self.assertContains(response, '<dialog class="preset-dialog', count=5)
        self.assertContains(response, "1 exercício")
        self.assertContains(response, "1 grupo")
        self.assertContains(response, 'name="preset_id"')
        self.assertContains(response, 'aria-label="Novo exercício"')
        self.assertNotContains(response, "playlist_add_check")

    def test_workout_day_hides_quick_actions_when_their_resources_are_absent(self):
        response = self.client.get(
            reverse("core:workout_day", kwargs={"date_str": "2026-08-14"})
        )

        self.assertContains(response, 'data-dialog-open="exercise-catalog-dialog"')
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


class SeedGymDataTests(TransactionTestCase):
    def test_seed_creates_catalog_and_primary_groups_idempotently(self):
        call_command("seed_gym_data")
        call_command("seed_gym_data")

        self.assertEqual(MuscleGroup.objects.count(), len(CATALOG))
        expected_exercises = {name for names in CATALOG.values() for name in names}
        self.assertEqual(len(expected_exercises), 74)
        self.assertEqual(Exercise.objects.count(), len(expected_exercises))
        squat = Exercise.objects.get(name="Agachamento Livre")
        bench = Exercise.objects.get(name="Supino Fechado")
        face_pull = Exercise.objects.get(name="Face Pull")
        self.assertEqual(squat.primary_muscle_group.name, "Quadríceps")
        self.assertEqual(bench.primary_muscle_group.name, "Tríceps")
        self.assertEqual(face_pull.primary_muscle_group.name, "Ombros")
        self.assertEqual(squat.muscle_groups.count(), 2)
        self.assertEqual(bench.muscle_groups.count(), 2)
        self.assertEqual(face_pull.muscle_groups.count(), 2)
        self.assertFalse(
            Exercise.objects.filter(name="Supino Declinado com Barra").exists()
        )
        self.assertEqual(
            Exercise.objects.filter(primary_muscle_group__name="Cardio").count(),
            8,
        )


class DefaultWorkoutPresetTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        call_command("seed_gym_data")
        self.user = User.objects.create_user(
            "starter_presets",
            password="senha-teste-123",
        )

    def test_new_user_receives_three_ordered_default_presets(self):
        presets = WorkoutPreset.objects.filter(user=self.user)

        self.assertEqual(presets.count(), 3)
        self.assertEqual(
            set(presets.values_list("name", flat=True)),
            {preset_data["name"] for preset_data in DEFAULT_WORKOUT_PRESETS},
        )
        for preset_data in DEFAULT_WORKOUT_PRESETS:
            entries = list(
                presets.get(name=preset_data["name"])
                .exercise_entries.select_related("exercise")
                .order_by("order")
            )
            self.assertEqual(
                [entry.exercise.name for entry in entries],
                list(preset_data["exercises"]),
            )
            self.assertEqual(
                [entry.order for entry in entries],
                list(range(1, len(entries) + 1)),
            )
            self.assertTrue(
                all(
                    entry.muscle_group_id
                    == entry.exercise.primary_muscle_group_id
                    for entry in entries
                )
            )

    def test_default_preset_can_be_deleted_without_being_recreated(self):
        preset = WorkoutPreset.objects.filter(user=self.user).first()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "core:personalization_preset_delete",
                kwargs={"pk": preset.pk},
            )
        )

        self.assertRedirects(response, reverse("core:personalization_presets"))
        self.assertFalse(WorkoutPreset.objects.filter(pk=preset.pk).exists())
        self.user.save()
        self.assertEqual(WorkoutPreset.objects.filter(user=self.user).count(), 2)


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

        UserModel.objects.all().delete()
        ExerciseOld.objects.all().delete()
        MuscleGroupOld.objects.all().delete()

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


class DefaultWorkoutPresetMigrationTests(TransactionTestCase):
    migrate_from = [("core", "0008_daily_workout_flow")]
    migrate_to = [("core", "0009_create_default_workout_presets")]

    exercise_groups = {
        "Supino Reto com Barra": "Peito",
        "Supino Inclinado com Halteres": "Peito",
        "Peck Deck": "Peito",
        "Desenvolvimento com Halteres": "Ombros",
        "Elevação Lateral": "Ombros",
        "Tríceps Corda": "Tríceps",
        "Puxada Alta": "Costas",
        "Remada Baixa": "Costas",
        "Remada Unilateral": "Costas",
        "Face Pull": "Costas",
        "Rosca Direta": "Bíceps",
        "Rosca Martelo": "Bíceps",
        "Agachamento Livre": "Quadríceps",
        "Leg Press": "Quadríceps",
        "Cadeira Extensora": "Quadríceps",
        "Stiff": "Posterior de Coxa",
        "Mesa Flexora": "Posterior de Coxa",
        "Panturrilha em Pé": "Panturrilhas",
    }
    legacy_presets = (
        (
            "Treino A — Peito, ombros e tríceps",
            (
                "Supino Reto com Barra",
                "Supino Inclinado com Halteres",
                "Peck Deck",
                "Desenvolvimento com Halteres",
                "Elevação Lateral",
                "Tríceps Corda",
            ),
        ),
        (
            "Treino B — Costas e bíceps",
            (
                "Puxada Alta",
                "Remada Baixa",
                "Remada Unilateral",
                "Face Pull",
                "Rosca Direta",
                "Rosca Martelo",
            ),
        ),
        (
            "Treino C — Pernas",
            (
                "Agachamento Livre",
                "Leg Press",
                "Cadeira Extensora",
                "Stiff",
                "Mesa Flexora",
                "Panturrilha em Pé",
            ),
        ),
    )

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        UserModel = old_apps.get_model("auth", "User")
        MuscleGroupOld = old_apps.get_model("core", "MuscleGroup")
        ExerciseOld = old_apps.get_model("core", "Exercise")

        UserModel.objects.all().delete()
        ExerciseOld.objects.all().delete()
        MuscleGroupOld.objects.all().delete()

        self.user_id = UserModel.objects.create(username="existing_user").pk
        groups = {}
        for order, group_name in enumerate(
            dict.fromkeys(self.exercise_groups.values()), start=1
        ):
            groups[group_name] = MuscleGroupOld.objects.create(
                name=group_name,
                slug=f"default-group-{order}",
                order=order,
            )
        for exercise_name, group_name in self.exercise_groups.items():
            ExerciseOld.objects.create(
                name=exercise_name,
                primary_muscle_group=groups[group_name],
            )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def test_migration_adds_defaults_to_existing_users(self):
        Preset = self.apps.get_model("core", "WorkoutPreset")
        presets = Preset.objects.filter(user_id=self.user_id)

        self.assertEqual(presets.count(), 3)
        for preset_name, exercise_names in self.legacy_presets:
            entries = presets.get(name=preset_name).exercise_entries.select_related(
                "exercise"
            ).order_by("order")
            self.assertEqual(
                list(entries.values_list("exercise__name", flat=True)),
                list(exercise_names),
            )
            self.assertTrue(
                all(
                    entry.muscle_group_id
                    == entry.exercise.primary_muscle_group_id
                    for entry in entries
                )
            )


class ReducedCatalogMigrationTests(TransactionTestCase):
    migrate_from = [("core", "0009_create_default_workout_presets")]
    migrate_to = [("core", "0011_update_default_workout_presets")]

    legacy_primary_groups = {
        "Supino Reto com Barra": "Peito",
        "Supino Inclinado com Halteres": "Peito",
        "Peck Deck": "Peito",
        "Desenvolvimento com Halteres": "Ombros",
        "Elevação Lateral": "Ombros",
        "Tríceps Corda": "Tríceps",
        "Puxada Alta": "Costas",
        "Remada Baixa": "Costas",
        "Remada Unilateral": "Costas",
        "Face Pull": "Costas",
        "Rosca Direta": "Bíceps",
        "Rosca Martelo": "Bíceps",
        "Agachamento Livre": "Quadríceps",
        "Leg Press": "Quadríceps",
        "Cadeira Extensora": "Quadríceps",
        "Stiff": "Posterior de Coxa",
        "Mesa Flexora": "Posterior de Coxa",
        "Panturrilha em Pé": "Panturrilhas",
        "Crucifixo": "Peito",
        "Crossover": "Peito",
        "Remada Curvada": "Costas",
        "Remada na Máquina": "Costas",
        "Desenvolvimento na Máquina": "Ombros",
        "Tríceps Barra": "Tríceps",
        "Tríceps Unilateral na Polia": "Tríceps",
        "Búlgaro": "Quadríceps",
        "Panturrilha Sentado": "Panturrilhas",
        "Panturrilha Unilateral em Pé": "Panturrilhas",
        "Abdominal Crunch": "Abdômen",
        "Abdução de Quadril na Máquina": "Glúteos",
        "Supino Declinado com Barra": "Peito",
        "Crossover Alto": "Peito",
    }
    legacy_presets = (
        (
            "Treino A — Peito, ombros e tríceps",
            (
                "Supino Reto com Barra",
                "Supino Inclinado com Halteres",
                "Peck Deck",
                "Desenvolvimento com Halteres",
                "Elevação Lateral",
                "Tríceps Corda",
            ),
        ),
        (
            "Treino B — Costas e bíceps",
            (
                "Puxada Alta",
                "Remada Baixa",
                "Remada Unilateral",
                "Face Pull",
                "Rosca Direta",
                "Rosca Martelo",
            ),
        ),
        (
            "Treino C — Pernas",
            (
                "Agachamento Livre",
                "Leg Press",
                "Cadeira Extensora",
                "Stiff",
                "Mesa Flexora",
                "Panturrilha em Pé",
            ),
        ),
    )

    def create_preset(self, Preset, PresetEntry, user_id, name, exercise_names):
        preset = Preset.objects.create(user_id=user_id, name=name)
        for order, exercise_name in enumerate(exercise_names, start=1):
            exercise = self.old_exercises[exercise_name]
            PresetEntry.objects.create(
                preset=preset,
                exercise=exercise,
                muscle_group_id=exercise.primary_muscle_group_id,
                order=order,
            )
        return preset

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        UserModel = old_apps.get_model("auth", "User")
        MuscleGroupOld = old_apps.get_model("core", "MuscleGroup")
        ExerciseOld = old_apps.get_model("core", "Exercise")
        WorkoutOld = old_apps.get_model("core", "Workout")
        WorkoutExerciseOld = old_apps.get_model("core", "WorkoutExercise")
        ExerciseSetOld = old_apps.get_model("core", "ExerciseSet")
        PresetOld = old_apps.get_model("core", "WorkoutPreset")
        PresetEntryOld = old_apps.get_model("core", "WorkoutPresetExercise")

        UserModel.objects.all().delete()
        ExerciseOld.objects.all().delete()
        MuscleGroupOld.objects.all().delete()

        self.groups = {}
        for order, group_name in enumerate(CATALOG, start=1):
            self.groups[group_name] = MuscleGroupOld.objects.create(
                name=group_name,
                slug=slugify(group_name),
                order=order,
                tracking_type="cardio" if group_name == "Cardio" else "strength",
            )

        self.old_exercises = {}
        for exercise_name, group_name in self.legacy_primary_groups.items():
            exercise = ExerciseOld.objects.create(
                name=exercise_name,
                primary_muscle_group=self.groups[group_name],
            )
            exercise.muscle_groups.add(self.groups[group_name])
            self.old_exercises[exercise_name] = exercise
        self.old_exercises["Face Pull"].muscle_groups.add(self.groups["Ombros"])
        self.old_exercises["Agachamento Livre"].muscle_groups.add(
            self.groups["Glúteos"]
        )

        user = UserModel.objects.create(username="catalog_user")
        other_user = UserModel.objects.create(username="other_catalog_user")
        self.user_id = user.pk
        self.other_user_id = other_user.pk

        self.user_legacy_preset_ids = []
        for preset_name, exercise_names in self.legacy_presets:
            preset = self.create_preset(
                PresetOld,
                PresetEntryOld,
                user.pk,
                preset_name,
                exercise_names,
            )
            self.user_legacy_preset_ids.append(preset.pk)

        conflicting_push = self.create_preset(
            PresetOld,
            PresetEntryOld,
            other_user.pk,
            "Push",
            ("Puxada Alta",),
        )
        self.conflicting_push_id = conflicting_push.pk
        conflicting_legacy = self.create_preset(
            PresetOld,
            PresetEntryOld,
            other_user.pk,
            self.legacy_presets[0][0],
            self.legacy_presets[0][1],
        )
        self.conflicting_legacy_id = conflicting_legacy.pk
        edited_legacy = self.create_preset(
            PresetOld,
            PresetEntryOld,
            other_user.pk,
            self.legacy_presets[1][0],
            self.legacy_presets[1][1][:-1],
        )
        self.edited_legacy_id = edited_legacy.pk

        stale_exercise = self.old_exercises["Supino Declinado com Barra"]
        personal_exercise = ExerciseOld.objects.create(
            user=user,
            name=stale_exercise.name,
            primary_muscle_group=self.groups["Peito"],
        )
        personal_exercise.muscle_groups.add(self.groups["Peito"])
        self.personal_exercise_id = personal_exercise.pk

        workout = WorkoutOld.objects.create(user=user, date=date(2026, 8, 20))
        personal_entry = WorkoutExerciseOld.objects.create(
            workout=workout,
            exercise=personal_exercise,
            muscle_group=self.groups["Peito"],
            order=1,
        )
        ExerciseSetOld.objects.create(
            workout_exercise=personal_entry,
            order=1,
            reps=10,
            is_working_set=True,
        )
        stale_entry = WorkoutExerciseOld.objects.create(
            workout=workout,
            exercise=stale_exercise,
            muscle_group=self.groups["Peito"],
            order=2,
        )
        ExerciseSetOld.objects.create(
            workout_exercise=stale_entry,
            order=1,
            reps=8,
            is_working_set=True,
        )
        self.workout_id = workout.pk

        personal_preset = PresetOld.objects.create(
            user=user,
            name="Combinação pessoal",
        )
        PresetEntryOld.objects.create(
            preset=personal_preset,
            exercise=personal_exercise,
            muscle_group=self.groups["Peito"],
            order=1,
        )
        PresetEntryOld.objects.create(
            preset=personal_preset,
            exercise=stale_exercise,
            muscle_group=self.groups["Peito"],
            order=2,
        )
        self.personal_preset_id = personal_preset.pk

        other_workout = WorkoutOld.objects.create(
            user=other_user,
            date=date(2026, 8, 20),
        )
        WorkoutExerciseOld.objects.create(
            workout=other_workout,
            exercise=stale_exercise,
            muscle_group=self.groups["Peito"],
            order=1,
        )
        self.other_workout_id = other_workout.pk

        renamed_exercise = self.old_exercises["Remada Unilateral"]
        renamed_workout = WorkoutOld.objects.create(
            user=user,
            date=date(2026, 8, 21),
        )
        WorkoutExerciseOld.objects.create(
            workout=renamed_workout,
            exercise=renamed_exercise,
            muscle_group=self.groups["Costas"],
            order=1,
        )
        self.renamed_exercise_id = renamed_exercise.pk
        self.renamed_workout_id = renamed_workout.pk

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def test_catalog_is_reduced_and_renames_preserve_ids_and_groups(self):
        ExerciseNew = self.apps.get_model("core", "Exercise")
        system_exercises = ExerciseNew.objects.filter(user__isnull=True)

        self.assertEqual(system_exercises.count(), 74)
        self.assertEqual(
            set(system_exercises.values_list("name", flat=True)),
            set(SYSTEM_EXERCISE_NAMES),
        )
        renamed = system_exercises.get(name="Remada Unilateral com Halter")
        self.assertEqual(renamed.pk, self.renamed_exercise_id)
        for old_name in RENAMED_SYSTEM_EXERCISES:
            self.assertFalse(system_exercises.filter(name=old_name).exists())

        for exercise_name, group_names in EXERCISE_GROUPS.items():
            exercise = system_exercises.get(name=exercise_name)
            expected_primary = PRIMARY_GROUP_OVERRIDES.get(
                exercise_name, group_names[0]
            )
            self.assertEqual(exercise.primary_muscle_group.name, expected_primary)
            self.assertEqual(
                set(exercise.muscle_groups.values_list("name", flat=True)),
                set(group_names),
            )

    def test_removed_exercises_become_isolated_personal_exercises(self):
        ExerciseNew = self.apps.get_model("core", "Exercise")
        WorkoutExerciseNew = self.apps.get_model("core", "WorkoutExercise")
        ExerciseSetNew = self.apps.get_model("core", "ExerciseSet")
        PresetEntryNew = self.apps.get_model("core", "WorkoutPresetExercise")
        stale_name = "Supino Declinado com Barra"

        self.assertFalse(
            ExerciseNew.objects.filter(user__isnull=True, name=stale_name).exists()
        )
        self.assertFalse(ExerciseNew.objects.filter(name="Crossover Alto").exists())
        personal = ExerciseNew.objects.get(pk=self.personal_exercise_id)
        other_personal = ExerciseNew.objects.get(
            user_id=self.other_user_id,
            name=stale_name,
        )
        self.assertNotEqual(personal.pk, other_personal.pk)

        workout_entries = WorkoutExerciseNew.objects.filter(
            workout_id=self.workout_id
        )
        self.assertEqual(workout_entries.count(), 1)
        self.assertEqual(workout_entries.get().exercise_id, personal.pk)
        self.assertEqual(
            list(
                ExerciseSetNew.objects.filter(
                    workout_exercise=workout_entries.get()
                ).values_list("reps", flat=True)
            ),
            [10, 8],
        )
        self.assertEqual(
            WorkoutExerciseNew.objects.get(
                workout_id=self.other_workout_id
            ).exercise_id,
            other_personal.pk,
        )
        personal_preset_entries = PresetEntryNew.objects.filter(
            preset_id=self.personal_preset_id
        )
        self.assertEqual(personal_preset_entries.count(), 1)
        self.assertEqual(personal_preset_entries.get().exercise_id, personal.pk)
        self.assertEqual(personal_preset_entries.get().order, 1)

        renamed_entry = WorkoutExerciseNew.objects.get(
            workout_id=self.renamed_workout_id
        )
        self.assertEqual(renamed_entry.exercise_id, self.renamed_exercise_id)
        self.assertEqual(renamed_entry.muscle_group.name, "Costas")

    def test_only_untouched_defaults_are_updated(self):
        PresetNew = self.apps.get_model("core", "WorkoutPreset")

        for preset_data in DEFAULT_WORKOUT_PRESETS:
            preset = PresetNew.objects.get(
                user_id=self.user_id,
                name=preset_data["name"],
            )
            self.assertEqual(
                list(
                    preset.exercise_entries.order_by("order").values_list(
                        "exercise__name", flat=True
                    )
                ),
                list(preset_data["exercises"]),
            )

        self.assertTrue(
            PresetNew.objects.filter(pk=self.conflicting_push_id, name="Push").exists()
        )
        self.assertFalse(
            PresetNew.objects.filter(pk=self.conflicting_legacy_id).exists()
        )
        self.assertTrue(
            PresetNew.objects.filter(pk=self.edited_legacy_id).exists()
        )
        self.assertFalse(
            PresetNew.objects.filter(
                user_id=self.other_user_id,
                name__in=["Pull", "Legs"],
            ).exists()
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

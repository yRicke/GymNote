import calendar
import json
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, F, Max, Prefetch, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    CustomExerciseForm,
    ExerciseSelectionForm,
    ExerciseSetForm,
    WorkoutFilterForm,
    WorkoutPresetNameForm,
    WorkoutPresetForm,
)
from .models import (
    Exercise,
    ExerciseSet,
    MuscleGroup,
    Workout,
    WorkoutExercise,
    WorkoutPreset,
    WorkoutPresetExercise,
)


def _parse_date(date_str):
    try:
        return date.fromisoformat(date_str)
    except ValueError as exc:
        raise Http404("Data inválida.") from exc


def _next_order(queryset):
    return (queryset.aggregate(max_order=Max("order"))["max_order"] or 0) + 1


def _safe_return_url(request):
    return_url = request.POST.get("return_to") or request.GET.get("return_to")
    if return_url and url_has_allowed_host_and_scheme(
        return_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return return_url
    return None


def _wants_json(request):
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


def _form_errors_json(form):
    return {
        field: [error["message"] for error in errors]
        for field, errors in form.errors.get_json_data(escape_html=False).items()
    }


def _owned_workout_exercise(user, date_str, pk):
    workout_date = _parse_date(date_str)
    return get_object_or_404(
        WorkoutExercise.objects.select_related(
            "exercise",
            "muscle_group",
            "workout",
        ),
        pk=pk,
        workout__user=user,
        workout__date=workout_date,
    )


def _available_exercises_for(user):
    return Exercise.objects.filter(
        Q(user__isnull=True) | Q(user=user),
        is_active=True,
        primary_muscle_group__is_active=True,
    ).select_related("primary_muscle_group").distinct()


def landing_page(request):
    return render(request, "core/landing.html")


@login_required
def calendar_view(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        first_day = date(year, month, 1)
    except (TypeError, ValueError):
        raise Http404("Mês inválido.")

    previous_month = date(year - 1, 12, 1) if month == 1 else date(year, month - 1, 1)
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    workouts = {
        workout.date: workout
        for workout in Workout.objects.filter(
            user=request.user,
            date__year=year,
            date__month=month,
        ).annotate(
            exercise_count=Count("workout_exercises", distinct=True)
        ).prefetch_related(
            "workout_exercises__muscle_group",
        )
    }
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        weeks.append(
            [
                {
                    "date": day,
                    "in_month": day.month == month,
                    "workout": workouts.get(day),
                    "has_workout": bool(
                        workouts.get(day) and workouts[day].exercise_count
                    ),
                    "is_today": day == today,
                }
                for day in week
            ]
        )

    today_workout = workouts.get(today)
    today_group_names = []
    if today_workout:
        today_group_names = list(
            dict.fromkeys(
                entry.muscle_group.name
                for entry in today_workout.workout_exercises.all()
            )
        )
    return render(
        request,
        "core/calendar.html",
        {
            "month_name": calendar.month_name[month],
            "month": first_day,
            "weeks": weeks,
            "previous_month": previous_month,
            "next_month": next_month,
            "today": today,
            "today_workout": today_workout,
            "today_group_names": today_group_names,
        },
    )


@login_required
def workout_list(request):
    filter_form = WorkoutFilterForm(
        request.GET,
        queryset=MuscleGroup.objects.filter(is_active=True),
    )
    selected_groups = []
    selected_date = None
    workouts = Workout.objects.filter(
        user=request.user,
        workout_exercises__isnull=False,
    )
    if filter_form.is_valid():
        selected_groups = list(filter_form.cleaned_data["muscle_groups"])
        selected_date = filter_form.cleaned_data["date"]
    if selected_groups:
        workouts = workouts.filter(
            workout_exercises__muscle_group__in=selected_groups,
        )
    if selected_date:
        workouts = workouts.filter(date=selected_date)
    workouts = list(
        workouts.prefetch_related("workout_exercises__muscle_group")
        .distinct()
        .order_by("-date")
    )
    for workout in workouts:
        workout.group_names = list(
            dict.fromkeys(
                entry.muscle_group.name for entry in workout.workout_exercises.all()
            )
        )
    has_filters = bool(selected_groups or selected_date)
    return render(
        request,
        "core/workout_list.html",
        {
            "workouts": workouts,
            "filter_form": filter_form,
            "selected_groups": selected_groups,
            "selected_date": selected_date,
            "has_filters": has_filters,
            "selected_filter_count": len(selected_groups) + bool(selected_date),
        },
    )


@login_required
def personalization(request):
    custom_exercises = (
        Exercise.objects.filter(user=request.user, is_active=True)
        .prefetch_related("muscle_groups")
        .order_by("name")
    )
    exercise_groups = (
        MuscleGroup.objects.filter(
            exercises__user=request.user,
            exercises__is_active=True,
        )
        .distinct()
        .prefetch_related(
            Prefetch(
                "exercises",
                queryset=custom_exercises,
                to_attr="custom_exercises",
            )
        )
        .order_by("order", "name")
    )
    return render(
        request,
        "core/personalization_exercises.html",
        {
            "custom_exercises": custom_exercises,
            "exercise_groups": exercise_groups,
            "quick_exercise_form": CustomExerciseForm(
                user=request.user,
                auto_id="id_quick_exercise_%s",
            ),
            "active_personalization_tab": "exercises",
        },
    )


@login_required
def custom_exercise_create(request):
    form = CustomExerciseForm(
        request.POST or None,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        exercise = form.save()
        message = "Exercício personalizado criado."
        messages.success(request, message)
        if _wants_json(request):
            return JsonResponse(
                {
                    "ok": True,
                    "message": message,
                    "exercise_id": exercise.pk,
                    "exercise": {
                        "id": exercise.pk,
                        "name": exercise.name,
                        "is_custom": True,
                        "label": (
                            f"{exercise.name} · "
                            f"{exercise.primary_muscle_group.name} · Meu exercício"
                        ),
                        "group": {
                            "id": exercise.primary_muscle_group_id,
                            "name": exercise.primary_muscle_group.name,
                            "order": exercise.primary_muscle_group.order,
                        },
                    },
                },
                status=201,
            )
        return redirect("core:personalization")
    if request.method == "POST" and _wants_json(request):
        return JsonResponse(
            {"ok": False, "errors": _form_errors_json(form)},
            status=400,
        )
    return render(
        request,
        "core/custom_exercise_form.html",
        {
            "form": form,
            "page_title": "Novo exercício",
        },
    )


@login_required
def custom_exercise_edit(request, pk):
    exercise = get_object_or_404(
        Exercise,
        pk=pk,
        user=request.user,
        is_active=True,
    )
    form = CustomExerciseForm(
        request.POST or None,
        instance=exercise,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Exercício personalizado atualizado.")
        return redirect("core:personalization")
    return render(
        request,
        "core/custom_exercise_form.html",
        {
            "form": form,
            "page_title": "Editar exercício",
            "exercise": exercise,
        },
    )


@login_required
def custom_exercise_delete(request, pk):
    exercise = get_object_or_404(
        Exercise,
        pk=pk,
        user=request.user,
        is_active=True,
    )
    if request.method == "POST":
        with transaction.atomic():
            exercise.preset_entries.all().delete()
            if exercise.workout_entries.exists():
                exercise.is_active = False
                exercise.save(update_fields=["is_active"])
            else:
                exercise.delete()
        message = "Exercício personalizado excluído."
        messages.success(request, message)
        if _wants_json(request):
            return JsonResponse({"ok": True, "message": message})
        return redirect("core:personalization")
    return render(
        request,
        "core/confirm_delete.html",
        {
            "page_title": "Excluir exercício personalizado",
            "item_type": "exercício personalizado",
            "item_name": exercise.name,
            "warning": (
                "Ele deixará de aparecer no catálogo. Registros anteriores "
                "serão preservados."
            ),
            "cancel_url": reverse("core:personalization"),
        },
    )


@login_required
def workout_preset_list(request):
    presets = (
        WorkoutPreset.objects.filter(user=request.user)
        .annotate(
            exercise_count=Count("exercise_entries", distinct=True),
            group_count=Count("exercise_entries__muscle_group", distinct=True),
        )
        .order_by("name")
    )
    return render(
        request,
        "core/personalization_presets.html",
        {
            "presets": presets,
            "active_personalization_tab": "presets",
        },
    )


def _preset_source_entries(request):
    raw_workout_id = request.POST.get("source_workout") or request.GET.get(
        "source_workout"
    )
    if not raw_workout_id:
        return None, []
    workout = get_object_or_404(Workout, pk=raw_workout_id, user=request.user)
    return workout, list(
        workout.workout_exercises.select_related(
            "exercise", "muscle_group"
        ).order_by("order")
    )


@login_required
def workout_preset_create(request):
    source_workout, initial_entries = _preset_source_entries(request)
    return_url = _safe_return_url(request)
    form = WorkoutPresetForm(
        request.POST or None,
        user=request.user,
        initial_entries=initial_entries,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Predefinição de treino criada.")
        if return_url:
            return redirect(return_url)
        return redirect("core:personalization_presets")
    return render(
        request,
        "core/workout_preset_form.html",
        {
            "form": form,
            "page_title": "Nova predefinição",
            "return_url": return_url,
            "source_workout": source_workout,
            "quick_exercise_form": CustomExerciseForm(
                user=request.user,
                auto_id="id_quick_exercise_%s",
            ),
        },
    )


@login_required
def workout_preset_edit(request, pk):
    preset = get_object_or_404(
        WorkoutPreset,
        pk=pk,
        user=request.user,
    )
    form = WorkoutPresetForm(
        request.POST or None,
        instance=preset,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Predefinição de treino atualizada.")
        return redirect("core:personalization_presets")
    return render(
        request,
        "core/workout_preset_form.html",
        {
            "form": form,
            "page_title": "Editar predefinição",
            "preset": preset,
            "quick_exercise_form": CustomExerciseForm(
                user=request.user,
                auto_id="id_quick_exercise_%s",
            ),
        },
    )


@login_required
def workout_preset_delete(request, pk):
    preset = get_object_or_404(
        WorkoutPreset,
        pk=pk,
        user=request.user,
    )
    if request.method == "POST":
        preset.delete()
        message = "Predefinição de treino excluída."
        messages.success(request, message)
        if _wants_json(request):
            return JsonResponse({"ok": True, "message": message})
        return redirect("core:personalization_presets")
    return render(
        request,
        "core/confirm_delete.html",
        {
            "page_title": "Excluir predefinição",
            "item_type": "predefinição de treino",
            "item_name": preset.name,
            "warning": "Os treinos já registrados não serão alterados.",
            "cancel_url": reverse("core:personalization_presets"),
        },
    )


@login_required
def workout_day(request, date_str):
    workout_date = _parse_date(date_str)
    workout = Workout.objects.filter(user=request.user, date=workout_date).first()
    added_exercises = (
        workout.workout_exercises.select_related("exercise", "muscle_group")
        .annotate(
            working_sets=Count("sets", filter=Q(sets__is_working_set=True)),
            record_count=Count("sets"),
            cardio_minutes=Sum("sets__duration_minutes", default=0),
        )
        .order_by("order")
        if workout
        else WorkoutExercise.objects.none()
    )
    group_summaries = (
        list(
            workout.workout_exercises.values(
                "muscle_group_id",
                "muscle_group__name",
                "muscle_group__order",
                "muscle_group__tracking_type",
            )
            .annotate(
                exercise_count=Count("id", distinct=True),
                record_count=Count("sets"),
                working_set_count=Count(
                    "sets", filter=Q(sets__is_working_set=True)
                ),
                cardio_minutes=Sum("sets__duration_minutes", default=0),
            )
            .order_by("muscle_group__order", "muscle_group__name")
        )
        if workout
        else []
    )
    available_exercises = _available_exercises_for(request.user).exclude(
        id__in=added_exercises.values_list("exercise_id", flat=True)
    )
    query = request.GET.get("q", "").strip()
    if query:
        available_exercises = available_exercises.filter(name__icontains=query)
    available_exercises = available_exercises.order_by(
        "primary_muscle_group__order", "name"
    )
    exercise_form = ExerciseSelectionForm(queryset=available_exercises)
    exercise_count = available_exercises.count()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        exercises = [
            {
                "id": exercise.pk,
                "name": exercise.name,
                "is_custom": exercise.is_custom,
                "group": exercise.primary_muscle_group.name,
            }
            for exercise in available_exercises
        ]
        return JsonResponse(
            {
                "exercises": exercises,
                "count": len(exercises),
                "query": query,
            }
        )
    presets = (
        WorkoutPreset.objects.filter(user=request.user)
        .annotate(
            exercise_count=Count("exercise_entries", distinct=True),
            group_count=Count("exercise_entries__muscle_group", distinct=True),
        )
        .order_by("name")
    )
    quick_preset_form = WorkoutPresetNameForm(user=request.user)
    quick_exercise_form = CustomExerciseForm(
        user=request.user,
        auto_id="id_quick_exercise_%s",
    )
    return render(
        request,
        "core/workout_day.html",
        {
            "workout_date": workout_date,
            "workout": workout,
            "added_exercises": added_exercises,
            "group_summaries": group_summaries,
            "exercise_form": exercise_form,
            "exercise_count": exercise_count,
            "query": query,
            "presets": presets,
            "quick_preset_form": quick_preset_form,
            "quick_exercise_form": quick_exercise_form,
            "workout_exercise_count": added_exercises.count(),
            "workout_group_count": len(group_summaries),
        },
    )


@require_POST
@login_required
def add_exercises(request, date_str):
    workout_date = _parse_date(date_str)
    workout = Workout.objects.filter(user=request.user, date=workout_date).first()
    existing_ids = (
        workout.workout_exercises.values_list("exercise_id", flat=True)
        if workout
        else []
    )
    available_exercises = _available_exercises_for(request.user).exclude(
        id__in=existing_ids
    )
    form = ExerciseSelectionForm(request.POST, queryset=available_exercises)
    if form.is_valid():
        selected_exercises = list(form.cleaned_data["exercises"])
        first_workout_exercise = None
        with transaction.atomic():
            workout, _ = Workout.objects.get_or_create(
                user=request.user, date=workout_date
            )
            next_order = _next_order(workout.workout_exercises.all())
            for exercise in selected_exercises:
                workout_exercise = WorkoutExercise.objects.create(
                    workout=workout,
                    exercise=exercise,
                    muscle_group=exercise.primary_muscle_group,
                    order=next_order,
                )
                if first_workout_exercise is None:
                    first_workout_exercise = workout_exercise
                next_order += 1
        messages.success(request, "Exercício(s) adicionado(s).")
        if len(selected_exercises) == 1:
            return redirect(
                "core:workout_exercise",
                date_str=date_str,
                pk=first_workout_exercise.pk,
            )
        return redirect("core:workout_day", date_str=date_str)

    messages.error(request, "Selecione ao menos um exercício válido.")
    return redirect("core:workout_day", date_str=date_str)


@require_POST
@login_required
def reorder_exercises(request, date_str):
    workout_date = _parse_date(date_str)
    workout = get_object_or_404(
        Workout, user=request.user, date=workout_date
    )
    try:
        payload = json.loads(request.body)
        requested_order = [int(item) for item in payload["order"]]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Ordem inválida."}, status=400)

    with transaction.atomic():
        entries = list(
            WorkoutExercise.objects.select_for_update().filter(
                workout=workout
            )
        )
        current_ids = {entry.pk for entry in entries}
        if (
            len(requested_order) != len(entries)
            or len(set(requested_order)) != len(requested_order)
            or set(requested_order) != current_ids
        ):
            return JsonResponse(
                {"error": "A ordem deve conter todos os exercícios do treino."},
                status=400,
            )

        WorkoutExercise.objects.filter(workout=workout).update(
            order=F("order") + 1_000_000
        )
        entries_by_id = {entry.pk: entry for entry in entries}
        ordered_entries = []
        for order, entry_id in enumerate(requested_order, start=1):
            entry = entries_by_id[entry_id]
            entry.order = order
            ordered_entries.append(entry)
        WorkoutExercise.objects.bulk_update(ordered_entries, ["order"])

    return JsonResponse({"ok": True, "order": requested_order})


@require_POST
@login_required
def save_workout_preset(request, date_str):
    workout_date = _parse_date(date_str)
    workout = (
        Workout.objects.filter(
            user=request.user,
            date=workout_date,
            workout_exercises__isnull=False,
        )
        .distinct()
        .first()
    )
    if workout is None:
        message = "Adicione ao menos um exercício antes de salvar a predefinição."
        if _wants_json(request):
            return JsonResponse({"ok": False, "message": message}, status=404)
        messages.error(request, message)
        return redirect("core:workout_day", date_str=date_str)

    form = WorkoutPresetNameForm(request.POST, user=request.user)
    if not form.is_valid():
        if _wants_json(request):
            return JsonResponse(
                {"ok": False, "errors": _form_errors_json(form)},
                status=400,
            )
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
        return redirect("core:workout_day", date_str=date_str)

    with transaction.atomic():
        preset = form.save()
        entries = list(
            workout.workout_exercises.select_related(
                "exercise", "muscle_group"
            ).order_by("order")
        )
        WorkoutPresetExercise.objects.bulk_create(
            [
                WorkoutPresetExercise(
                    preset=preset,
                    exercise=entry.exercise,
                    muscle_group=entry.muscle_group,
                    order=entry.order,
                )
                for entry in entries
            ]
        )

    message = f'Predefinição "{preset.name}" criada.'
    messages.success(request, message)
    if _wants_json(request):
        return JsonResponse(
            {"ok": True, "message": message, "preset_id": preset.pk},
            status=201,
        )
    return redirect("core:workout_day", date_str=date_str)


@require_POST
@login_required
def load_workout_preset(request, date_str):
    workout_date = _parse_date(date_str)
    preset = (
        WorkoutPreset.objects.filter(
            user=request.user,
            pk=request.POST.get("preset_id"),
        )
        .prefetch_related(
            "exercise_entries__exercise__muscle_groups",
            "exercise_entries__muscle_group",
        )
        .first()
    )
    if preset is None:
        message = "Predefinição não encontrada."
        if _wants_json(request):
            return JsonResponse({"ok": False, "message": message}, status=404)
        raise Http404(message)
    with transaction.atomic():
        workout, _ = Workout.objects.get_or_create(
            user=request.user, date=workout_date
        )
        workout = Workout.objects.select_for_update().get(pk=workout.pk)
        existing_exercise_ids = set(
            workout.workout_exercises.values_list("exercise_id", flat=True)
        )
        next_order = _next_order(workout.workout_exercises.all())
        added_count = 0
        for preset_entry in preset.exercise_entries.select_related(
            "exercise", "muscle_group"
        ).order_by("order"):
            exercise = preset_entry.exercise
            is_available = (
                exercise.is_active
                and exercise.user_id in (None, request.user.id)
                and exercise.muscle_groups.filter(
                    pk=preset_entry.muscle_group_id
                ).exists()
            )
            if not is_available or exercise.pk in existing_exercise_ids:
                continue
            WorkoutExercise.objects.create(
                workout=workout,
                exercise=exercise,
                muscle_group=preset_entry.muscle_group,
                order=next_order,
            )
            existing_exercise_ids.add(exercise.pk)
            next_order += 1
            added_count += 1
        if not workout.workout_exercises.exists():
            workout.delete()
    if added_count:
        exercise_label = "exercício" if added_count == 1 else "exercícios"
        message = (
            f'Predefinição "{preset.name}" carregada com '
            f"{added_count} {exercise_label}."
        )
        messages.success(request, message)
    else:
        message = "Todos os exercícios disponíveis desta predefinição já estavam no treino."
        messages.info(request, message)
    if _wants_json(request):
        return JsonResponse(
            {"ok": True, "message": message, "added_count": added_count}
        )
    return redirect("core:workout_day", date_str=date_str)


@login_required
def remove_exercise(request, date_str, pk):
    workout_exercise = _owned_workout_exercise(request.user, date_str, pk)
    if request.method == "POST":
        workout_exercise.delete()
        message = "Exercício removido."
        messages.success(request, message)
        if _wants_json(request):
            return JsonResponse({"ok": True, "message": message})
        return redirect("core:workout_day", date_str=date_str)

    return render(
        request,
        "core/confirm_delete.html",
        {
            "page_title": "Excluir exercício",
            "item_type": "exercício",
            "item_name": workout_exercise.exercise.name,
            "warning": "Todas as séries registradas neste exercício também serão excluídas.",
            "cancel_url": reverse("core:workout_day", kwargs={"date_str": date_str}),
        },
    )


@login_required
def workout_exercise_detail(request, date_str, pk):
    workout_exercise = _owned_workout_exercise(request.user, date_str, pk)
    return _render_workout_exercise(request, workout_exercise)


def _format_history_number(value):
    if value is None:
        return "—"
    formatted = format(value, "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted.replace(".", ",")


def _history_relative_label(current_date, previous_date):
    days_ago = (current_date - previous_date).days
    if days_ago == 1:
        return "Há 1 dia"
    if days_ago < 7:
        return f"Há {days_ago} dias"
    weeks_ago = days_ago // 7
    if weeks_ago == 1:
        return "Há 1 semana"
    return f"Há {weeks_ago} semanas"


def _strength_history_payload(exercise_sets):
    feeder_set = next(
        (
            exercise_set
            for exercise_set in exercise_sets
            if not exercise_set.is_working_set
        ),
        None,
    )
    working_sets = [
        exercise_set
        for exercise_set in exercise_sets
        if exercise_set.is_working_set
        and exercise_set.weight_kg is not None
        and exercise_set.reps is not None
    ]
    work_set = (
        min(
            working_sets,
            key=lambda exercise_set: (exercise_set.weight_kg, exercise_set.order),
        )
        if working_sets
        else None
    )
    top_set = (
        max(
            working_sets,
            key=lambda exercise_set: (
                exercise_set.weight_kg,
                exercise_set.reps,
                -exercise_set.order,
            ),
        )
        if working_sets
        else None
    )

    def set_value(exercise_set, empty_value):
        if exercise_set is None:
            return empty_value
        if exercise_set.weight_kg is None or exercise_set.reps is None:
            return "Dados incompletos"
        return (
            f"{_format_history_number(exercise_set.weight_kg)} kg × "
            f"{exercise_set.reps} reps"
        )

    return {
        "summary_items": [
            {
                "label": "Feeder set",
                "value": set_value(feeder_set, "Sem série de preparação"),
            },
            {
                "label": "Work set",
                "value": set_value(work_set, "Sem série válida"),
            },
            {
                "label": "Top set",
                "value": set_value(top_set, "Sem série válida"),
            },
        ],
        "sets": [
            {
                "order": exercise_set.order,
                "weight_kg": _format_history_number(exercise_set.weight_kg),
                "reps": exercise_set.reps if exercise_set.reps is not None else "—",
                "partial_reps": (
                    exercise_set.partial_reps
                    if exercise_set.partial_reps is not None
                    else "—"
                ),
                "is_working_set": exercise_set.is_working_set,
            }
            for exercise_set in exercise_sets
        ],
    }


def _cardio_history_payload(exercise_sets):
    total_duration = sum(
        exercise_set.duration_minutes or 0 for exercise_set in exercise_sets
    )
    distances = [
        exercise_set.distance_km
        for exercise_set in exercise_sets
        if exercise_set.distance_km is not None
    ]
    exertions = [
        exercise_set.perceived_exertion
        for exercise_set in exercise_sets
        if exercise_set.perceived_exertion is not None
    ]
    average_exertion = (
        Decimal(sum(exertions)) / len(exertions) if exertions else None
    )
    return {
        "summary_items": [
            {"label": "Duração total", "value": f"{total_duration} min"},
            {
                "label": "Distância total",
                "value": (
                    f"{_format_history_number(sum(distances, start=Decimal('0')))} km"
                    if distances
                    else "Não registrada"
                ),
            },
            {
                "label": "Esforço médio",
                "value": (
                    f"{_format_history_number(average_exertion)}/10"
                    if exertions
                    else "Não registrado"
                ),
            },
        ],
        "sets": [
            {
                "order": exercise_set.order,
                "duration_minutes": exercise_set.duration_minutes,
                "distance_km": _format_history_number(exercise_set.distance_km),
                "perceived_exertion": (
                    exercise_set.perceived_exertion
                    if exercise_set.perceived_exertion is not None
                    else "—"
                ),
            }
            for exercise_set in exercise_sets
        ],
    }


@require_GET
@login_required
def previous_workout_summary(request, date_str, pk):
    workout_exercise = _owned_workout_exercise(request.user, date_str, pk)
    previous_entry = (
        WorkoutExercise.objects.select_related("workout", "muscle_group")
        .filter(
            workout__user=request.user,
            workout__date__lt=workout_exercise.workout.date,
            exercise_id=workout_exercise.exercise_id,
            sets__isnull=False,
        )
        .distinct()
        .order_by("-workout__date")
        .first()
    )
    if previous_entry is None:
        empty_message = (
            "Nenhum registro anterior encontrado para este exercício."
            if workout_exercise.muscle_group.is_cardio
            else "Nenhuma série anterior encontrada para este exercício."
        )
        return JsonResponse(
            {
                "ok": True,
                "has_history": False,
                "message": empty_message,
            }
        )

    exercise_sets = list(previous_entry.sets.all())
    is_cardio = previous_entry.muscle_group.is_cardio
    history_payload = (
        _cardio_history_payload(exercise_sets)
        if is_cardio
        else _strength_history_payload(exercise_sets)
    )
    return JsonResponse(
        {
            "ok": True,
            "has_history": True,
            "is_cardio": is_cardio,
            "date": previous_entry.workout.date.isoformat(),
            "date_label": previous_entry.workout.date.strftime("%d/%m/%Y"),
            "relative_label": _history_relative_label(
                workout_exercise.workout.date,
                previous_entry.workout.date,
            ),
            **history_payload,
        }
    )


def _exercise_set_form_values(exercise_set):
    return {
        "weight_kg": (
            str(exercise_set.weight_kg)
            if exercise_set.weight_kg is not None
            else ""
        ),
        "reps": exercise_set.reps if exercise_set.reps is not None else "",
        "partial_reps": (
            exercise_set.partial_reps
            if exercise_set.partial_reps is not None
            else ""
        ),
        "duration_minutes": (
            exercise_set.duration_minutes
            if exercise_set.duration_minutes is not None
            else ""
        ),
        "distance_km": (
            str(exercise_set.distance_km)
            if exercise_set.distance_km is not None
            else ""
        ),
        "perceived_exertion": (
            exercise_set.perceived_exertion
            if exercise_set.perceived_exertion is not None
            else ""
        ),
        "is_working_set": exercise_set.is_working_set,
    }


def _render_workout_exercise(
    request,
    workout_exercise,
    *,
    set_form=None,
    editing_set=None,
    open_set_dialog=False,
    status=200,
):
    exercise_sets = list(workout_exercise.sets.all())
    is_cardio = workout_exercise.muscle_group.is_cardio
    return render(
        request,
        "core/workout_exercise.html",
        {
            "workout_exercise": workout_exercise,
            "exercise_sets": exercise_sets,
            "working_set_count": sum(
                exercise_set.is_working_set for exercise_set in exercise_sets
            ),
            "total_duration_minutes": sum(
                exercise_set.duration_minutes or 0
                for exercise_set in exercise_sets
            ),
            "is_cardio": is_cardio,
            "set_form": (
                set_form
                if set_form is not None
                else ExerciseSetForm(workout_exercise=workout_exercise)
            ),
            "editing_set": editing_set,
            "open_set_dialog": open_set_dialog,
            "exercise_set_values": {
                str(exercise_set.pk): _exercise_set_form_values(exercise_set)
                for exercise_set in exercise_sets
            },
        },
        status=status,
    )


@require_POST
@login_required
def add_set(request, date_str, pk):
    workout_exercise = _owned_workout_exercise(request.user, date_str, pk)
    form = ExerciseSetForm(request.POST, workout_exercise=workout_exercise)
    if form.is_valid():
        exercise_set = form.save(commit=False)
        exercise_set.workout_exercise = workout_exercise
        exercise_set.order = _next_order(workout_exercise.sets.all())
        exercise_set.save()
        message = (
            "Registro de cardio adicionado."
            if workout_exercise.muscle_group.is_cardio
            else "Série adicionada."
        )
        messages.success(request, message)
        if _wants_json(request):
            return JsonResponse(
                {"ok": True, "message": message, "set_id": exercise_set.pk},
                status=201,
            )
        return redirect("core:workout_exercise", date_str=date_str, pk=pk)

    if _wants_json(request):
        return JsonResponse(
            {"ok": False, "errors": _form_errors_json(form)},
            status=400,
        )
    return _render_workout_exercise(
        request,
        workout_exercise,
        set_form=form,
        open_set_dialog=True,
        status=400,
    )


@login_required
def edit_set(request, pk):
    exercise_set = get_object_or_404(
        ExerciseSet.objects.select_related(
            "workout_exercise__workout",
            "workout_exercise__muscle_group",
        ),
        pk=pk,
        workout_exercise__workout__user=request.user,
    )
    if request.method == "POST":
        form = ExerciseSetForm(
            request.POST,
            instance=exercise_set,
            workout_exercise=exercise_set.workout_exercise,
        )
        if form.is_valid():
            form.save()
            message = (
                "Registro de cardio atualizado."
                if exercise_set.workout_exercise.muscle_group.is_cardio
                else "Série atualizada."
            )
            messages.success(request, message)
            if _wants_json(request):
                return JsonResponse({"ok": True, "message": message})
            workout = exercise_set.workout_exercise.workout
            return redirect(
                "core:workout_exercise",
                date_str=workout.date.isoformat(),
                pk=exercise_set.workout_exercise_id,
            )
    else:
        form = ExerciseSetForm(
            instance=exercise_set,
            workout_exercise=exercise_set.workout_exercise,
        )
    if request.method == "POST" and _wants_json(request):
        return JsonResponse(
            {"ok": False, "errors": _form_errors_json(form)},
            status=400,
        )
    return _render_workout_exercise(
        request,
        exercise_set.workout_exercise,
        set_form=form,
        editing_set=exercise_set,
        open_set_dialog=True,
        status=400 if request.method == "POST" else 200,
    )


@login_required
def delete_set(request, pk):
    exercise_set = get_object_or_404(
        ExerciseSet.objects.select_related(
            "workout_exercise__workout"
        ),
        pk=pk,
        workout_exercise__workout__user=request.user,
    )
    if request.method == "POST":
        is_cardio = exercise_set.workout_exercise.muscle_group.is_cardio
        workout_exercise_id = exercise_set.workout_exercise_id
        workout_date = exercise_set.workout_exercise.workout.date
        exercise_set.delete()
        message = "Registro de cardio excluído." if is_cardio else "Série excluída."
        messages.success(request, message)
        if _wants_json(request):
            return JsonResponse({"ok": True, "message": message})
        return redirect(
            "core:workout_exercise",
            date_str=workout_date.isoformat(),
            pk=workout_exercise_id,
        )
    return render(request, "core/set_confirm_delete.html", {"exercise_set": exercise_set})

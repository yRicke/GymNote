import calendar
import json
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, F, Max, Prefetch, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

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
        for field, errors in form.errors.get_json_data(escape_html=True).items()
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
    workouts = Workout.objects.filter(
        user=request.user,
        workout_exercises__isnull=False,
    )
    if filter_form.is_valid():
        selected_groups = list(filter_form.cleaned_data["muscle_groups"])
    if selected_groups:
        workouts = workouts.filter(
            workout_exercises__muscle_group__in=selected_groups,
        )
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
    return render(
        request,
        "core/workout_list.html",
        {
            "workouts": workouts,
            "filter_form": filter_form,
            "selected_groups": selected_groups,
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
        form.save()
        messages.success(request, "Exercício personalizado criado.")
        return redirect("core:personalization")
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
        messages.success(request, "Exercício personalizado excluído.")
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
        messages.success(request, "Predefinição de treino excluída.")
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
        return JsonResponse(
            {
                "html": render_to_string(
                    "core/includes/exercise_catalog_results.html",
                    {"exercise_form": exercise_form},
                    request=request,
                ),
                "count": exercise_count,
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
        messages.success(request, "Exercício removido.")
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
    exercise_sets = workout_exercise.sets.all()
    is_cardio = workout_exercise.muscle_group.is_cardio
    return render(
        request,
        "core/workout_exercise.html",
        {
            "workout_exercise": workout_exercise,
            "exercise_sets": exercise_sets,
            "working_set_count": exercise_sets.filter(is_working_set=True).count(),
            "total_duration_minutes": exercise_sets.aggregate(
                total=Sum("duration_minutes"),
            )["total"]
            or 0,
            "is_cardio": is_cardio,
            "set_form": ExerciseSetForm(workout_exercise=workout_exercise),
        },
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
        messages.success(
            request,
            "Registro de cardio adicionado."
            if workout_exercise.muscle_group.is_cardio
            else "Série adicionada.",
        )
    else:
        exercise_sets = workout_exercise.sets.all()
        return render(
            request,
            "core/workout_exercise.html",
            {
                "workout_exercise": workout_exercise,
                "exercise_sets": exercise_sets,
                "working_set_count": exercise_sets.filter(is_working_set=True).count(),
                "total_duration_minutes": exercise_sets.aggregate(
                    total=Sum("duration_minutes"),
                )["total"]
                or 0,
                "is_cardio": workout_exercise.muscle_group.is_cardio,
                "set_form": form,
            },
            status=400,
        )
    return redirect("core:workout_exercise", date_str=date_str, pk=pk)


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
            messages.success(
                request,
                "Registro de cardio atualizado."
                if exercise_set.workout_exercise.muscle_group.is_cardio
                else "Série atualizada.",
            )
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
    return render(request, "core/set_form.html", {"form": form, "exercise_set": exercise_set})


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
        workout_exercise_id = exercise_set.workout_exercise_id
        workout_date = exercise_set.workout_exercise.workout.date
        exercise_set.delete()
        messages.success(request, "Série excluída.")
        return redirect(
            "core:workout_exercise",
            date_str=workout_date.isoformat(),
            pk=workout_exercise_id,
        )
    return render(request, "core/set_confirm_delete.html", {"exercise_set": exercise_set})

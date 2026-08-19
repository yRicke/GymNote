import calendar
import json
from datetime import date
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, F, Max, Prefetch, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (
    CustomExerciseForm,
    ExerciseSelectionForm,
    ExerciseSetForm,
    MuscleGroupSelectionForm,
    PresetGroupSelectionForm,
    WorkoutFilterForm,
    WorkoutPresetForm,
)
from .models import (
    Exercise,
    ExerciseSet,
    MuscleGroup,
    Workout,
    WorkoutExercise,
    WorkoutMuscleGroup,
    WorkoutPreset,
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


def _owned_workout_muscle_group(user, date_str, pk):
    workout_date = _parse_date(date_str)
    return get_object_or_404(
        WorkoutMuscleGroup.objects.select_related("workout", "muscle_group"),
        pk=pk,
        workout__user=user,
        workout__date=workout_date,
    )


def _owned_workout_exercise(user, date_str, pk):
    workout_date = _parse_date(date_str)
    return get_object_or_404(
        WorkoutExercise.objects.select_related(
            "exercise",
            "workout_muscle_group__muscle_group",
            "workout_muscle_group__workout",
        ),
        pk=pk,
        workout_muscle_group__workout__user=user,
        workout_muscle_group__workout__date=workout_date,
    )


def _available_exercises_for(user, muscle_group):
    return Exercise.objects.filter(
        Q(user__isnull=True) | Q(user=user),
        is_active=True,
        muscle_groups=muscle_group,
    ).distinct()


def _continue_after_preset_offer(request, date_str, workout_group):
    queue = request.session.get("preset_offer_queue")
    if not queue or queue.get("date") != date_str:
        return redirect(
            "core:muscle_group",
            date_str=date_str,
            pk=workout_group.pk,
        )

    group_ids = queue.get("group_ids", [])
    if workout_group.pk in group_ids:
        group_ids = group_ids[group_ids.index(workout_group.pk) + 1 :]
    else:
        group_ids = []

    workout_date = _parse_date(date_str)
    for position, group_id in enumerate(group_ids):
        next_group = WorkoutMuscleGroup.objects.filter(
            pk=group_id,
            workout__user=request.user,
            workout__date=workout_date,
        ).first()
        if next_group and WorkoutPreset.objects.filter(
            user=request.user,
            muscle_group_id=next_group.muscle_group_id,
        ).exists():
            queue["group_ids"] = group_ids[position:]
            request.session["preset_offer_queue"] = queue
            return redirect(
                "core:workout_group_preset_offer",
                date_str=date_str,
                pk=next_group.pk,
            )

    fallback = queue.get("fallback", "workout")
    request.session.pop("preset_offer_queue", None)
    if fallback == "group":
        return redirect(
            "core:muscle_group",
            date_str=date_str,
            pk=workout_group.pk,
        )
    return redirect("core:workout_day", date_str=date_str)


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
            muscle_group_count=Count("workout_muscle_groups", distinct=True)
        ).prefetch_related(
            "workout_muscle_groups__muscle_group",
            "workout_muscle_groups__workout_exercises",
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
                    "has_workout_groups": bool(
                        workouts.get(day) and workouts[day].muscle_group_count
                    ),
                    "is_today": day == today,
                }
                for day in week
            ]
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
            "today_workout": workouts.get(today),
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
        workout_muscle_groups__isnull=False,
    )
    if filter_form.is_valid():
        selected_groups = list(filter_form.cleaned_data["muscle_groups"])
    if selected_groups:
        workouts = workouts.filter(
            workout_muscle_groups__muscle_group__in=selected_groups,
        )
    workouts = (
        workouts.prefetch_related("workout_muscle_groups__muscle_group")
        .distinct()
        .order_by("-date")
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
        .select_related("muscle_group")
        .annotate(exercise_count=Count("exercise_entries"))
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


def _preset_group_form(request, preset=None):
    if request.method == "POST":
        group_data = request.POST
    elif "muscle_group" in request.GET:
        group_data = request.GET
    elif preset:
        group_data = {"muscle_group": preset.muscle_group_id}
    else:
        group_data = None
    group_form = PresetGroupSelectionForm(group_data)
    selected_group = None
    if group_form.is_bound and group_form.is_valid():
        selected_group = group_form.cleaned_data["muscle_group"]
    return group_form, selected_group


@login_required
def workout_preset_create(request):
    group_form, selected_group = _preset_group_form(request)
    form = None
    return_url = _safe_return_url(request)
    if selected_group:
        form = WorkoutPresetForm(
            request.POST or None,
            user=request.user,
            muscle_group=selected_group,
            initial_exercise_ids=request.GET.getlist("exercises"),
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
            "group_form": group_form,
            "selected_group": selected_group,
            "page_title": "Nova predefinição",
            "return_url": return_url,
        },
    )


@login_required
def workout_preset_edit(request, pk):
    preset = get_object_or_404(
        WorkoutPreset,
        pk=pk,
        user=request.user,
    )
    group_form, selected_group = _preset_group_form(request, preset=preset)
    form = None
    if selected_group:
        form = WorkoutPresetForm(
            request.POST or None,
            instance=preset,
            user=request.user,
            muscle_group=selected_group,
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
            "group_form": group_form,
            "selected_group": selected_group,
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
    workout = (
        Workout.objects.filter(user=request.user, date=workout_date)
        .prefetch_related("workout_muscle_groups__muscle_group")
        .first()
    )
    workout_groups = (
        workout.workout_muscle_groups.select_related("muscle_group")
        .annotate(
            exercise_count=Count("workout_exercises", distinct=True),
            working_set_count=Count(
                "workout_exercises__sets",
                filter=Q(workout_exercises__sets__is_working_set=True),
                distinct=True,
            ),
            cardio_minutes=Sum(
                "workout_exercises__sets__duration_minutes",
                default=0,
            ),
        )
        if workout
        else WorkoutMuscleGroup.objects.none()
    )
    added_group_ids = workout_groups.values_list("muscle_group_id", flat=True)
    available_groups = MuscleGroup.objects.filter(is_active=True).exclude(
        id__in=added_group_ids
    )
    add_group_form = MuscleGroupSelectionForm(queryset=available_groups, prefix="add")
    return render(
        request,
        "core/workout_day.html",
        {
            "workout_date": workout_date,
            "workout": workout,
            "workout_groups": workout_groups,
            "add_group_form": add_group_form,
        },
    )


@require_POST
@login_required
def add_muscle_groups(request, date_str):
    workout_date = _parse_date(date_str)
    workout = Workout.objects.filter(user=request.user, date=workout_date).first()
    existing_ids = (
        workout.workout_muscle_groups.values_list("muscle_group_id", flat=True)
        if workout
        else []
    )
    available_groups = MuscleGroup.objects.filter(is_active=True).exclude(id__in=existing_ids)
    form = MuscleGroupSelectionForm(
        request.POST,
        queryset=available_groups,
        prefix="add",
    )
    if form.is_valid():
        selected_groups = list(form.cleaned_data["muscle_groups"])
        first_workout_group = None
        created_workout_groups = []
        with transaction.atomic():
            workout, _ = Workout.objects.get_or_create(
                user=request.user,
                date=workout_date,
            )
            next_order = _next_order(workout.workout_muscle_groups.all())
            for muscle_group in selected_groups:
                workout_group = WorkoutMuscleGroup.objects.create(
                    workout=workout,
                    muscle_group=muscle_group,
                    order=next_order,
                )
                if first_workout_group is None:
                    first_workout_group = workout_group
                created_workout_groups.append(workout_group)
                next_order += 1
        messages.success(request, "Grupo(s) muscular(es) adicionado(s).")
        preset_group_ids = set(
            WorkoutPreset.objects.filter(
                user=request.user,
                muscle_group_id__in=[
                    workout_group.muscle_group_id
                    for workout_group in created_workout_groups
                ],
            ).values_list("muscle_group_id", flat=True)
        )
        preset_offer_groups = [
            workout_group
            for workout_group in created_workout_groups
            if workout_group.muscle_group_id in preset_group_ids
        ]
        if preset_offer_groups:
            request.session["preset_offer_queue"] = {
                "date": date_str,
                "group_ids": [group.pk for group in preset_offer_groups],
                "fallback": "group" if len(selected_groups) == 1 else "workout",
            }
            return redirect(
                "core:workout_group_preset_offer",
                date_str=date_str,
                pk=preset_offer_groups[0].pk,
            )
        if len(selected_groups) == 1:
            return redirect(
                "core:muscle_group",
                date_str=date_str,
                pk=first_workout_group.pk,
            )
        return redirect("core:workout_day", date_str=date_str)

    messages.error(request, "Selecione ao menos um grupo muscular válido.")
    return redirect("core:workout_day", date_str=date_str)


@login_required
def remove_muscle_group(request, date_str, pk):
    workout_group = _owned_workout_muscle_group(request.user, date_str, pk)
    if request.method == "POST":
        workout_group.delete()
        messages.success(request, "Grupo muscular removido.")
        return redirect("core:workout_day", date_str=date_str)

    return render(
        request,
        "core/confirm_delete.html",
        {
            "page_title": "Excluir grupo muscular",
            "item_type": "grupo muscular",
            "item_name": workout_group.muscle_group.name,
            "warning": "Os exercícios e as séries deste grupo também serão excluídos.",
            "cancel_url": reverse("core:workout_day", kwargs={"date_str": date_str}),
        },
    )


@login_required
def muscle_group_detail(request, date_str, pk):
    workout_group = _owned_workout_muscle_group(request.user, date_str, pk)
    added_exercises = workout_group.workout_exercises.select_related("exercise").annotate(
        working_sets=Count("sets", filter=Q(sets__is_working_set=True)),
        record_count=Count("sets"),
        cardio_minutes=Sum("sets__duration_minutes", default=0),
    )
    set_counts = workout_group.workout_exercises.aggregate(
        total_set_count=Count("sets"),
        working_set_count=Count(
            "sets",
            filter=Q(sets__is_working_set=True),
        ),
        total_duration_minutes=Sum("sets__duration_minutes", default=0),
    )
    available_exercises = _available_exercises_for(
        request.user,
        workout_group.muscle_group,
    ).exclude(id__in=added_exercises.values_list("exercise_id", flat=True))
    query = request.GET.get("q", "").strip()
    if query:
        available_exercises = available_exercises.filter(name__icontains=query)
    exercise_form = ExerciseSelectionForm(queryset=available_exercises)
    preset_params = [
        ("muscle_group", workout_group.muscle_group_id),
        ("return_to", request.path),
        *[
            ("exercises", exercise_id)
            for exercise_id in added_exercises.values_list("exercise_id", flat=True)
        ],
    ]
    save_preset_url = (
        f'{reverse("core:personalization_preset_create")}?{urlencode(preset_params)}'
        if len(preset_params) > 2
        else ""
    )
    return render(
        request,
        "core/muscle_group.html",
        {
            "workout_group": workout_group,
            "added_exercises": added_exercises,
            "exercise_form": exercise_form,
            "query": query,
            "is_cardio": workout_group.muscle_group.is_cardio,
            "save_preset_url": save_preset_url,
            **set_counts,
        },
    )


@require_POST
@login_required
def add_exercises(request, date_str, pk):
    workout_group = _owned_workout_muscle_group(request.user, date_str, pk)
    existing_ids = workout_group.workout_exercises.values_list("exercise_id", flat=True)
    available_exercises = _available_exercises_for(
        request.user,
        workout_group.muscle_group,
    ).exclude(id__in=existing_ids)
    form = ExerciseSelectionForm(request.POST, queryset=available_exercises)
    if form.is_valid():
        selected_exercises = list(form.cleaned_data["exercises"])
        first_workout_exercise = None
        with transaction.atomic():
            next_order = _next_order(workout_group.workout_exercises.all())
            for exercise in selected_exercises:
                workout_exercise = WorkoutExercise.objects.create(
                    workout_muscle_group=workout_group,
                    exercise=exercise,
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
        return redirect("core:muscle_group", date_str=date_str, pk=pk)

    messages.error(request, "Selecione ao menos um exercício válido.")
    return redirect("core:muscle_group", date_str=date_str, pk=pk)


@require_POST
@login_required
def reorder_exercises(request, date_str, pk):
    workout_group = _owned_workout_muscle_group(request.user, date_str, pk)
    try:
        payload = json.loads(request.body)
        requested_order = [int(item) for item in payload["order"]]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Ordem inválida."}, status=400)

    with transaction.atomic():
        entries = list(
            WorkoutExercise.objects.select_for_update().filter(
                workout_muscle_group=workout_group
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

        WorkoutExercise.objects.filter(workout_muscle_group=workout_group).update(
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


@login_required
def workout_group_preset_offer(request, date_str, pk):
    workout_group = _owned_workout_muscle_group(request.user, date_str, pk)
    presets = (
        WorkoutPreset.objects.filter(
            user=request.user,
            muscle_group=workout_group.muscle_group,
        )
        .prefetch_related("exercise_entries__exercise")
        .order_by("name")
    )
    if not presets.exists():
        return _continue_after_preset_offer(
            request,
            date_str,
            workout_group,
        )

    if request.method == "POST":
        if request.POST.get("action") == "skip":
            return _continue_after_preset_offer(
                request,
                date_str,
                workout_group,
            )

        preset = get_object_or_404(
            presets,
            pk=request.POST.get("preset_id"),
        )
        with transaction.atomic():
            locked_group = WorkoutMuscleGroup.objects.select_for_update().get(
                pk=workout_group.pk
            )
            existing_exercise_ids = set(
                locked_group.workout_exercises.values_list("exercise_id", flat=True)
            )
            next_order = _next_order(locked_group.workout_exercises.all())
            added_count = 0
            for preset_entry in preset.exercise_entries.select_related(
                "exercise"
            ).order_by("order"):
                exercise = preset_entry.exercise
                is_available = (
                    exercise.is_active
                    and exercise.user_id in (None, request.user.id)
                    and exercise.muscle_groups.filter(
                        pk=workout_group.muscle_group_id
                    ).exists()
                )
                if not is_available or exercise.pk in existing_exercise_ids:
                    continue
                WorkoutExercise.objects.create(
                    workout_muscle_group=locked_group,
                    exercise=exercise,
                    order=next_order,
                )
                existing_exercise_ids.add(exercise.pk)
                next_order += 1
                added_count += 1
        if added_count:
            exercise_label = "exercício" if added_count == 1 else "exercícios"
            messages.success(
                request,
                f'Predefinição "{preset.name}" carregada com '
                f"{added_count} {exercise_label}.",
            )
        else:
            messages.info(
                request,
                "Todos os exercícios disponíveis desta predefinição já estavam no grupo.",
            )
        return _continue_after_preset_offer(
            request,
            date_str,
            workout_group,
        )

    return render(
        request,
        "core/workout_preset_offer.html",
        {
            "workout_group": workout_group,
            "presets": presets,
        },
    )


@login_required
def remove_exercise(request, date_str, pk):
    workout_exercise = _owned_workout_exercise(request.user, date_str, pk)
    workout_group_id = workout_exercise.workout_muscle_group_id
    if request.method == "POST":
        workout_exercise.delete()
        messages.success(request, "Exercício removido.")
        return redirect("core:muscle_group", date_str=date_str, pk=workout_group_id)

    return render(
        request,
        "core/confirm_delete.html",
        {
            "page_title": "Excluir exercício",
            "item_type": "exercício",
            "item_name": workout_exercise.exercise.name,
            "warning": "Todas as séries registradas neste exercício também serão excluídas.",
            "cancel_url": reverse(
                "core:muscle_group",
                kwargs={"date_str": date_str, "pk": workout_group_id},
            ),
        },
    )


@login_required
def workout_exercise_detail(request, date_str, pk):
    workout_exercise = _owned_workout_exercise(request.user, date_str, pk)
    exercise_sets = workout_exercise.sets.all()
    is_cardio = workout_exercise.workout_muscle_group.muscle_group.is_cardio
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
            if workout_exercise.workout_muscle_group.muscle_group.is_cardio
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
                "is_cardio": workout_exercise.workout_muscle_group.muscle_group.is_cardio,
                "set_form": form,
            },
            status=400,
        )
    return redirect("core:workout_exercise", date_str=date_str, pk=pk)


@login_required
def edit_set(request, pk):
    exercise_set = get_object_or_404(
        ExerciseSet.objects.select_related(
            "workout_exercise__workout_muscle_group__workout",
            "workout_exercise__workout_muscle_group__muscle_group",
        ),
        pk=pk,
        workout_exercise__workout_muscle_group__workout__user=request.user,
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
                if exercise_set.workout_exercise.workout_muscle_group.muscle_group.is_cardio
                else "Série atualizada.",
            )
            workout = exercise_set.workout_exercise.workout_muscle_group.workout
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
            "workout_exercise__workout_muscle_group__workout"
        ),
        pk=pk,
        workout_exercise__workout_muscle_group__workout__user=request.user,
    )
    if request.method == "POST":
        workout_exercise_id = exercise_set.workout_exercise_id
        workout_date = exercise_set.workout_exercise.workout_muscle_group.workout.date
        exercise_set.delete()
        messages.success(request, "Série excluída.")
        return redirect(
            "core:workout_exercise",
            date_str=workout_date.isoformat(),
            pk=workout_exercise_id,
        )
    return render(request, "core/set_confirm_delete.html", {"exercise_set": exercise_set})

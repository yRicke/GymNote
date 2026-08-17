import calendar
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import ExerciseSelectionForm, ExerciseSetForm, MuscleGroupSelectionForm
from .models import (
    Exercise,
    ExerciseSet,
    MuscleGroup,
    Workout,
    WorkoutExercise,
    WorkoutMuscleGroup,
)


def _parse_date(date_str):
    try:
        return date.fromisoformat(date_str)
    except ValueError as exc:
        raise Http404("Data inválida.") from exc


def _next_order(queryset):
    return (queryset.aggregate(max_order=Max("order"))["max_order"] or 0) + 1


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
def workout_day(request, date_str):
    workout_date = _parse_date(date_str)
    workout = (
        Workout.objects.filter(user=request.user, date=workout_date)
        .prefetch_related("workout_muscle_groups__muscle_group")
        .first()
    )
    workout_groups = (
        workout.workout_muscle_groups.select_related("muscle_group")
        .annotate(exercise_count=Count("workout_exercises"))
        if workout
        else WorkoutMuscleGroup.objects.none()
    )
    added_group_ids = workout_groups.values_list("muscle_group_id", flat=True)
    available_groups = MuscleGroup.objects.filter(is_active=True).exclude(
        id__in=added_group_ids
    )
    add_group_form = MuscleGroupSelectionForm(queryset=available_groups, prefix="add")
    remove_group_form = MuscleGroupSelectionForm(
        queryset=MuscleGroup.objects.filter(id__in=added_group_ids),
        prefix="remove",
    )
    return render(
        request,
        "core/workout_day.html",
        {
            "workout_date": workout_date,
            "workout": workout,
            "workout_groups": workout_groups,
            "add_group_form": add_group_form,
            "remove_group_form": remove_group_form,
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
        with transaction.atomic():
            workout, _ = Workout.objects.get_or_create(
                user=request.user,
                date=workout_date,
            )
            next_order = _next_order(workout.workout_muscle_groups.all())
            for muscle_group in form.cleaned_data["muscle_groups"]:
                WorkoutMuscleGroup.objects.create(
                    workout=workout,
                    muscle_group=muscle_group,
                    order=next_order,
                )
                next_order += 1
        messages.success(request, "Grupo(s) muscular(es) adicionado(s).")
    else:
        messages.error(request, "Selecione ao menos um grupo muscular válido.")
    return redirect("core:workout_day", date_str=date_str)


@require_POST
@login_required
def remove_muscle_groups(request, date_str):
    workout_date = _parse_date(date_str)
    workout = get_object_or_404(Workout, user=request.user, date=workout_date)
    current_groups = MuscleGroup.objects.filter(
        workout_entries__workout=workout
    ).distinct()
    form = MuscleGroupSelectionForm(
        request.POST,
        queryset=current_groups,
        prefix="remove",
    )
    if form.is_valid():
        workout.workout_muscle_groups.filter(
            muscle_group__in=form.cleaned_data["muscle_groups"]
        ).delete()
        messages.success(request, "Grupo(s) muscular(es) removido(s).")
    else:
        messages.error(request, "Selecione ao menos um grupo muscular válido.")
    return redirect("core:workout_day", date_str=date_str)


@login_required
def muscle_group_detail(request, date_str, pk):
    workout_group = _owned_workout_muscle_group(request.user, date_str, pk)
    added_exercises = workout_group.workout_exercises.select_related("exercise").annotate(
        working_sets=Count("sets", filter=Q(sets__is_working_set=True))
    )
    available_exercises = Exercise.objects.filter(
        is_active=True,
        muscle_groups=workout_group.muscle_group,
    ).exclude(id__in=added_exercises.values_list("exercise_id", flat=True))
    query = request.GET.get("q", "").strip()
    if query:
        available_exercises = available_exercises.filter(name__icontains=query)
    exercise_form = ExerciseSelectionForm(queryset=available_exercises)
    return render(
        request,
        "core/muscle_group.html",
        {
            "workout_group": workout_group,
            "added_exercises": added_exercises,
            "exercise_form": exercise_form,
            "query": query,
        },
    )


@require_POST
@login_required
def add_exercises(request, date_str, pk):
    workout_group = _owned_workout_muscle_group(request.user, date_str, pk)
    existing_ids = workout_group.workout_exercises.values_list("exercise_id", flat=True)
    available_exercises = Exercise.objects.filter(
        is_active=True,
        muscle_groups=workout_group.muscle_group,
    ).exclude(id__in=existing_ids)
    form = ExerciseSelectionForm(request.POST, queryset=available_exercises)
    if form.is_valid():
        with transaction.atomic():
            next_order = _next_order(workout_group.workout_exercises.all())
            for exercise in form.cleaned_data["exercises"]:
                WorkoutExercise.objects.create(
                    workout_muscle_group=workout_group,
                    exercise=exercise,
                    order=next_order,
                )
                next_order += 1
        messages.success(request, "Exercício(s) adicionado(s).")
    else:
        messages.error(request, "Selecione ao menos um exercício válido.")
    return redirect("core:muscle_group", date_str=date_str, pk=pk)


@require_POST
@login_required
def remove_exercise(request, date_str, pk):
    workout_exercise = _owned_workout_exercise(request.user, date_str, pk)
    workout_group_id = workout_exercise.workout_muscle_group_id
    workout_exercise.delete()
    messages.success(request, "Exercício removido.")
    return redirect("core:muscle_group", date_str=date_str, pk=workout_group_id)


@login_required
def workout_exercise_detail(request, date_str, pk):
    workout_exercise = _owned_workout_exercise(request.user, date_str, pk)
    exercise_sets = workout_exercise.sets.all()
    return render(
        request,
        "core/workout_exercise.html",
        {
            "workout_exercise": workout_exercise,
            "exercise_sets": exercise_sets,
            "working_set_count": exercise_sets.filter(is_working_set=True).count(),
            "set_form": ExerciseSetForm(),
        },
    )


@require_POST
@login_required
def add_set(request, date_str, pk):
    workout_exercise = _owned_workout_exercise(request.user, date_str, pk)
    form = ExerciseSetForm(request.POST)
    if form.is_valid():
        exercise_set = form.save(commit=False)
        exercise_set.workout_exercise = workout_exercise
        exercise_set.order = _next_order(workout_exercise.sets.all())
        exercise_set.save()
        messages.success(request, "Série adicionada.")
    else:
        exercise_sets = workout_exercise.sets.all()
        return render(
            request,
            "core/workout_exercise.html",
            {
                "workout_exercise": workout_exercise,
                "exercise_sets": exercise_sets,
                "working_set_count": exercise_sets.filter(is_working_set=True).count(),
                "set_form": form,
            },
            status=400,
        )
    return redirect("core:workout_exercise", date_str=date_str, pk=pk)


@login_required
def edit_set(request, pk):
    exercise_set = get_object_or_404(
        ExerciseSet.objects.select_related(
            "workout_exercise__workout_muscle_group__workout"
        ),
        pk=pk,
        workout_exercise__workout_muscle_group__workout__user=request.user,
    )
    if request.method == "POST":
        form = ExerciseSetForm(request.POST, instance=exercise_set)
        if form.is_valid():
            form.save()
            messages.success(request, "Série atualizada.")
            workout = exercise_set.workout_exercise.workout_muscle_group.workout
            return redirect(
                "core:workout_exercise",
                date_str=workout.date.isoformat(),
                pk=exercise_set.workout_exercise_id,
            )
    else:
        form = ExerciseSetForm(instance=exercise_set)
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

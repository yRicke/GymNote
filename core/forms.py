from django import forms
from django.db import transaction
from django.db.models import Case, IntegerField, Q, When

from .models import (
    Exercise,
    ExerciseSet,
    MuscleGroup,
    WorkoutPreset,
    WorkoutPresetExercise,
)


class ExerciseMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, exercise):
        label = f"{exercise.name} · {exercise.primary_muscle_group.name}"
        if exercise.is_custom:
            return f"{label} · Meu exercício"
        return label


class WorkoutFilterForm(forms.Form):
    date = forms.DateField(
        label="Data",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    muscle_groups = forms.ModelMultipleChoiceField(
        queryset=MuscleGroup.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Grupos e modalidades",
        required=False,
    )

    def __init__(self, *args, queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if queryset is not None:
            self.fields["muscle_groups"].queryset = queryset


class ExerciseSelectionForm(forms.Form):
    exercises = ExerciseMultipleChoiceField(
        queryset=Exercise.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Exercícios",
    )

    def __init__(self, *args, queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if queryset is not None:
            self.fields["exercises"].queryset = queryset


class ExerciseSetForm(forms.ModelForm):
    class Meta:
        model = ExerciseSet
        fields = (
            "weight_kg",
            "reps",
            "partial_reps",
            "duration_minutes",
            "distance_km",
            "perceived_exertion",
            "is_working_set",
        )
        labels = {
            "weight_kg": "Peso em kg",
            "reps": "Repetições",
            "partial_reps": "Repetições parciais",
            "duration_minutes": "Duração em minutos",
            "distance_km": "Distância em km",
            "perceived_exertion": "Esforço percebido (1–10)",
            "is_working_set": "Série válida/de trabalho",
        }
        widgets = {
            "weight_kg": forms.NumberInput(
                attrs={"placeholder": "0", "inputmode": "decimal", "step": "0.01"}
            ),
            "reps": forms.NumberInput(
                attrs={"placeholder": "0", "inputmode": "numeric"}
            ),
            "partial_reps": forms.NumberInput(
                attrs={"placeholder": "0", "inputmode": "numeric"}
            ),
            "duration_minutes": forms.NumberInput(
                attrs={"placeholder": "30", "inputmode": "numeric", "min": "1"}
            ),
            "distance_km": forms.NumberInput(
                attrs={"placeholder": "Opcional", "inputmode": "decimal", "step": "0.01"}
            ),
            "perceived_exertion": forms.NumberInput(
                attrs={"placeholder": "1 a 10", "inputmode": "numeric", "min": "1", "max": "10"}
            ),
        }

    def __init__(self, *args, workout_exercise=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workout_exercise = workout_exercise or getattr(
            self.instance,
            "workout_exercise",
            None,
        )
        self.is_cardio = bool(
            self.workout_exercise
            and self.workout_exercise.muscle_group.is_cardio
        )
        if self.is_cardio:
            for field_name in ("weight_kg", "reps", "partial_reps", "is_working_set"):
                self.fields.pop(field_name)
            self.fields["duration_minutes"].required = True
        else:
            for field_name in ("duration_minutes", "distance_km", "perceived_exertion"):
                self.fields.pop(field_name)

    def save(self, commit=True):
        exercise_set = super().save(commit=False)
        if self.is_cardio:
            exercise_set.weight_kg = None
            exercise_set.reps = None
            exercise_set.partial_reps = None
            exercise_set.is_working_set = False
        else:
            exercise_set.duration_minutes = None
            exercise_set.distance_km = None
            exercise_set.perceived_exertion = None
        if commit:
            exercise_set.save()
        return exercise_set


class CustomExerciseForm(forms.ModelForm):
    muscle_group = forms.ModelChoiceField(
        queryset=MuscleGroup.objects.none(),
        label="Grupo ou modalidade",
        empty_label="Selecione uma opção",
    )

    class Meta:
        model = Exercise
        fields = ("name",)
        labels = {"name": "Nome do exercício"}
        widgets = {
            "name": forms.TextInput(
                attrs={"placeholder": "Ex.: Remada unilateral no cabo"}
            ),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["muscle_group"].queryset = MuscleGroup.objects.filter(
            is_active=True
        )
        if self.instance.pk:
            self.fields["muscle_group"].initial = (
                self.instance.primary_muscle_group_id
            )

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        system_exercises = Exercise.objects.filter(
            name__iexact=name,
            is_active=True,
            user__isnull=True,
        )
        owned_exercises = Exercise.objects.filter(
            name__iexact=name,
            is_active=True,
            user=self.user,
        )
        if self.instance.pk:
            owned_exercises = owned_exercises.exclude(pk=self.instance.pk)
        if system_exercises.exists() or owned_exercises.exists():
            raise forms.ValidationError(
                "Já existe um exercício disponível com este nome."
            )
        return name

    @transaction.atomic
    def save(self, commit=True):
        exercise = super().save(commit=False)
        exercise.user = self.user
        exercise.is_active = True
        muscle_group = self.cleaned_data["muscle_group"]
        exercise.primary_muscle_group = muscle_group
        if commit:
            exercise.save()
            exercise.muscle_groups.set([muscle_group])
            exercise.preset_entries.update(muscle_group=muscle_group)
        return exercise


class WorkoutPresetNameForm(forms.ModelForm):
    class Meta:
        model = WorkoutPreset
        fields = ("name",)
        labels = {"name": "Nome da predefinição"}
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ex.: Quadríceps A"}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        presets = WorkoutPreset.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            presets = presets.exclude(pk=self.instance.pk)
        if presets.exists():
            raise forms.ValidationError("Você já possui uma predefinição com este nome.")
        return name

    def save(self, commit=True):
        preset = super().save(commit=False)
        preset.user = self.user
        if commit:
            preset.save()
        return preset


class WorkoutPresetForm(WorkoutPresetNameForm):
    exercises = ExerciseMultipleChoiceField(
        queryset=Exercise.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Exercícios",
    )
    exercise_order = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(
        self,
        *args,
        user,
        initial_entries=None,
        **kwargs,
    ):
        super().__init__(*args, user=user, **kwargs)
        self.entry_groups = {}
        available_exercises = Exercise.objects.filter(
            Q(user__isnull=True) | Q(user=user),
            is_active=True,
        ).select_related("primary_muscle_group").distinct()
        initial_ids = []
        if self.instance.pk:
            entries = list(
                self.instance.exercise_entries.select_related("exercise").order_by(
                    "order"
                )
            )
            initial_ids = [entry.exercise_id for entry in entries]
            self.entry_groups = {
                entry.exercise_id: entry.muscle_group_id for entry in entries
            }
        elif initial_entries:
            entries = list(initial_entries)
            initial_ids = [entry.exercise_id for entry in entries]
            self.entry_groups = {
                entry.exercise_id: entry.muscle_group_id for entry in entries
            }

        if initial_ids:
            selection_order = Case(
                *[
                    When(pk=exercise_id, then=position)
                    for position, exercise_id in enumerate(initial_ids)
                ],
                default=len(initial_ids),
                output_field=IntegerField(),
            )
            available_exercises = available_exercises.annotate(
                selection_order=selection_order
            ).order_by(
                "selection_order",
                "primary_muscle_group__order",
                "name",
            )
        else:
            available_exercises = available_exercises.order_by(
                "primary_muscle_group__order", "name"
            )
        self.fields["exercises"].queryset = available_exercises
        selected_ids = list(initial_ids)
        if self.is_bound:
            available_ids = set(available_exercises.values_list("pk", flat=True))
            submitted_ids = []
            for raw_id in self.data.getlist("exercises"):
                try:
                    exercise_id = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if exercise_id in available_ids and exercise_id not in submitted_ids:
                    submitted_ids.append(exercise_id)
            submitted_id_set = set(submitted_ids)
            selected_ids = []
            for raw_id in self.data.get("exercise_order", "").split(","):
                try:
                    exercise_id = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if (
                    exercise_id in submitted_id_set
                    and exercise_id not in selected_ids
                ):
                    selected_ids.append(exercise_id)
            selected_ids.extend(
                exercise_id
                for exercise_id in submitted_ids
                if exercise_id not in selected_ids
            )

        exercises_by_id = {
            exercise.pk: exercise for exercise in available_exercises
        }
        group_ids = {
            self.entry_groups.get(exercise_id)
            or exercises_by_id[exercise_id].primary_muscle_group_id
            for exercise_id in selected_ids
            if exercise_id in exercises_by_id
        }
        groups_by_id = MuscleGroup.objects.in_bulk(group_ids)
        self.selected_exercise_rows = [
            {
                "exercise": exercises_by_id[exercise_id],
                "muscle_group": groups_by_id[
                    self.entry_groups.get(exercise_id)
                    or exercises_by_id[exercise_id].primary_muscle_group_id
                ],
            }
            for exercise_id in selected_ids
            if exercise_id in exercises_by_id
        ]
        if not self.is_bound and initial_ids:
            self.fields["exercises"].initial = initial_ids
            self.fields["exercise_order"].initial = ",".join(map(str, initial_ids))

    def clean(self):
        cleaned_data = super().clean()
        exercises = cleaned_data.get("exercises")
        if not exercises:
            return cleaned_data
        selected_ids = {exercise.pk for exercise in exercises}
        submitted_order = []
        raw_order = cleaned_data.get("exercise_order", "")
        for raw_id in raw_order.split(","):
            try:
                exercise_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if exercise_id in selected_ids and exercise_id not in submitted_order:
                submitted_order.append(exercise_id)
        for raw_id in self.data.getlist("exercises"):
            try:
                exercise_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if exercise_id in selected_ids and exercise_id not in submitted_order:
                submitted_order.append(exercise_id)
        cleaned_data["ordered_exercise_ids"] = submitted_order
        return cleaned_data

    @transaction.atomic
    def save(self, commit=True):
        preset = super().save(commit=False)
        if commit:
            preset.save()
            preset.exercise_entries.all().delete()
            exercises_by_id = {
                exercise.pk: exercise for exercise in self.cleaned_data["exercises"]
            }
            WorkoutPresetExercise.objects.bulk_create(
                [
                    WorkoutPresetExercise(
                        preset=preset,
                        exercise=exercises_by_id[exercise_id],
                        muscle_group_id=self.entry_groups.get(exercise_id)
                        or exercises_by_id[exercise_id].primary_muscle_group_id,
                        order=order,
                    )
                    for order, exercise_id in enumerate(
                        self.cleaned_data["ordered_exercise_ids"], start=1
                    )
                ]
            )
        return preset

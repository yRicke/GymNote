from django import forms
from django.db import transaction
from django.db.models import Q

from .models import (
    Exercise,
    ExerciseSet,
    MuscleGroup,
    WorkoutPreset,
    WorkoutPresetExercise,
)


class ExerciseMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, exercise):
        if exercise.is_custom:
            return f"{exercise.name} · Meu exercício"
        return exercise.name


class MuscleGroupSelectionForm(forms.Form):
    muscle_groups = forms.ModelMultipleChoiceField(
        queryset=MuscleGroup.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Grupos musculares",
    )

    def __init__(self, *args, queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if queryset is not None:
            self.fields["muscle_groups"].queryset = queryset


class WorkoutFilterForm(forms.Form):
    muscle_groups = forms.ModelMultipleChoiceField(
        queryset=MuscleGroup.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Grupos musculares",
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
            "is_working_set",
        )
        labels = {
            "weight_kg": "Peso em kg",
            "reps": "Repetições",
            "partial_reps": "Repetições parciais",
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
        }


class CustomExerciseForm(forms.ModelForm):
    muscle_group = forms.ModelChoiceField(
        queryset=MuscleGroup.objects.none(),
        label="Grupo muscular",
        empty_label="Selecione um grupo",
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
                self.instance.muscle_groups.values_list("pk", flat=True).first()
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
        if commit:
            exercise.save()
            muscle_group = self.cleaned_data["muscle_group"]
            exercise.muscle_groups.set([muscle_group])
            exercise.preset_entries.exclude(
                preset__muscle_group=muscle_group
            ).delete()
        return exercise


class PresetGroupSelectionForm(forms.Form):
    muscle_group = forms.ModelChoiceField(
        queryset=MuscleGroup.objects.none(),
        label="Grupo muscular",
        empty_label="Selecione um grupo",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["muscle_group"].queryset = MuscleGroup.objects.filter(
            is_active=True
        )


class WorkoutPresetForm(forms.ModelForm):
    exercises = ExerciseMultipleChoiceField(
        queryset=Exercise.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Exercícios",
    )

    class Meta:
        model = WorkoutPreset
        fields = ("name",)
        labels = {"name": "Nome da predefinição"}
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ex.: Quadríceps A"}),
        }

    def __init__(self, *args, user, muscle_group, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.muscle_group = muscle_group
        self.fields["exercises"].queryset = Exercise.objects.filter(
            Q(user__isnull=True) | Q(user=user),
            is_active=True,
            muscle_groups=muscle_group,
        ).distinct()
        if self.instance.pk:
            self.fields["exercises"].initial = self.instance.exercise_entries.order_by(
                "order"
            ).values_list("exercise_id", flat=True)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        presets = WorkoutPreset.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            presets = presets.exclude(pk=self.instance.pk)
        if presets.exists():
            raise forms.ValidationError("Você já possui uma predefinição com este nome.")
        return name

    @transaction.atomic
    def save(self, commit=True):
        preset = super().save(commit=False)
        preset.user = self.user
        preset.muscle_group = self.muscle_group
        if commit:
            preset.save()
            preset.exercise_entries.all().delete()
            WorkoutPresetExercise.objects.bulk_create(
                [
                    WorkoutPresetExercise(
                        preset=preset,
                        exercise=exercise,
                        order=order,
                    )
                    for order, exercise in enumerate(
                        self.cleaned_data["exercises"],
                        start=1,
                    )
                ]
            )
        return preset

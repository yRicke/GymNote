from django import forms

from .models import Exercise, ExerciseSet, MuscleGroup


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
    exercises = forms.ModelMultipleChoiceField(
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

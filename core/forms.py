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
            "weight_description",
            "reps",
            "partial_reps",
            "is_working_set",
        )
        labels = {
            "weight_kg": "Peso em kg",
            "weight_description": "Descrição do peso",
            "reps": "Repetições",
            "partial_reps": "Repetições parciais",
            "is_working_set": "Série válida/de trabalho",
        }

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("weight_kg") is None
            and not cleaned_data.get("weight_description", "").strip()
        ):
            raise forms.ValidationError(
                "Informe o peso em kg ou uma descrição do peso."
            )
        return cleaned_data

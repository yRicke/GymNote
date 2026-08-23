from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver


class MuscleGroup(models.Model):
    class TrackingType(models.TextChoices):
        STRENGTH = "strength", "Força"
        CARDIO = "cardio", "Cardio"

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    tracking_type = models.CharField(
        max_length=10,
        choices=TrackingType.choices,
        default=TrackingType.STRENGTH,
    )

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    @property
    def is_cardio(self):
        return self.tracking_type == self.TrackingType.CARDIO


class Exercise(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="custom_exercises",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=150)
    muscle_groups = models.ManyToManyField(MuscleGroup, related_name="exercises")
    primary_muscle_group = models.ForeignKey(
        MuscleGroup,
        on_delete=models.PROTECT,
        related_name="primary_exercises",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(user__isnull=True),
                name="unique_system_exercise_name",
            ),
            models.UniqueConstraint(
                fields=["user", "name"],
                condition=models.Q(user__isnull=False, is_active=True),
                name="unique_active_custom_exercise_name_per_user",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_custom(self):
        return self.user_id is not None


class WorkoutPreset(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workout_presets",
    )
    name = models.CharField(max_length=120)
    exercises = models.ManyToManyField(
        Exercise,
        through="WorkoutPresetExercise",
        related_name="workout_presets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="unique_workout_preset_name_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.name} - {self.user}"


class WorkoutPresetExercise(models.Model):
    preset = models.ForeignKey(
        WorkoutPreset,
        on_delete=models.CASCADE,
        related_name="exercise_entries",
    )
    exercise = models.ForeignKey(
        Exercise,
        on_delete=models.PROTECT,
        related_name="preset_entries",
    )
    muscle_group = models.ForeignKey(
        MuscleGroup,
        on_delete=models.PROTECT,
        related_name="preset_exercise_entries",
    )
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["preset", "exercise"],
                name="unique_exercise_per_workout_preset",
            ),
            models.UniqueConstraint(
                fields=["preset", "order"],
                name="unique_exercise_order_per_workout_preset",
            ),
        ]

    def clean(self):
        errors = {}
        if self.preset_id and self.exercise_id:
            if not self.exercise.muscle_groups.filter(
                pk=self.muscle_group_id
            ).exists():
                errors["exercise"] = "O exercício não pertence ao grupo da predefinição."
            if self.exercise.user_id not in (None, self.preset.user_id):
                errors["exercise"] = "O exercício não está disponível para este usuário."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.preset} - {self.exercise}"


class Workout(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workouts",
    )
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date"],
                name="unique_workout_per_user_date",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.date:%d/%m/%Y}"


class WorkoutExercise(models.Model):
    workout = models.ForeignKey(
        Workout,
        on_delete=models.CASCADE,
        related_name="workout_exercises",
    )
    exercise = models.ForeignKey(
        Exercise,
        on_delete=models.PROTECT,
        related_name="workout_entries",
    )
    muscle_group = models.ForeignKey(
        MuscleGroup,
        on_delete=models.PROTECT,
        related_name="workout_exercise_entries",
    )
    order = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["workout", "exercise"],
                name="unique_exercise_per_workout",
            ),
            models.UniqueConstraint(
                fields=["workout", "order"],
                name="unique_exercise_order_per_workout",
            ),
        ]

    def __str__(self):
        return f"{self.exercise} - {self.workout}"

    def clean(self):
        errors = {}
        if self.exercise_id and self.muscle_group_id:
            if not self.exercise.muscle_groups.filter(pk=self.muscle_group_id).exists():
                errors["muscle_group"] = "O grupo deve estar associado ao exercício."
        if self.exercise_id and self.workout_id:
            if self.exercise.user_id not in (None, self.workout.user_id):
                errors["exercise"] = "O exercício não está disponível para este usuário."
        if errors:
            raise ValidationError(errors)

    @property
    def working_set_count(self):
        return self.sets.filter(is_working_set=True).count()


class ExerciseSet(models.Model):
    workout_exercise = models.ForeignKey(
        WorkoutExercise,
        on_delete=models.CASCADE,
        related_name="sets",
    )
    order = models.PositiveIntegerField()
    weight_kg = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    reps = models.PositiveIntegerField(null=True, blank=True)
    partial_reps = models.PositiveIntegerField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
    )
    distance_km = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    perceived_exertion = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    is_working_set = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["workout_exercise", "order"],
                name="unique_set_order_per_workout_exercise",
            ),
        ]

    def __str__(self):
        return f"{self.workout_exercise} - Série {self.order}"


class RateLimitCounter(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=1)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["expires_at"]

    def __str__(self):
        return f"{self.key[:12]}… ({self.count})"


@receiver(post_delete, sender=WorkoutExercise)
def delete_empty_workout_after_exercise_removal(
    sender, instance, origin=None, **kwargs
):
    """Remove o treino quando seus exercícios forem removidos diretamente."""
    origin_model = getattr(origin, "model", origin.__class__ if origin else None)
    if origin_model is not WorkoutExercise:
        return

    Workout.objects.filter(
        pk=instance.workout_id, workout_exercises__isnull=True
    ).delete()

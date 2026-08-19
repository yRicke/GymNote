from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.text import slugify


class MuscleGroup(models.Model):
    ICON_BY_SLUG = {
        "peito": "peito",
        "costas": "costas",
        "ombros": "ombros",
        "biceps": "biceps",
        "triceps": "triceps",
        "quadriceps": "quadriceps",
        "posterior-de-coxa": "posterior",
        "gluteos": "gluteos",
        "panturrilhas": "panturrilhas",
        "abdomen": "abdomen",
    }

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

    @property
    def icon_name(self):
        if self.is_cardio:
            return "cardio"

        return self.ICON_BY_SLUG.get(
            self.slug,
            self.ICON_BY_SLUG.get(slugify(self.name), "forca"),
        )


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
    muscle_group = models.ForeignKey(
        MuscleGroup,
        on_delete=models.PROTECT,
        related_name="workout_presets",
    )
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
        return f"{self.name} - {self.muscle_group}"


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
                pk=self.preset.muscle_group_id
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


class WorkoutMuscleGroup(models.Model):
    workout = models.ForeignKey(
        Workout,
        on_delete=models.CASCADE,
        related_name="workout_muscle_groups",
    )
    muscle_group = models.ForeignKey(
        MuscleGroup,
        on_delete=models.PROTECT,
        related_name="workout_entries",
    )
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["workout", "muscle_group"],
                name="unique_muscle_group_per_workout",
            ),
            models.UniqueConstraint(
                fields=["workout", "order"],
                name="unique_muscle_group_order_per_workout",
            ),
        ]

    def __str__(self):
        return f"{self.workout} - {self.muscle_group}"


class WorkoutExercise(models.Model):
    workout_muscle_group = models.ForeignKey(
        WorkoutMuscleGroup,
        on_delete=models.CASCADE,
        related_name="workout_exercises",
    )
    exercise = models.ForeignKey(
        Exercise,
        on_delete=models.PROTECT,
        related_name="workout_entries",
    )
    order = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["workout_muscle_group", "exercise"],
                name="unique_exercise_per_workout_muscle_group",
            ),
            models.UniqueConstraint(
                fields=["workout_muscle_group", "order"],
                name="unique_exercise_order_per_workout_muscle_group",
            ),
        ]

    def __str__(self):
        return f"{self.exercise} - {self.workout_muscle_group}"

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


@receiver(post_delete, sender=WorkoutMuscleGroup)
def delete_empty_workout_after_group_removal(
    sender, instance, origin=None, **kwargs
):
    """Remove o treino quando seus grupos forem removidos diretamente."""
    origin_model = getattr(origin, "model", origin.__class__ if origin else None)
    if origin_model is not WorkoutMuscleGroup:
        return

    Workout.objects.filter(
        pk=instance.workout_id,
        workout_muscle_groups__isnull=True,
    ).delete()

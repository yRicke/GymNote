from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class MuscleGroup(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Exercise(models.Model):
    name = models.CharField(max_length=150, unique=True)
    muscle_groups = models.ManyToManyField(MuscleGroup, related_name="exercises")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Workout(models.Model):
    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planejado"
        IN_PROGRESS = "IN_PROGRESS", "Em andamento"
        COMPLETED = "COMPLETED", "Concluído"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workouts",
    )
    date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNED,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
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
    weight_description = models.CharField(max_length=150, blank=True)
    reps = models.PositiveIntegerField(null=True, blank=True)
    partial_reps = models.PositiveIntegerField(null=True, blank=True)
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

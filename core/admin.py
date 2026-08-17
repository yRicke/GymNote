from django.contrib import admin

from .models import (
    Exercise,
    ExerciseSet,
    MuscleGroup,
    Workout,
    WorkoutExercise,
    WorkoutMuscleGroup,
)


@admin.register(MuscleGroup)
class MuscleGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "order", "is_active")
    list_editable = ("order", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active", "muscle_groups")
    search_fields = ("name",)
    filter_horizontal = ("muscle_groups",)


@admin.register(Workout)
class WorkoutAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "created_at", "updated_at")
    list_filter = ("date",)
    search_fields = ("user__username", "user__email")
    date_hierarchy = "date"

    def has_add_permission(self, request):
        # O treino nasce junto com seu primeiro grupo pelo fluxo da aplicação.
        return False


@admin.register(WorkoutMuscleGroup)
class WorkoutMuscleGroupAdmin(admin.ModelAdmin):
    list_display = ("workout", "muscle_group", "order")
    list_filter = ("muscle_group",)


@admin.register(WorkoutExercise)
class WorkoutExerciseAdmin(admin.ModelAdmin):
    list_display = ("exercise", "workout_muscle_group", "order", "created_at")
    list_filter = ("exercise",)


@admin.register(ExerciseSet)
class ExerciseSetAdmin(admin.ModelAdmin):
    list_display = (
        "workout_exercise",
        "order",
        "weight_kg",
        "reps",
        "partial_reps",
        "is_working_set",
    )
    list_filter = ("is_working_set",)

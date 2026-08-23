from django.contrib import admin

from .models import (
    Exercise,
    ExerciseSet,
    MuscleGroup,
    Workout,
    WorkoutExercise,
    WorkoutPreset,
    WorkoutPresetExercise,
)


@admin.register(MuscleGroup)
class MuscleGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "tracking_type", "order", "is_active")
    list_editable = ("tracking_type", "order", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("name", "primary_muscle_group", "user", "is_active")
    list_filter = ("is_active", "primary_muscle_group", "muscle_groups", "user")
    search_fields = ("name", "user__username", "user__email")
    filter_horizontal = ("muscle_groups",)


class WorkoutPresetExerciseInline(admin.TabularInline):
    model = WorkoutPresetExercise
    extra = 0


@admin.register(WorkoutPreset)
class WorkoutPresetAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "updated_at")
    search_fields = ("name", "user__username", "user__email")
    inlines = (WorkoutPresetExerciseInline,)


@admin.register(Workout)
class WorkoutAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "created_at", "updated_at")
    list_filter = ("date",)
    search_fields = ("user__username", "user__email")
    date_hierarchy = "date"

    def has_add_permission(self, request):
        # O treino nasce junto com seu primeiro exercício pelo fluxo da aplicação.
        return False


@admin.register(WorkoutExercise)
class WorkoutExerciseAdmin(admin.ModelAdmin):
    list_display = ("exercise", "workout", "muscle_group", "order", "created_at")
    list_filter = ("muscle_group", "exercise")


@admin.register(ExerciseSet)
class ExerciseSetAdmin(admin.ModelAdmin):
    list_display = (
        "workout_exercise",
        "order",
        "weight_kg",
        "reps",
        "partial_reps",
        "duration_minutes",
        "distance_km",
        "perceived_exertion",
        "is_working_set",
    )
    list_filter = ("is_working_set",)

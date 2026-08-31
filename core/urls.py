from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.landing_page, name="landing"),
    path("calendario/", views.calendar_view, name="calendar"),
    path("treinos/", views.workout_list, name="workouts"),
    path("personalizacao/", views.personalization, name="personalization"),
    path(
        "personalizacao/exercicios/novo/",
        views.custom_exercise_create,
        name="personalization_exercise_create",
    ),
    path(
        "personalizacao/exercicios/<int:pk>/editar/",
        views.custom_exercise_edit,
        name="personalization_exercise_edit",
    ),
    path(
        "personalizacao/exercicios/<int:pk>/excluir/",
        views.custom_exercise_delete,
        name="personalization_exercise_delete",
    ),
    path(
        "personalizacao/predefinicoes/",
        views.workout_preset_list,
        name="personalization_presets",
    ),
    path(
        "personalizacao/predefinicoes/nova/",
        views.workout_preset_create,
        name="personalization_preset_create",
    ),
    path(
        "personalizacao/predefinicoes/<int:pk>/editar/",
        views.workout_preset_edit,
        name="personalization_preset_edit",
    ),
    path(
        "personalizacao/predefinicoes/<int:pk>/excluir/",
        views.workout_preset_delete,
        name="personalization_preset_delete",
    ),
    path("treino/<str:date_str>/", views.workout_day, name="workout_day"),
    path(
        "treino/<str:date_str>/exercicios/adicionar/",
        views.add_exercises,
        name="add_exercises",
    ),
    path(
        "treino/<str:date_str>/exercicios/reordenar/",
        views.reorder_exercises,
        name="reorder_exercises",
    ),
    path(
        "treino/<str:date_str>/predefinicoes/salvar/",
        views.save_workout_preset,
        name="save_workout_preset",
    ),
    path(
        "treino/<str:date_str>/predefinicoes/carregar/",
        views.load_workout_preset,
        name="load_workout_preset",
    ),
    path(
        "treino/<str:date_str>/exercicio/<int:pk>/",
        views.workout_exercise_detail,
        name="workout_exercise",
    ),
    path(
        "treino/<str:date_str>/exercicio/<int:pk>/resumo-anterior/",
        views.previous_workout_summary,
        name="previous_workout_summary",
    ),
    path(
        "treino/<str:date_str>/exercicio/<int:pk>/remover/",
        views.remove_exercise,
        name="remove_exercise",
    ),
    path(
        "treino/<str:date_str>/exercicio/<int:pk>/series/adicionar/",
        views.add_set,
        name="add_set",
    ),
    path("serie/<int:pk>/editar/", views.edit_set, name="edit_set"),
    path("serie/<int:pk>/excluir/", views.delete_set, name="delete_set"),
]

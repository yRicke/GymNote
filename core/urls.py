from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.landing_page, name="landing"),
    path("calendario/", views.calendar_view, name="calendar"),
    path("treinos/", views.workout_list, name="workouts"),
    path("treino/<str:date_str>/", views.workout_day, name="workout_day"),
    path(
        "treino/<str:date_str>/grupos/adicionar/",
        views.add_muscle_groups,
        name="add_muscle_groups",
    ),
    path(
        "treino/<str:date_str>/grupo/<int:pk>/remover/",
        views.remove_muscle_group,
        name="remove_muscle_group",
    ),
    path(
        "treino/<str:date_str>/grupo/<int:pk>/",
        views.muscle_group_detail,
        name="muscle_group",
    ),
    path(
        "treino/<str:date_str>/grupo/<int:pk>/exercicios/adicionar/",
        views.add_exercises,
        name="add_exercises",
    ),
    path(
        "treino/<str:date_str>/exercicio/<int:pk>/",
        views.workout_exercise_detail,
        name="workout_exercise",
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

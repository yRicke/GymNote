from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from core.models import Exercise, MuscleGroup


CATALOG = {
    "Peito": [
        "Supino Reto com Barra",
        "Supino Inclinado com Barra",
        "Supino Reto com Halteres",
        "Supino Inclinado com Halteres",
        "Crucifixo",
        "Crossover",
        "Peck Deck",
    ],
    "Costas": [
        "Puxada Alta",
        "Barra Fixa",
        "Remada Baixa",
        "Remada Curvada",
        "Remada Unilateral",
        "Pulldown",
    ],
    "Ombros": [
        "Desenvolvimento com Halteres",
        "Desenvolvimento com Barra",
        "Elevação Lateral",
        "Elevação Frontal",
        "Crucifixo Inverso",
    ],
    "Bíceps": [
        "Rosca Direta",
        "Rosca Alternada",
        "Rosca Scott",
        "Rosca Martelo",
        "Rosca na Polia",
    ],
    "Tríceps": [
        "Tríceps Corda",
        "Tríceps Barra",
        "Tríceps Francês",
        "Tríceps Testa",
        "Mergulho",
    ],
    "Quadríceps": [
        "Agachamento Livre",
        "Leg Press",
        "Hack Squat",
        "Cadeira Extensora",
        "Agachamento no Smith",
    ],
    "Posterior de Coxa": [
        "Stiff",
        "Levantamento Terra Romeno",
        "Mesa Flexora",
        "Cadeira Flexora",
    ],
    "Glúteos": [
        "Elevação Pélvica",
        "Agachamento Livre",
        "Stiff",
        "Afundo",
        "Búlgaro",
    ],
    "Panturrilhas": [
        "Panturrilha em Pé",
        "Panturrilha Sentado",
        "Panturrilha no Leg Press",
    ],
    "Abdômen": [
        "Abdominal Crunch",
        "Abdominal na Polia",
        "Elevação de Pernas",
        "Prancha",
    ],
}


class Command(BaseCommand):
    help = "Popula o catálogo inicial de grupos musculares e exercícios."

    @transaction.atomic
    def handle(self, *args, **options):
        groups = {}
        for order, group_name in enumerate(CATALOG, start=1):
            group, _ = MuscleGroup.objects.update_or_create(
                slug=slugify(group_name),
                defaults={
                    "name": group_name,
                    "order": order,
                    "is_active": True,
                },
            )
            groups[group_name] = group

        exercise_groups = defaultdict(list)
        for group_name, exercise_names in CATALOG.items():
            for exercise_name in exercise_names:
                exercise_groups[exercise_name].append(groups[group_name])

        for exercise_name, related_groups in exercise_groups.items():
            exercise, _ = Exercise.objects.update_or_create(
                name=exercise_name,
                defaults={"is_active": True},
            )
            exercise.muscle_groups.set(related_groups)

        self.stdout.write(
            self.style.SUCCESS(
                f"Catálogo atualizado: {len(groups)} grupos e "
                f"{len(exercise_groups)} exercícios."
            )
        )

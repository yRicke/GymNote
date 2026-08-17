from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from core.models import Exercise, MuscleGroup


CATALOG = {
    "Peito": [
        "Supino Reto com Barra",
        "Supino Inclinado com Barra",
        "Supino Declinado com Barra",
        "Supino Reto com Halteres",
        "Supino Inclinado com Halteres",
        "Supino Declinado com Halteres",
        "Supino Reto no Smith",
        "Supino Inclinado no Smith",
        "Supino na Máquina",
        "Supino Fechado",
        "Crucifixo",
        "Crucifixo Inclinado com Halteres",
        "Crossover",
        "Crossover Alto",
        "Crossover Médio",
        "Crossover Baixo",
        "Peck Deck",
        "Flexão de Braços",
        "Paralelas",
        "Pullover com Halter",
    ],
    "Costas": [
        "Puxada Alta",
        "Puxada Neutra",
        "Puxada Supinada",
        "Barra Fixa",
        "Remada Baixa",
        "Remada Curvada",
        "Remada Unilateral",
        "Remada Cavalinho",
        "Remada na Máquina",
        "Remada Alta",
        "Pulldown",
        "Pullover na Polia",
        "Pullover com Halter",
        "Face Pull",
        "Encolhimento com Barra",
        "Encolhimento com Halteres",
        "Levantamento Terra",
        "Hiperextensão Lombar",
    ],
    "Ombros": [
        "Desenvolvimento com Halteres",
        "Desenvolvimento com Barra",
        "Desenvolvimento Arnold",
        "Desenvolvimento na Máquina",
        "Elevação Lateral",
        "Elevação Lateral na Polia",
        "Elevação Lateral na Máquina",
        "Elevação Lateral Inclinado",
        "Elevação Frontal",
        "Crucifixo Inverso",
        "Face Pull",
        "Remada Alta",
        "Encolhimento com Barra",
        "Encolhimento com Halteres",
        "Rotação Externa na Polia",
    ],
    "Bíceps": [
        "Rosca Direta",
        "Rosca Alternada",
        "Rosca Scott",
        "Rosca Scott Unilateral",
        "Rosca Martelo",
        "Rosca Martelo na Polia",
        "Rosca na Polia",
        "Rosca Concentrada",
        "Rosca Inclinada",
        "Rosca Spider",
        "Rosca Bayesian",
        "Rosca Inversa",
        "Rosca 21",
    ],
    "Tríceps": [
        "Tríceps Corda",
        "Tríceps Barra",
        "Tríceps Francês",
        "Tríceps Francês com Halter",
        "Tríceps Testa",
        "Tríceps Testa com Halteres",
        "Tríceps Coice",
        "Tríceps Unilateral na Polia",
        "Tríceps na Máquina",
        "Supino Fechado",
        "Paralelas",
        "Mergulho",
    ],
    "Quadríceps": [
        "Agachamento Livre",
        "Agachamento Frontal",
        "Agachamento Goblet",
        "Agachamento Sumô",
        "Agachamento Sissy",
        "Leg Press",
        "Leg Press Unilateral",
        "Hack Squat",
        "Belt Squat",
        "Cadeira Extensora",
        "Cadeira Extensora Unilateral",
        "Agachamento no Smith",
        "Afundo",
        "Búlgaro",
        "Passada",
        "Step Up",
    ],
    "Posterior de Coxa": [
        "Stiff",
        "Levantamento Terra",
        "Levantamento Terra Romeno",
        "Levantamento Terra Sumô",
        "Mesa Flexora",
        "Cadeira Flexora",
        "Flexora em Pé",
        "Flexora Unilateral",
        "Nordic Curl",
        "Good Morning",
        "Glute Ham Raise",
        "Pull Through",
        "Hiperextensão Lombar",
    ],
    "Glúteos": [
        "Elevação Pélvica",
        "Elevação Pélvica Unilateral",
        "Agachamento Livre",
        "Agachamento Goblet",
        "Agachamento Sumô",
        "Stiff",
        "Levantamento Terra Sumô",
        "Afundo",
        "Búlgaro",
        "Passada",
        "Step Up",
        "Coice na Polia",
        "Abdução de Quadril na Máquina",
        "Abdução de Quadril na Polia",
        "Glúteo na Máquina",
        "Pull Through",
        "Hiperextensão Lombar",
    ],
    "Panturrilhas": [
        "Panturrilha em Pé",
        "Panturrilha Unilateral em Pé",
        "Panturrilha Sentado",
        "Panturrilha Sentado Unilateral",
        "Panturrilha no Leg Press",
        "Panturrilha no Leg Press Unilateral",
        "Panturrilha no Smith",
        "Panturrilha no Hack",
        "Panturrilha Donkey",
    ],
    "Abdômen": [
        "Abdominal Crunch",
        "Abdominal na Polia",
        "Abdominal Infra",
        "Abdominal Bicicleta",
        "Abdominal Remador",
        "Abdominal Oblíquo",
        "Elevação de Pernas",
        "Elevação de Joelhos na Barra",
        "Prancha",
        "Prancha Lateral",
        "Roda Abdominal",
        "Rotação Russa",
        "Dead Bug",
        "Hollow Body",
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
                user=None,
                defaults={"is_active": True},
            )
            exercise.muscle_groups.set(related_groups)

        self.stdout.write(
            self.style.SUCCESS(
                f"Catálogo atualizado: {len(groups)} grupos e "
                f"{len(exercise_groups)} exercícios."
            )
        )

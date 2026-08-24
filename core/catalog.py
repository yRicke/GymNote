from collections import defaultdict


CATALOG = {
    "Peito": [
        "Supino Reto com Barra",
        "Supino Reto com Halteres",
        "Supino Inclinado com Barra",
        "Supino Inclinado com Halteres",
        "Crucifixo com Halteres",
        "Crossover na Polia",
        "Peck Deck",
        "Paralelas",
        "Supino Fechado",
    ],
    "Costas": [
        "Puxada Alta",
        "Barra Fixa",
        "Remada Curvada com Barra",
        "Remada Baixa",
        "Remada Unilateral com Halter",
        "Remada Máquina",
        "Pulldown",
        "Pullover na Polia",
        "Face Pull",
        "Levantamento Terra",
    ],
    "Ombros": [
        "Desenvolvimento com Halteres",
        "Desenvolvimento com Barra",
        "Desenvolvimento Máquina",
        "Elevação Lateral",
        "Elevação Frontal",
        "Crucifixo Inverso",
        "Face Pull",
        "Desenvolvimento Militar",
    ],
    "Bíceps": [
        "Rosca Direta com Barra",
        "Rosca Direta com Halteres",
        "Rosca Alternada",
        "Rosca Martelo",
        "Rosca Scott",
        "Rosca Inclinada",
        "Rosca na Polia",
    ],
    "Tríceps": [
        "Tríceps na Polia",
        "Tríceps Francês",
        "Tríceps Testa",
        "Tríceps Corda",
        "Tríceps Unilateral",
        "Paralelas",
        "Supino Fechado",
    ],
    "Quadríceps": [
        "Agachamento Livre",
        "Agachamento no Smith",
        "Leg Press",
        "Hack Squat",
        "Cadeira Extensora",
        "Afundo",
        "Agachamento Búlgaro",
        "Passada",
    ],
    "Posterior de Coxa": [
        "Stiff",
        "Levantamento Terra Romeno",
        "Mesa Flexora",
        "Cadeira Flexora",
        "Flexora Unilateral",
        "Good Morning",
        "Levantamento Terra",
    ],
    "Glúteos": [
        "Elevação Pélvica",
        "Hip Thrust",
        "Coice na Polia",
        "Abdução de Quadril",
        "Passada",
        "Agachamento Livre",
    ],
    "Panturrilhas": [
        "Panturrilha em Pé",
        "Panturrilha Sentada",
        "Panturrilha no Leg Press",
        "Panturrilha Unilateral",
    ],
    "Abdômen": [
        "Abdominal Tradicional",
        "Abdominal Máquina",
        "Abdominal na Polia",
        "Elevação de Pernas",
        "Prancha",
        "Abdominal Infra",
    ],
    "Cardio": [
        "Caminhada",
        "Corrida",
        "Bicicleta Ergométrica",
        "Elíptico",
        "Escada",
        "Remo Ergométrico",
        "Pular Corda",
        "HIIT",
    ],
}


PRIMARY_GROUP_OVERRIDES = {
    "Face Pull": "Ombros",
    "Paralelas": "Tríceps",
    "Passada": "Glúteos",
    "Supino Fechado": "Tríceps",
}


RENAMED_SYSTEM_EXERCISES = {
    "Crucifixo": "Crucifixo com Halteres",
    "Crossover": "Crossover na Polia",
    "Remada Curvada": "Remada Curvada com Barra",
    "Remada Unilateral": "Remada Unilateral com Halter",
    "Remada na Máquina": "Remada Máquina",
    "Desenvolvimento na Máquina": "Desenvolvimento Máquina",
    "Rosca Direta": "Rosca Direta com Barra",
    "Tríceps Barra": "Tríceps na Polia",
    "Tríceps Unilateral na Polia": "Tríceps Unilateral",
    "Búlgaro": "Agachamento Búlgaro",
    "Panturrilha Sentado": "Panturrilha Sentada",
    "Panturrilha Unilateral em Pé": "Panturrilha Unilateral",
    "Abdominal Crunch": "Abdominal Tradicional",
    "Abdução de Quadril na Máquina": "Abdução de Quadril",
}


def get_exercise_groups():
    exercise_groups = defaultdict(list)
    for group_name, exercise_names in CATALOG.items():
        for exercise_name in exercise_names:
            exercise_groups[exercise_name].append(group_name)
    return dict(exercise_groups)


EXERCISE_GROUPS = get_exercise_groups()
SYSTEM_EXERCISE_NAMES = frozenset(EXERCISE_GROUPS)

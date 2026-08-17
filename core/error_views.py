from django.http import HttpResponse
from django.template import loader


ERROR_PAGES = {
    400: {
        "eyebrow": "Solicitação inválida",
        "heading": "Não conseguimos processar isso",
        "description": (
            "A solicitação chegou incompleta ou em um formato inesperado. "
            "Volte ao início e tente novamente."
        ),
        "icon": "warning",
    },
    403: {
        "eyebrow": "Acesso não permitido",
        "heading": "Esta área não está disponível",
        "description": (
            "Você não tem permissão para acessar este conteúdo ou sua sessão "
            "expirou. Entre novamente e tente outra vez."
        ),
        "icon": "lock",
    },
    404: {
        "eyebrow": "Página não encontrada",
        "heading": "Esse caminho não existe",
        "description": (
            "O endereço pode ter mudado ou sido digitado incorretamente. "
            "Você pode continuar a partir da página inicial."
        ),
        "icon": "search_off",
    },
    500: {
        "eyebrow": "Erro interno",
        "heading": "Algo saiu do lugar",
        "description": (
            "Encontramos um problema ao carregar esta página. Tente novamente "
            "em alguns instantes."
        ),
        "icon": "construction",
    },
}


def _error_response(status_code, **context):
    page_context = {
        "error_code": status_code,
        **ERROR_PAGES.get(status_code, {}),
        **context,
    }
    content = loader.get_template("errors/error.html").render(page_context)
    return HttpResponse(content, status=status_code)


def bad_request(request, exception=None):
    return _error_response(400)


def permission_denied(request, exception=None):
    return _error_response(403)


def page_not_found(request, exception=None):
    return _error_response(404)


def server_error(request):
    return _error_response(500)


def csrf_failure(request, reason=""):
    return _error_response(403)


def too_many_requests(request, retry_after):
    retry_label = "segundo" if retry_after == 1 else "segundos"
    return _error_response(
        429,
        eyebrow="Limite de requisições",
        heading="Respire um pouco",
        description=(
            "Muitas ações foram enviadas em sequência. Tente novamente em "
            f"aproximadamente {retry_after} {retry_label}."
        ),
        icon="timer",
    )

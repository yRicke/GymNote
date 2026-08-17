from django.conf import settings

from .error_views import too_many_requests
from .rate_limit import client_identity, consume_rate_limit


class RateLimitMiddleware:
    AUTH_PATHS = {"/accounts/login/", "/accounts/cadastro/"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method != "POST":
            return self.get_response(request)

        limits = settings.GYMNOTE_RATE_LIMITS
        is_auth_request = request.path_info in self.AUTH_PATHS
        policy_name = "auth" if is_auth_request else "write"
        policy = limits[policy_name]
        identity = client_identity(request, prefer_user=not is_auth_request)
        allowed, remaining, retry_after = consume_rate_limit(
            scope=policy_name,
            identity=identity,
            limit=policy["limit"],
            window_seconds=policy["window_seconds"],
        )

        if not allowed:
            response = too_many_requests(request, retry_after)
            response["Retry-After"] = str(retry_after)
        else:
            response = self.get_response(request)

        response["X-RateLimit-Limit"] = str(policy["limit"])
        response["X-RateLimit-Remaining"] = str(remaining)
        return response

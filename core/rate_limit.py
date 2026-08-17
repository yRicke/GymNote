import hashlib
import math
from datetime import datetime, timezone as datetime_timezone

from django.db.models import F
from django.utils import timezone

from .models import RateLimitCounter


def client_identity(request, *, prefer_user=True):
    if prefer_user and request.user.is_authenticated:
        return f"user:{request.user.pk}"

    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip_address = forwarded_for.split(",", 1)[0].strip()
    if not ip_address:
        ip_address = request.META.get("REMOTE_ADDR", "unknown")
    return f"ip:{ip_address}"


def consume_rate_limit(*, scope, identity, limit, window_seconds):
    now = timezone.now()
    window_number = int(now.timestamp()) // window_seconds
    window_end_timestamp = (window_number + 1) * window_seconds
    expires_at = datetime.fromtimestamp(
        window_end_timestamp,
        tz=datetime_timezone.utc,
    )
    raw_key = f"{scope}:{identity}:{window_number}"
    key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    counter, created = RateLimitCounter.objects.get_or_create(
        key=key,
        defaults={"count": 1, "expires_at": expires_at},
    )
    if created:
        RateLimitCounter.objects.filter(expires_at__lt=now).delete()
        return True, limit - 1, 0

    updated = RateLimitCounter.objects.filter(
        key=key,
        count__lt=limit,
    ).update(count=F("count") + 1)
    if updated:
        counter.refresh_from_db(fields=["count"])
        return True, max(0, limit - counter.count), 0

    retry_after = max(1, math.ceil((expires_at - now).total_seconds()))
    return False, 0, retry_after

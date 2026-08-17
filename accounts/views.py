from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import RegisterForm


def register(request):
    if request.user.is_authenticated:
        return redirect("core:calendar")
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("core:calendar")
    else:
        form = RegisterForm()
    return render(request, "accounts/register.html", {"form": form})


@login_required
def profile(request):
    return render(
        request,
        "accounts/profile.html",
        {
            "workout_count": request.user.workouts.filter(
                workout_muscle_groups__isnull=False
            )
            .distinct()
            .count()
        },
    )

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
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
    password_form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and password_form.is_valid():
        user = password_form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Senha atualizada com segurança.")
        return redirect("accounts:profile")

    return render(
        request,
        "accounts/profile.html",
        {
            "workout_count": request.user.workouts.filter(
                workout_exercises__isnull=False
            )
            .distinct()
            .count(),
            "password_form": password_form,
        },
        status=400 if request.method == "POST" else 200,
    )

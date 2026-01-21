from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages

from .models import Team
from .forms import TeamImportForm

@staff_member_required
def import_teams_view(request):
    if request.method == "POST":
        form = TeamImportForm(request.POST)
        if form.is_valid():
            competition = form.cleaned_data["competition"]
            team_names = form.cleaned_data["teams"].splitlines()

            created = 0
            for name in team_names:
                name = name.strip()
                if not name:
                    continue

                _, was_created = Team.objects.get_or_create(
                    name=name,
                    competition=competition
                )
                if was_created:
                    created += 1

            messages.success(
                request,
                f"{created} équipes ajoutées à {competition}"
            )
            return redirect("/admin/")

    else:
        form = TeamImportForm()

    return render(request, "admin/import_teams.html", {"form": form})

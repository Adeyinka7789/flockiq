from django.shortcuts import render

def case_study_detail(request, slug):
    return render(request, "case-study-details.html", {"slug": slug})
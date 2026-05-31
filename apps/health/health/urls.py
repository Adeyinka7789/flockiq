from django.urls import path

from . import views

app_name = "health"

urlpatterns = [
    path(
        "health/vaccinations/",
        views.VaccinationCalendarView.as_view(),
        name="calendar",
    ),
    path(
        "health/vaccinations/<uuid:pk>/complete/",
        views.VaccinationCompleteView.as_view(),
        name="complete",
    ),
    path(
        "health/medications/<uuid:batch_pk>/log/",
        views.MedicationLogView.as_view(),
        name="medication_log",
    ),
    path(
        "health/symptoms/<uuid:batch_pk>/log/",
        views.SymptomLogView.as_view(),
        name="symptom_log",
    ),
    path(
        "health/summary/<uuid:batch_pk>/",
        views.HealthSummaryView.as_view(),
        name="summary",
    ),
    path(
        "health/outbreaks/",
        views.OutbreakAlertView.as_view(),
        name="outbreaks",
    ),
    path(
        "api/v1/health/vaccinations/",
        views.VaccinationAPIView.as_view(),
        name="api_vaccinations",
    ),
    path(
        "api/v1/health/vaccinations/<uuid:pk>/complete/",
        views.VaccinationCompleteAPIView.as_view(),
        name="api_complete",
    ),
    path(
        "api/v1/health/medications/",
        views.MedicationAPIView.as_view(),
        name="api_medications",
    ),
    path(
        "api/v1/health/symptoms/",
        views.SymptomAPIView.as_view(),
        name="api_symptoms",
    ),
]

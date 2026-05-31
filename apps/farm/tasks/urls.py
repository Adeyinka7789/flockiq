from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("tasks/", views.TaskListView.as_view(), name="list"),
    path("tasks/summary/", views.TaskSummaryWidget.as_view(), name="summary"),
    path("tasks/<uuid:pk>/complete/", views.TaskCompleteView.as_view(), name="complete"),
]

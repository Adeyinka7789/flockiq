from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("tasks/", views.TaskListView.as_view(), name="list"),
    path("tasks/summary/", views.TaskSummaryWidget.as_view(), name="summary"),
    path("tasks/create/", views.TaskCreateView.as_view(), name="create"),
    path("tasks/<uuid:pk>/complete/", views.TaskCompleteView.as_view(), name="complete"),
    path("tasks/<uuid:pk>/status/", views.TaskStatusView.as_view(), name="status"),
    path("tasks/<uuid:pk>/delete/", views.TaskDeleteView.as_view(), name="delete"),
]

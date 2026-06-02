import pytest

pytestmark = pytest.mark.django_db


class TestTaskListView:

    def test_task_list_requires_login(self, client):
        response = client.get("/tasks/")
        assert response.status_code in (301, 302)

    def test_task_list_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/tasks/")
        assert response.status_code == 200


class TestTaskSummaryWidget:

    def test_summary_widget_requires_login(self, client):
        response = client.get("/tasks/summary/")
        assert response.status_code in (301, 302)

    def test_summary_widget_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/tasks/summary/")
        assert response.status_code == 200

    def test_summary_widget_user_without_org(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get("/tasks/summary/")
        assert response.status_code == 200


class TestTaskCompleteView:

    def test_task_complete_requires_login(self, client, test_batch):
        import uuid
        response = client.post(f"/tasks/{uuid.uuid4()}/complete/")
        assert response.status_code in (301, 302)

    def test_task_complete_nonexistent_returns_404(self, client, tenant_user):
        import uuid
        client.force_login(tenant_user)
        response = client.post(f"/tasks/{uuid.uuid4()}/complete/")
        assert response.status_code == 404

    def test_task_complete_existing_task(self, client, tenant_user, test_org, test_farm, test_batch):
        from apps.farm.tasks.models import FarmTask
        from apps.infrastructure.core.rls import set_tenant_context
        import datetime
        client.force_login(tenant_user)
        with set_tenant_context(test_org):
            task = FarmTask.objects.create(
                org=test_org,
                farm=test_farm,
                batch=test_batch,
                title="Feed birds",
                due_date=datetime.date.today(),
                status="pending",
            )
        response = client.post(f"/tasks/{task.pk}/complete/")
        assert response.status_code == 200
        task.refresh_from_db()
        assert task.status == "complete"

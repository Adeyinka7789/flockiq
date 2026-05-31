import pytest
from django.test import TestCase  # noqa: F401


@pytest.fixture(scope="session")
def django_db_setup():
    pass

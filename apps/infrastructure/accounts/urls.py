from django.urls import path

from .views import (
    ChangePasswordView,
    LoginView,
    LogoutView,
    TokenRefreshView,
    UserCreateView,
    UserListView,
    UserProfileView,
)

app_name = "accounts"

urlpatterns = [
    path("api/v1/auth/login/", LoginView.as_view(), name="login"),
    path("api/v1/auth/logout/", LogoutView.as_view(), name="logout"),
    path("api/v1/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/v1/auth/me/", UserProfileView.as_view(), name="profile"),
    path("api/v1/auth/change-password/", ChangePasswordView.as_view(), name="change_password"),
    path("api/v1/users/", UserListView.as_view(), name="user_list"),
    path("api/v1/users/create/", UserCreateView.as_view(), name="user_create"),
]

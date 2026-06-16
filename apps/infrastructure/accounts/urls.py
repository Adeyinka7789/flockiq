from django.urls import path

from .views import (
    ChangePasswordView,
    DeactivateUserView,
    DismissStaffOnboardingView,
    EditProfileView,
    EditUserRoleView,
    ForgotPasswordView,
    InviteUserView,
    LoginView,
    LogoutView,
    NotificationPreferencesView,
    ProfilePageView,
    ReactivateUserView,
    ResendVerificationView,
    ResetPasswordView,
    TeamListView,
    TokenRefreshView,
    UserCreateView,
    UserListView,
    UserProfileView,
    VerifyEmailSentView,
    VerifyEmailView,
    WebChangePasswordView,
    delete_account,
    export_data,
)

app_name = "accounts"

urlpatterns = [
    path("api/v1/auth/login/", LoginView.as_view(), name="login"),
    path("api/v1/auth/logout/", LogoutView.as_view(), name="logout"),
    path("api/v1/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/v1/auth/me/", UserProfileView.as_view(), name="api_profile"),
    path("api/v1/auth/change-password/", ChangePasswordView.as_view(), name="api_change_password"),
    path("api/v1/users/", UserListView.as_view(), name="user_list"),
    path("api/v1/users/create/", UserCreateView.as_view(), name="user_create"),
    path("profile/", ProfilePageView.as_view(), name="profile"),
    path(
        "settings/notifications/",
        NotificationPreferencesView.as_view(),
        name="notification_preferences",
    ),
    path("profile/edit/", EditProfileView.as_view(), name="edit_profile"),
    path("profile/change-password/", WebChangePasswordView.as_view(), name="change_password"),
    # NDPR compliance
    path("export-data/", export_data, name="export_data"),
    path("delete-account/", delete_account, name="delete_account"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot_password"),
    path("reset-password/", ResetPasswordView.as_view(), name="reset_password"),
    path("accounts/verify/<uuid:token>/", VerifyEmailView.as_view(), name="verify_email"),
    path("accounts/verify-sent/", VerifyEmailSentView.as_view(), name="verify_email_sent"),
    path("accounts/resend-verification/", ResendVerificationView.as_view(), name="resend_verification"),
    # Team management
    path("team/", TeamListView.as_view(), name="team"),
    path("team/invite/", InviteUserView.as_view(), name="team_invite"),
    path("team/<uuid:pk>/role/", EditUserRoleView.as_view(), name="team_role"),
    path("team/<uuid:pk>/deactivate/", DeactivateUserView.as_view(), name="team_deactivate"),
    path("team/<uuid:pk>/reactivate/", ReactivateUserView.as_view(), name="team_reactivate"),
    # Staff onboarding tour
    path(
        "onboarding/staff/dismiss/",
        DismissStaffOnboardingView.as_view(),
        name="dismiss_staff_onboarding",
    ),
]

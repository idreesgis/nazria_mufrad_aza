from django.urls import path

from . import apple_web, views

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view(), name="auth-register"),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/refresh/", views.RefreshView.as_view(), name="auth-refresh"),
    path("auth/social/<str:provider>/", views.SocialLoginView.as_view(), name="auth-social"),
    path("auth/google/", views.GoogleLoginView.as_view(), name="auth-google"),          # older route
    path("auth/apple/start/", apple_web.start, name="auth-apple-start"),
    path("auth/apple/callback/", apple_web.callback, name="auth-apple-callback"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("me/", views.MeView.as_view(), name="me"),
    path("me/password/", views.PasswordView.as_view(), name="me-password"),
    path("me/social/<str:provider>/", views.SocialLinkView.as_view(), name="me-social"),
    path("me/google/", views.GoogleLinkView.as_view(), name="me-google"),               # older route
]

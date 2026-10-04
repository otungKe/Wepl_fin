from django.urls import path

from . import views

urlpatterns = [
    path("sign-in", views.sign_in),
    path("password", views.change_password),
    path("authenticator/begin", views.begin_enrolment),
    path("authenticator/confirm", views.confirm_enrolment),
    path("code", views.enter_code),
    path("step-up", views.step_up),
    path("sign-out", views.sign_out),
    path("me", views.me),
]

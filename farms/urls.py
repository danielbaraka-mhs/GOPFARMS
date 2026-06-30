from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("categories/", views.categories, name="categories"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("trackoder/", views.trackoder, name="trackoder"),
]

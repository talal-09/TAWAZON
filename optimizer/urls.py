from django.urls import path

from . import views


app_name = 'optimizer'

urlpatterns = [
    path('', views.home, name='home'),
]

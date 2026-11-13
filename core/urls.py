from django.urls import path

from . import views


app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('login/', views.sign_in, name='login'),
    path('logout/', views.sign_out, name='logout'),
]

from django.urls import path

from . import views


app_name = 'optimizer'

urlpatterns = [
    path('', views.home, name='home'),
    path('export/<int:run_id>/', views.export_csv, name='export_csv'),
]

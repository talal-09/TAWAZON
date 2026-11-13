from django.urls import path

from . import views


app_name = 'academics'

urlpatterns = [
    path('', views.home, name='home'),
    path('courses/new/', views.course_create, name='course_create'),
    path('courses/<int:course_id>/edit/', views.course_edit, name='course_edit'),
    path('courses/<int:course_id>/delete/', views.course_delete, name='course_delete'),
]

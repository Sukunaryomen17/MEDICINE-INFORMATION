# MediData/urls.py
from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='MediData/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('analyse/', views.analyse_pdf, name='analyse_pdf'),
    path('api/medicines/search/', views.api_search_medicines, name='api_search_medicines'),
    path('api/medicines/detail/', views.api_medicine_detail, name='api_medicine_detail'),
    path('api/history/', views.api_analysis_history, name='api_analysis_history'),
]


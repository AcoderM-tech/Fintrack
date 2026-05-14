from django.urls import path
from . import views

urlpatterns = [
    path('', views.account_list, name='account_list'),
    path('create/', views.account_create, name='account_create'),
    path('<int:pk>/edit/', views.account_edit, name='account_edit'),
    path('<int:pk>/delete/', views.account_delete, name='account_delete'),
    path('<int:pk>/', views.account_detail, name='account_detail'),
    path('api/list/', views.api_accounts, name='api_accounts'),
]

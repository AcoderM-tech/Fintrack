from django.urls import path
from . import views

urlpatterns = [
    path('', views.budget_list, name='budget_list'),
    path('create/', views.budget_create, name='budget_create'),
    path('<int:pk>/delete/', views.budget_delete, name='budget_delete'),
]

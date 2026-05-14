from django.urls import path
from . import views

urlpatterns = [
    path('', views.transaction_list, name='transaction_list'),
    path('create/', views.transaction_create, name='transaction_create'),
    path('<int:pk>/edit/', views.transaction_edit, name='transaction_edit'),
    path('<int:pk>/delete/', views.transaction_delete, name='transaction_delete'),
    path('calendar/', views.calendar_view, name='calendar'),
    path('api/suggest-category/', views.api_suggest_category, name='api_suggest_category'),
]

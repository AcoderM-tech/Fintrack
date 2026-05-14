from django.urls import path
from . import views

urlpatterns = [
    path('', views.debt_list, name='debt_list'),
    path('create/', views.debt_create, name='debt_create'),
    path('<int:pk>/payment/', views.debt_payment, name='debt_payment'),
    path('<int:pk>/close/', views.debt_close, name='debt_close'),
    path('<int:pk>/delete/', views.debt_delete, name='debt_delete'),
]

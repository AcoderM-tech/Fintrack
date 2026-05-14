from django.urls import path
from . import auth_views

urlpatterns = [
    path('register/', auth_views.register_view, name='register'),
]

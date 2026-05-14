from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing, name='landing'),
    path('set-language/', views.set_language, name='set_language'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('ai/', views.ai_assistant, name='ai_assistant'),
    path('ai/chat/', views.ai_chat, name='ai_chat'),
    path('profile/', views.profile_view, name='profile'),
    path('family/', views.family_view, name='family'),
    path('scope/', views.set_finance_scope, name='set_finance_scope'),
    path('family/stats/', views.family_member_stats, name='family_stats'),
]

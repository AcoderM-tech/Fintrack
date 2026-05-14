from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Dictionary dan key bo'yicha qiymat olish"""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None

@register.filter
def split(value, delimiter=","):
    """String ni bo'lish"""
    return value.split(delimiter)

@register.filter
def add_int(value, arg):
    """Integer qo'shish"""
    try:
        return int(value) + int(arg)
    except (ValueError, TypeError):
        return value

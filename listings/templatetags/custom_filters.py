# listings/templatetags/custom_filters.py
from django import template

register = template.Library()

@register.filter
def replace(value, arg):
    """Replace characters in string"""
    old, new = arg.split(',', 1)
    return value.replace(old, new)

@register.filter
def title_with_spaces(value):
    """Convert snake_case to Title Case with spaces"""
    return value.replace('_', ' ').title()
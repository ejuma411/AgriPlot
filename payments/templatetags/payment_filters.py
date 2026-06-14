# payments/templatetags/payment_filters.py
from django import template
from decimal import Decimal

register = template.Library()

@register.filter
def multiply(value, arg):
    """Multiply the value by the argument"""
    try:
        if isinstance(value, str):
            value = Decimal(value)
        if isinstance(arg, str):
            arg = Decimal(arg)
        return value * arg
    except (ValueError, TypeError, Decimal.InvalidOperation):
        return 0

@register.filter
def percentage(value, arg):
    """Calculate percentage: value * (arg / 100)"""
    try:
        if isinstance(value, str):
            value = Decimal(value)
        if isinstance(arg, str):
            arg = Decimal(arg)
        return value * (arg / 100)
    except (ValueError, TypeError, Decimal.InvalidOperation):
        return 0
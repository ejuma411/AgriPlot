# listings/templatetags/custom_filters.py
from django import template

register = template.Library()


def _string_or_none(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None

@register.filter
def replace(value, arg):
    """Replace characters in string"""
    old, new = arg.split(',', 1)
    return value.replace(old, new)

@register.filter
def title_with_spaces(value):
    """Convert snake_case to Title Case with spaces"""
    return value.replace('_', ' ').title()


@register.filter
def display_name(value, fallback="there"):
    """Safely render a user-like object's username first, then email."""
    if value is None:
        return fallback
    if isinstance(value, str):
        return _string_or_none(value) or fallback

    username = _string_or_none(getattr(value, "username", None))
    if username:
        return username

    email = _string_or_none(getattr(value, "email", None))
    if email:
        return email

    nested_user = getattr(value, "user", None)
    if nested_user is not None and nested_user is not value:
        return display_name(nested_user, fallback)

    return fallback


@register.filter
def display_initial(value, fallback="?"):
    """Safely render the first initial from a user-like object."""
    name = display_name(value, "")
    if not name:
        return fallback
    return name[:1].upper()


@register.filter
def contact_email(value, fallback=""):
    """Safely read a user-like object's email address."""
    if value is None:
        return fallback
    if isinstance(value, str):
        return _string_or_none(value) or fallback

    email = _string_or_none(getattr(value, "email", None))
    if email:
        return email

    nested_user = getattr(value, "user", None)
    if nested_user is not None and nested_user is not value:
        return contact_email(nested_user, fallback)

    return fallback

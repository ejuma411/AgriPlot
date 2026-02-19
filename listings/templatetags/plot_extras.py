# listings/templatetags/plot_extras.py
from django import template
import re

register = template.Library()

@register.filter
def get_doc_exists(docs, doc_type):
    return docs.filter(doc_type=doc_type).exists()

def split(value, delimiter=','):
    return value.split(delimiter)


@register.filter
def intcomma(value):
    """
    Convert an integer to a string containing commas every three digits.
    For example, 3000 becomes '3,000' and 45000 becomes '45,000'.
    """
    if value is None:
        return ''
    
    try:
        # Convert to string and remove any existing formatting
        value = str(value)
        
        # Handle negative numbers
        sign = ''
        if value.startswith('-'):
            sign = '-'
            value = value[1:]
        
        # Split decimal part if exists
        if '.' in value:
            whole, decimal = value.split('.')
            decimal = '.' + decimal
        else:
            whole, decimal = value, ''
        
        # Add commas to the whole number part
        result = re.sub(r'(\d)(?=(\d{3})+(?!\d))', r'\1,', whole)
        
        return sign + result + decimal
    except (ValueError, TypeError):
        return value

@register.filter
def split(value, delimiter=','):
    """Split a string by delimiter"""
    if value:
        return [item.strip() for item in value.split(delimiter)]
    return []
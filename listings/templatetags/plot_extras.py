# listings/templatetags/plot_extras.py
from django import template
register = template.Library()

@register.filter
def get_doc_exists(docs, doc_type):
    return docs.filter(doc_type=doc_type).exists()

from django import template
register = template.Library()

@register.filter
def dict_key(d, key):
    if d and key in d:
        return d[key]
    return None
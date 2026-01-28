from django import template
register = template.Library()

@register.filter
def dict_key(d, key):
    try:
        # On force la clé en entier au cas où
        res = d.get(int(key))
        return res
    except (AttributeError, TypeError, KeyError, ValueError):
        return None
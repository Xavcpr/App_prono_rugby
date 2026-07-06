from django import template
register = template.Library()

@register.filter
def get_item(dictionary, key):
    if not dictionary:
        return None
    # On tente de récupérer avec la clé telle quelle, puis en string
    res = dictionary.get(key)
    if res is None:
        res = dictionary.get(str(key))
    return res


@register.filter
def get_attr(obj, attr_name):
    """Permet de récupérer un attribut d'un objet dynamiquement"""
    return getattr(obj, attr_name, None)

@register.filter
def get_item_from_coords(dictionary, key):
    # Comme notre clé dans la vue est un tuple (x, y), on va simplifier 
    # en passant d'abord x puis y
    return dictionary.get(key)

@register.filter
def get_dict_item(dictionary, key):
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None
@register.filter
def dict_key(d, key):
    try:
        res = d.get(int(key))
        return res
    except (AttributeError, TypeError, KeyError, ValueError):
        return None

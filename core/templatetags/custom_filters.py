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
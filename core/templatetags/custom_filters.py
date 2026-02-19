from django import template
register = template.Library()

@register.filter
def get_item(dictionary, key):
    if dictionary is None: # Sécurité si l'élément précédent a renvoyé None
        return None
    return dictionary.get(str(key)) # On force str(key) car les clés JSON sont des strings


@register.filter
def get_attr(obj, attr_name):
    """Permet de récupérer un attribut d'un objet dynamiquement"""
    return getattr(obj, attr_name, None)
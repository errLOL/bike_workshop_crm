from django import template

register = template.Library()


@register.simple_tag
def is_admin(user):
    return user.is_superuser or user.groups.filter(name='Admin').exists()


@register.simple_tag
def is_technician(user):
    return user.groups.filter(name='Technician').exists()
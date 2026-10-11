from django import template

register = template.Library()

@register.filter
def pretty_changes(changes):
    if not changes:
        return '—'

    lines = []
    for field, diff in changes.items():
        if isinstance(diff, dict) and (
            'old' in diff or 'new' in diff
            or diff.get('added') or diff.get('deleted')
        ):
            if diff.get('deleted'):
                name = diff.get('product_name') or diff.get('name') or field
                lines.append(f"❌ Удалено: {name} в количестве {diff.get('quantity')}")
            elif diff.get('added'):
                name = diff.get('product_name') or diff.get('name') or field
                quantity = diff.get('quantity')
                unit_price = diff.get('unit_price')
                lines.append(f"✅ Добавлено: {name} в количестве {quantity} ({unit_price} Р)")
            else:
                lines.append(f"{field}: {diff.get('old')} → {diff.get('new')}")
            continue

    old_style = {
        k: v for k, v in changes.items()
        if not (isinstance(v, dict) and (
            'old' in v or 'new' in v
            or v.get('added') or v.get('deleted')
        ))
    }
    if old_style:
        used = set()
        for key in old_style:
            if key in used:
                continue
            if key.startswith('old_'):
                base = key[4:]
                new_key = f'new_{base}'
                if new_key in old_style:
                    lines.append(
                        f"{base}: {old_style[key]} → {old_style[new_key]}"
                    )
                    used.add(key)
                    used.add(new_key)
                    continue
            lines.append(f"{key}: {old_style[key]}")
            used.add(key)

    return ';\n'.join(lines)
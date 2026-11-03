from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()

_UNITS = {
    1: 'один', 2: 'два', 3: 'три', 4: 'четыре', 5: 'пять',
    6: 'шесть', 7: 'семь', 8: 'восемь', 9: 'девять',
}
_UNITS_F = {1: 'одна', 2: 'две'}
_TEENS = {
    10: 'десять', 11: 'одиннадцать', 12: 'двенадцать', 13: 'тринадцать',
    14: 'четырнадцать', 15: 'пятнадцать', 16: 'шестнадцать',
    17: 'семнадцать', 18: 'восемнадцать', 19: 'девятнадцать',
}
_TENS = {
    2: 'двадцать', 3: 'тридцать', 4: 'сорок', 5: 'пятьдесят',
    6: 'шестьдесят', 7: 'семьдесят', 8: 'восемьдесят', 9: 'девяносто',
}
_HUNDREDS = {
    1: 'сто', 2: 'двести', 3: 'триста', 4: 'четыреста', 5: 'пятьсот',
    6: 'шестьсот', 7: 'семьсот', 8: 'восемьсот', 9: 'девятьсот',
}


def _triad_to_words(n, feminine=False):
    """0..999 -> список слов."""
    words = []
    if n == 0:
        return words
    h = n // 100
    rem = n % 100
    if h:
        words.append(_HUNDREDS[h])
    if rem:
        if 10 <= rem <= 19:
            words.append(_TEENS[rem])
        else:
            t = rem // 10
            u = rem % 10
            if t:
                words.append(_TENS[t])
            if u:
                if feminine and u in _UNITS_F:
                    words.append(_UNITS_F[u])
                else:
                    words.append(_UNITS[u])
    return words


def _plural_form(n, forms):
    """forms = (one, few, many)."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return forms[2]
    n = n % 10
    if n == 1:
        return forms[0]
    if 2 <= n <= 4:
        return forms[1]
    return forms[2]


def _int_to_words(n, feminine=False):
    if n == 0:
        return 'ноль'
    parts = []
    ranks = (
        (10**9, ('миллиард', 'миллиарда', 'миллиардов'), False),
        (10**6, ('миллион', 'миллиона', 'миллионов'), False),
        (10**3, ('тысяча', 'тысячи', 'тысяч'), True),
        (1,     ('', '', ''), False),
    )
    for div, forms, fem in ranks:
        if n >= div:
            cnt = n // div
            n = n % div
            if div == 1:
                parts.extend(_triad_to_words(cnt, feminine=feminine))
            else:
                parts.extend(_triad_to_words(cnt, feminine=fem))
                parts.append(_plural_form(cnt, forms))
    return ' '.join(parts)


@register.filter
def amount_in_words(value):
    """1234.56 -> 'Одна тысяча двести тридцать четыре рубля 56 копеек'."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return ''
    negative = d < 0
    d = abs(d).quantize(Decimal('0.01'))
    rub = int(d)
    kop = int((d - rub) * 100)
    rub_words = _int_to_words(rub)
    rub_form = _plural_form(rub, ('рубль', 'рубля', 'рублей'))
    kop_words = _int_to_words(kop, feminine=True)
    kop_form = _plural_form(kop, ('копейка', 'копейки', 'копеек'))
    result = f'{rub_words} {rub_form} {kop:02d} {kop_form}'
    if negative:
        result = 'минус ' + result
    return result[0].upper() + result[1:]
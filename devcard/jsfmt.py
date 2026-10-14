"""Number and string formatting that matches what the TypeScript renderer prints.

The Python renderer is held to golden SVGs produced by the Worker's renderer
(tests/golden/), so every number has to come out exactly as JavaScript would
write it. Python's defaults differ in four places that matter here:

- ``str(6.0)`` is ``"6.0"``; JavaScript's ``String(6)`` is ``"6"``.
- ``round()`` rounds half to even; ``Math.round`` rounds half up.
- ``format(x, ".1f")`` rounds half to even; ``toFixed`` rounds the exact binary
  value half up.
- ``len()`` counts code points; ``String.prototype.length`` counts UTF-16 code
  units, so an emoji is 2 there. Text widths are estimated from it.
"""
from decimal import ROUND_HALF_UP, Decimal
import math


def num(x):
    """``String(x)`` for a JavaScript number."""
    if isinstance(x, bool):
        raise TypeError("a bool is not a number here")
    if isinstance(x, int):
        return str(x)
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x.is_integer() and abs(x) < 1e21:
        return str(int(x))
    text = repr(x)
    if "e" not in text:
        return text
    # Python switches to exponent notation at 1e16 / 1e-4, JavaScript at
    # 1e21 / 1e-6. Both print the shortest round-tripping digits.
    if 1e-6 <= abs(x) < 1e21:
        return format(Decimal(text), "f")
    mantissa, exponent = text.split("e")
    exp = int(exponent)
    return f"{mantissa}e{'+' if exp > 0 else '-'}{abs(exp)}"


def to_fixed(x, digits):
    """``x.toFixed(digits)``: the exact value rounded half up."""
    if x == 0:
        x = 0  # (-0).toFixed() has no sign; (-0.001).toFixed(2) keeps it
    quantum = Decimal(1).scaleb(-digits)
    return format(Decimal(x).quantize(quantum, rounding=ROUND_HALF_UP), "f")


def js_round(x):
    """``Math.round``: half rounds towards +infinity."""
    floor = math.floor(x)
    return floor + 1 if x - floor >= 0.5 else floor


def js_len(text):
    """``text.length`` — UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def js_slice(text, end):
    """``text.slice(0, end)`` in UTF-16 code units. A split surrogate pair is dropped."""
    return text.encode("utf-16-le")[: 2 * max(0, end)].decode("utf-16-le", errors="ignore")


def en_us(n):
    """``n.toLocaleString("en-US")`` for an integer."""
    return f"{int(n):,}"

import os
import qrcode
from io import BytesIO


def generate_qr(text: str, output_path: str = "qrcode.png", box_size: int = 10) -> str:
    qr = qrcode.QRCode(box_size=box_size, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(output_path)
    return output_path


def generate_qr_bytes(text: str, box_size: int = 10) -> bytes:
    qr = qrcode.QRCode(box_size=box_size, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


UNIT_CONVERSIONS = {
    "length": {
        "meter": 1.0, "kilometer": 1000.0, "centimeter": 0.01,
        "millimeter": 0.001, "mile": 1609.344, "yard": 0.9144,
        "foot": 0.3048, "inch": 0.0254,
    },
    "weight": {
        "kilogram": 1.0, "gram": 0.001, "milligram": 0.000001,
        "pound": 0.453592, "ounce": 0.0283495, "ton": 1000.0,
    },
    "temperature": {
        "celsius": "c", "fahrenheit": "f", "kelvin": "k",
    },
    "data": {
        "byte": 1, "kilobyte": 1024, "megabyte": 1048576,
        "gigabyte": 1073741824, "terabyte": 1099511627776,
    },
    "speed": {
        "m/s": 1.0, "km/h": 0.277778, "mph": 0.44704,
        "knot": 0.514444, "ft/s": 0.3048,
    },
    "area": {
        "sq_meter": 1.0, "sq_kilometer": 1000000.0,
        "sq_mile": 2589988.11, "sq_yard": 0.836127,
        "sq_foot": 0.092903, "acre": 4046.86, "hectare": 10000.0,
    },
    "volume": {
        "liter": 1.0, "milliliter": 0.001, "gallon": 3.78541,
        "quart": 0.946353, "pint": 0.473176, "cup": 0.236588,
        "tablespoon": 0.0147868, "teaspoon": 0.00492892,
        "cubic_meter": 1000.0, "cubic_foot": 28.3168,
    },
}


def convert_unit(value: float, from_unit: str, to_unit: str, category: str = None) -> float:
    if category is None:
        for cat, units in UNIT_CONVERSIONS.items():
            if from_unit in units and to_unit in units:
                category = cat
                break
        if category is None:
            raise ValueError(f"Unknown units: {from_unit}, {to_unit}")

    units = UNIT_CONVERSIONS[category]

    if category == "temperature":
        return _convert_temperature(value, from_unit, to_unit)

    base = value * units[from_unit]
    return base / units[to_unit]


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    if from_unit == to_unit:
        return value
    if from_unit == "celsius":
        kelvin = value + 273.15
    elif from_unit == "fahrenheit":
        kelvin = (value - 32) * 5 / 9 + 273.15
    elif from_unit == "kelvin":
        kelvin = value
    else:
        raise ValueError(f"Unknown temp unit: {from_unit}")
    if to_unit == "celsius":
        return kelvin - 273.15
    elif to_unit == "fahrenheit":
        return (kelvin - 273.15) * 9 / 5 + 32
    elif to_unit == "kelvin":
        return kelvin
    raise ValueError(f"Unknown temp unit: {to_unit}")


import ast
import operator

def safe_eval(expr_str: str) -> float:
    # Supported operators
    ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        elif isinstance(node, ast.BinOp):
            return ops[type(node.op)](_eval(node.left), _eval(node.right))
        elif isinstance(node, ast.UnaryOp):
            return ops[type(node.op)](_eval(node.operand))
        else:
            raise TypeError(node)
            
    tree = ast.parse(expr_str, mode='eval')
    return _eval(tree.body)

def calculate(expression: str) -> str:
    allowed = set("0123456789+-*/.()% ")
    if not all(c in allowed for c in expression):
        return "Invalid characters"
    try:
        result = safe_eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {e}"


def programmer_calc(value: str, from_base: str, to_base: str) -> str:
    """Convert values between Dec, Bin, Hex, and Oct."""
    try:
        value = value.strip()
        if from_base == "dec": val = int(value)
        elif from_base == "bin": val = int(value, 2)
        elif from_base == "hex": val = int(value, 16)
        elif from_base == "oct": val = int(value, 8)
        else: return "Invalid base"
        
        if to_base == "dec": return str(val)
        elif to_base == "bin": return bin(val)[2:]
        elif to_base == "hex": return hex(val)[2:].upper()
        elif to_base == "oct": return oct(val)[2:]
        return "Invalid base"
    except Exception as e:
        return f"Error: {e}"


def save_note(text: str, filepath: str = None) -> str:
    if filepath is None:
        from datetime import datetime
        filepath = f"note_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(text)
    return filepath

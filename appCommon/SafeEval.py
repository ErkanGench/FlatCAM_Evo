# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# MIT Licence                                              #
# ##########################################################

"""
safe_eval(): the value of a text typed by the user or read from a file (a Gerber aperture macro, a project, the
preferences, the clipboard, the command line), without running code.

eval() was used for these texts: opening a Gerber or a project file made by someone else, or pasting text copied from
a web page, could run any Python code (e.g. __import__('os').system(...)). safe_eval() accepts what those texts are
meant to hold and nothing else:

- Python literals: numbers, strings, True / False / None, tuples, lists, dicts, sets
- arithmetic on numbers: + - * / // % **, unary + and -, parentheses (the entries accept "10/3", the Gerber macros
  "$1x0.5+0.1")

Anything else (names, calls, attributes, subscripts, comprehensions, lambdas...) raises ValueError, as does a
calculation that would take too long: an exponent above MAX_EXPONENT, or a product or power of integers that could
have more than MAX_INTEGER_BITS bits (refused before it is calculated).
"""

import ast
import operator

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
# a value is a short text; a long one is refused before it is parsed
MAX_LENGTH = 100000
# 9**9**9 would run for minutes
MAX_EXPONENT = 1000
# the exponent limit alone does not bound an integer: (2**1000)**1000 has 1000001 bits, ((2**1000)**1000)**1000 has
# 10**9 (about 10 s and 0.5 GB; with 3 instead of 2 more than 5 minutes). These texts hold coordinates, sizes and
# flags: a float ends at 1024 bits. Only * and ** can make an integer much larger than their operands (+ and - add
# 1 bit, // and % do not add any, << is refused).
MAX_INTEGER_BITS = 4096


def safe_eval(text):
    """
    :param text:    the text (str); a number is returned as it is
    :return:        its value
    :raises ValueError: if the text is not a literal or an arithmetic expression on numbers
    """
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return text
    if not isinstance(text, str):
        raise ValueError('safe_eval() needs a string, not %s' % type(text).__name__)
    if len(text) > MAX_LENGTH:
        raise ValueError('text too long to evaluate')
    try:
        tree = ast.parse(text.strip(), mode='eval')
        return _value(tree.body)
    except SyntaxError as err:
        raise ValueError('not a value: %r (%s)' % (text[:80], err.msg)) from None
    except (RecursionError, MemoryError):
        # a very deep expression ('-' * 99999 + '1') overflows the parser or the recursion of _value()
        raise ValueError('expression nested too deeply') from None


def _number(value):
    return isinstance(value, (int, float, complex)) and not isinstance(value, bool)


def _integer_bits(op, left, right):
    """
    The most bits that left <op> right can have, for 2 integers, without calculating it: a product has at most the
    sum of the bit lengths, a power at most the bit length times the exponent. 0 when the result does not grow: a
    product with 0, a power of 0, 1 or -1, an exponent of 0 (1) or below 0 (a float), the other operators.
    """
    if isinstance(op, ast.Mult) and left and right:
        return left.bit_length() + right.bit_length()
    if isinstance(op, ast.Pow) and right > 0 and abs(left) > 1:
        return left.bit_length() * right
    return 0


def _value(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(_value(e) for e in node.elts)
    if isinstance(node, ast.List):
        return [_value(e) for e in node.elts]
    if isinstance(node, ast.Set):
        return {_value(e) for e in node.elts}
    if isinstance(node, ast.Dict):
        if any(k is None for k in node.keys):
            raise ValueError('dict unpacking is not a value')
        return {_value(k): _value(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        operand = _value(node.operand)
        if not _number(operand):
            raise ValueError('unary %s of a %s' % (type(node.op).__name__, type(operand).__name__))
        return _UNARY[type(node.op)](operand)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _value(node.left), _value(node.right)
        if not (_number(left) and _number(right)):
            raise ValueError('arithmetic on a %s and a %s' % (type(left).__name__, type(right).__name__))
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ValueError('exponent too large')
        if isinstance(left, int) and isinstance(right, int) and _integer_bits(node.op, left, right) > MAX_INTEGER_BITS:
            raise ValueError('integer result too large')
        try:
            return _BINARY[type(node.op)](left, right)
        except (ZeroDivisionError, OverflowError, TypeError) as err:
            raise ValueError(str(err)) from None
    raise ValueError('not allowed in a value: %s' % type(node).__name__)

from typing import NamedTuple

import shc


class ExampleTupleInner(NamedTuple):
    a: float
    b: str


class ExampleTuple(NamedTuple):
    a: float
    c: ExampleTupleInner


var = shc.Variable(ExampleTuple)
var2 = shc.Variable(float)


async def some_function() -> None:
    SOME_A = 'a'
    var_field1: str = await var.field('a').read()  # type error expected
    var_field2: float = await var.field('a').read()  # ok
    var_field3: str = await var.field(SOME_A).read()  # cannot be detected, since field name is no str literal
    var_field4: str = await var.field('c').field('a').read()  # type error expected
    var_field5: float = await var.field('c').field('a').read()  # ok
    await var.field('x').read()  # attr error expected
    await var.field('c').field('x').read()  # attr error expected
    await var2.field('a').read()  # error expected

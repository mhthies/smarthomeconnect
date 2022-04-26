from typing import NamedTuple

import shc
import shc.misc


class ExampleTupleInner(NamedTuple):
    a: float
    b: str


class ExampleTuple(NamedTuple):
    a: float
    c: ExampleTupleInner


exchange = shc.misc.UpdateExchange(ExampleTuple)
exchange2 = shc.misc.UpdateExchange(float)


async def some_function() -> None:
    SOME_A = 'a'
    target = shc.Variable(str)
    await exchange.field('a').read()  # error expected (not a Readable object)
    exchange.field('a').subscribe(target, convert=convert_str)  # type error expected
    exchange.field('a').subscribe(target, convert=convert_float)  # ok
    exchange.field(SOME_A).subscribe(target, convert=convert_float)  # not checked, b/c arg is no str literal
    exchange.field('c').field('a').subscribe(target, convert=convert_str)  # type error expected
    exchange.field('c').field('a').subscribe(target, convert=convert_float)  # ok
    exchange.field('x').subscribe(target, convert=convert_float)  # attr error expected
    exchange.field('c').field('x').subscribe(target, convert=convert_float)  # attr error expected
    exchange2.field('a')  # error expected


def convert_str(x: str) -> str:
    return x


def convert_float(x: float) -> str:
    return str(x)

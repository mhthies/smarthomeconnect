import asyncio
import datetime
import unittest
import unittest.mock

from shc import variables, expressions
from shc.base import UninitializedError
from shc.expressions import not_, or_, and_, ExpressionHandler
from test._helper import async_test, ExampleWritable


class TestExpressions(unittest.TestCase):
    @async_test
    async def test_expression_1(self):
        var1 = variables.Variable(int, initial_value=5)
        var2 = variables.Variable(int, initial_value=7)
        expression = var1.EX + (-var2.EX)
        expression2 = expression > 5
        subscriber = ExampleWritable(int)
        expression.subscribe(subscriber)
        subscriber2 = ExampleWritable(bool)
        expression2.subscribe(subscriber2)

        self.assertEqual(-2, await expression.read())
        self.assertEqual(False, await expression2.read())

        await var1.write(15, [self])
        await asyncio.sleep(0.01)
        subscriber._write.assert_called_once_with(8, unittest.mock.ANY)
        subscriber2._write.assert_called_once_with(True, unittest.mock.ANY)

    @async_test
    async def test_expression_2(self):
        var1 = variables.Variable(float, initial_value=17.0)
        var2 = variables.Variable(int, initial_value=7)
        expression = (var2.EX * 10) // (var1.EX - 7)
        expression2: ExpressionHandler[bool] = expression > 5
        expression3 = not_(var1.EX < 10)
        assert isinstance(expression3, ExpressionHandler)
        expression4: ExpressionHandler[bool] = expression2.and_(expression3)

        self.assertEqual(7, await expression.read())
        self.assertEqual(True, await expression2.read())
        self.assertEqual(True, await expression3.read())
        self.assertEqual(True, await expression4.read())

    @async_test
    async def test_expression_3(self):
        var1 = variables.Variable(bool, initial_value=True)
        var2 = variables.Variable(int, initial_value=42)
        expression = or_(False, var1.EX)
        expression2 = 10 * var2.EX / 2
        expression3 = 320 / (10 - var2.EX)
        expression4 = and_(True, (8 + var2.EX == 50))

        assert isinstance(expression, ExpressionHandler)
        self.assertEqual(True, await expression.read())
        self.assertEqual(210, await expression2.read())
        self.assertEqual(-10.0, await expression3.read())
        assert isinstance(expression4, ExpressionHandler)
        self.assertEqual(True, await expression4.read())

    @async_test
    async def test_expression_4(self):
        var1 = variables.Variable(datetime.datetime, initial_value=datetime.datetime(1970, 1, 1))
        var2 = variables.Variable(int, initial_value=-21)
        expression = abs(var2.EX) % 7
        expression2 = datetime.datetime(1970, 1, 31) - var1.EX
        expression3 = 9 // expression

        self.assertEqual(3, await expression.read())
        self.assertEqual(datetime.timedelta(days=30), await expression2.read())
        self.assertEqual(3, await expression3.read())

    def test_type_errors(self):
        var1 = variables.Variable(bool, initial_value=True)
        var2 = variables.Variable(list, initial_value=[42])
        with self.assertRaises(TypeError):
            var1.EX + var2.EX
        with self.assertRaises(TypeError):
            5.5 + var2.EX
        with self.assertRaises(TypeError):
            var1.EX - var2.EX
        with self.assertRaises(TypeError):
            5.5 - var2.EX
        with self.assertRaises(TypeError):
            var2.EX * 5.5
        with self.assertRaises(TypeError):
            5.5 * var2.EX
        with self.assertRaises(TypeError):
            (- var2.EX)
        with self.assertRaises(TypeError):
            abs(var2.EX)
        with self.assertRaises(TypeError):
            var2.EX % 5
        with self.assertRaises(TypeError):
            5 % var2.EX
        with self.assertRaises(TypeError):
            var2.EX > var1.EX
        with self.assertRaises(TypeError):
            var2.EX < var1.EX
        with self.assertRaises(TypeError):
            var2.EX >= 5
        with self.assertRaises(TypeError):
            var2.EX <= 5
        with self.assertRaises(TypeError):
            var2.EX / var1.EX
        with self.assertRaises(TypeError):
            var2.EX // var1.EX
        with self.assertRaises(TypeError):
            5 / var2.EX
        with self.assertRaises(TypeError):
            5 // var2.EX

    @async_test
    async def test_expressions_concurrent_update(self) -> None:
        var1 = variables.Variable(int)
        var2 = variables.Variable(int).connect(var1.EX + 5)
        var1.connect(var2.EX - 5)

        await asyncio.gather(var1.write(42, []), var2.write(56, []))
        self.assertEqual(await var1.read(), await var2.read() - 5)

    @async_test
    async def test_ifthenelse_and_multiplexer(self) -> None:
        var1 = variables.Variable(int)
        var2 = variables.Variable(bool)

        ifthenelse = expressions.IfThenElse(var2, var1.EX + 5, 5)
        multiplexer = expressions.Multiplexer(var2, 5, var1.EX + 5)  # type: ignore  # Variable is used covariantly here

        subscriber1 = ExampleWritable(int).connect(ifthenelse)
        subscriber2 = ExampleWritable(int).connect(multiplexer)

        self.assertIs(ifthenelse.type, int)
        self.assertIs(multiplexer.type, int)

        with self.assertRaises(UninitializedError):
            await ifthenelse.read()
        with self.assertRaises(UninitializedError):
            await multiplexer.read()

        await var1.write(42, [self])
        await asyncio.sleep(0.01)
        subscriber1._write.assert_not_called()
        subscriber2._write.assert_not_called()

        await var2.write(True, [self])
        await asyncio.sleep(0.01)
        subscriber1._write.assert_called_once_with(47, unittest.mock.ANY)
        subscriber2._write.assert_called_once_with(47, unittest.mock.ANY)
        self.assertEqual(47, await ifthenelse.read())
        self.assertEqual(47, await multiplexer.read())

        await var2.write(False, [self])
        await asyncio.sleep(0.01)
        subscriber1._write.assert_called_with(5, unittest.mock.ANY)
        subscriber2._write.assert_called_with(5, unittest.mock.ANY)
        self.assertEqual(5, await ifthenelse.read())
        self.assertEqual(5, await multiplexer.read())

        await var1.write(20, [self])
        await asyncio.sleep(0.01)
        subscriber1._write.assert_called_with(5, unittest.mock.ANY)
        subscriber2._write.assert_called_with(5, unittest.mock.ANY)
        self.assertEqual(5, await ifthenelse.read())
        self.assertEqual(5, await multiplexer.read())

    @async_test
    async def test_expression_decorator(self) -> None:
        var1 = variables.Variable(int)
        var2 = variables.Variable(bool)

        @expressions.expression
        def test_1(a, b) -> int:
            return a + 5 if b else 5

        @expressions.expression
        def test_2(a, b) -> str:
            ret = "xx-{}".format(a)
            if b:
                ret += " (foo)"
            return ret

        test_1_inst = test_1(var1, var2)
        test_2_inst = test_2(var1, var2)

        self.assertIsInstance(test_1_inst, expressions.ExpressionBuilder)
        self.assertIsInstance(test_2_inst, expressions.ExpressionBuilder)
        self.assertIs(test_1_inst.type, int)
        self.assertIs(test_2_inst.type, str)
        subscriber1 = ExampleWritable(int).connect(test_1_inst)
        subscriber2 = ExampleWritable(str).connect(test_2_inst)

        await var1.write(42, [self])
        await asyncio.sleep(0.01)
        subscriber1._write.assert_not_called()
        subscriber2._write.assert_not_called()

        await var2.write(True, [self])
        await asyncio.sleep(0.01)
        subscriber1._write.assert_called_once_with(47, unittest.mock.ANY)
        subscriber2._write.assert_called_once_with("xx-42 (foo)", unittest.mock.ANY)
        self.assertEqual(47, await test_1_inst.read())
        self.assertEqual("xx-42 (foo)", await test_2_inst.read())

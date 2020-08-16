import datetime
import unittest
import unittest.mock

from shc import variables
from shc.expressions import not_
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
        subscriber._write.assert_called_once_with(8, unittest.mock.ANY)
        subscriber2._write.assert_called_once_with(True, unittest.mock.ANY)

    @async_test
    async def test_expression_2(self):
        var1 = variables.Variable(float, initial_value=17.0)
        var2 = variables.Variable(int, initial_value=7)
        expression = (var2.EX * 10) // (var1.EX - 7)
        expression2 = expression > 5
        expression3 = not_(var1.EX < 10)
        expression4 = expression2 and expression3

        self.assertEqual(7, await expression.read())
        self.assertEqual(True, await expression2.read())
        self.assertEqual(True, await expression3.read())
        self.assertEqual(True, await expression4.read())

    @async_test
    async def test_expression_3(self):
        var1 = variables.Variable(bool, initial_value=True)
        var2 = variables.Variable(int, initial_value=42)
        expression = False or var1.EX
        expression2 = 10 * var2.EX / 2
        expression3 = 320 / (10 - var2.EX)
        expression4 = True and (8 + var2.EX == 50)

        self.assertEqual(True, await expression.read())
        self.assertEqual(210, await expression2.read())
        self.assertEqual(-10.0, await expression3.read())
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

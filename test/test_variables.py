
import unittest
import unittest.mock
from typing import NamedTuple

from shc import variables, base, expressions
from ._helper import async_test, ExampleReadable, ExampleWritable, AsyncMock


class SimpleVariableTest(unittest.TestCase):

    @unittest.mock.patch('shc.variables.Variable._publish', new_callable=AsyncMock)
    @async_test
    async def test_basic_behaviour(self, publish_patch):
        var = variables.Variable(int)
        await var.write(42, [self])
        publish_patch.assert_called_once_with(42, [self])
        self.assertEqual(42, await var.read())

        publish_patch.reset_mock()
        await var.write(21, [self])
        publish_patch.assert_called_once_with(21, [self])
        self.assertEqual(21, await var.read())

        publish_patch.reset_mock()
        await var.write(21, [self])
        publish_patch.assert_not_called()

    @async_test
    async def test_static_initialization(self):
        var = variables.Variable(int)
        with self.assertRaises(base.UninitializedError):
            await var.read()

        var = variables.Variable(int, initial_value=42)
        self.assertEqual(42, await var.read())
        await var.write(21, [self])
        self.assertEqual(21, await var.read())

    @async_test
    async def test_read_initialization(self):
        var1 = variables.Variable(int)
        var2 = variables.Variable(int, initial_value=21)
        var3 = variables.Variable(int)
        source = ExampleReadable(int, 42)
        var1.set_provider(source)

        with self.assertRaises(base.UninitializedError):
            await var1.read()
        self.assertEqual(21, await var2.read())
        with self.assertRaises(base.UninitializedError):
            await var3.read()

        await variables.read_initialize_variables()
        self.assertEqual(42, await var1.read())
        self.assertEqual(21, await var2.read())
        with self.assertRaises(base.UninitializedError):
            await var3.read()

    @async_test
    async def test_expression_wrapper(self):
        var = variables.Variable(int, initial_value=42)
        wrapper = var.EX
        subscriber = ExampleWritable(int)
        wrapper.subscribe(subscriber)

        self.assertIsInstance(wrapper, expressions.ExpressionBuilder)
        self.assertEqual(42, await wrapper.read())
        await var.write(21, [self])
        subscriber._write.assert_called_with(21, [self, var])


class ExampleTupleType(NamedTuple):
    a: int
    b: float


class ExampleRecursiveTupleType(NamedTuple):
    a: ExampleTupleType
    b: int


class VariableFieldsTest(unittest.TestCase):
    @async_test
    async def test_field_subscribing(self):
        var = variables.Variable(ExampleTupleType)
        field_subscriber = ExampleWritable(int)
        var.a.subscribe(field_subscriber)

        with self.assertRaises(base.UninitializedError):
            await var.a.read()

        await var.write(ExampleTupleType(42, 3.1416), [self])
        self.assertEqual(42, await var.a.read())
        field_subscriber._write.assert_called_once_with(42, [self, var.a])

        field_subscriber._write.reset_mock()
        await var.write(ExampleTupleType(42, 2.719), [self])
        field_subscriber._write.assert_not_called()

    @async_test
    async def test_field_writing(self):
        var = variables.Variable(ExampleTupleType, name="A test variable")
        field_subscriber = ExampleWritable(int)
        other_field_subscriber = ExampleWritable(float)
        subscriber = ExampleWritable(ExampleTupleType)
        var.subscribe(subscriber)
        var.a.subscribe(field_subscriber)
        var.b.subscribe(other_field_subscriber)

        with self.assertRaises(base.UninitializedError):
            await var.a.write(21, [self])

        await var.write(ExampleTupleType(42, 3.1416), [self])

        subscriber._write.reset_mock()
        field_subscriber._write.reset_mock()
        other_field_subscriber._write.reset_mock()

        await var.a.write(21, [self])
        self.assertEqual(21, await var.a.read())
        subscriber._write.assert_called_once_with(ExampleTupleType(21, 3.1416), [self, var.a, var])
        field_subscriber._write.assert_called_once_with(21, [self, var.a, var.a])
        other_field_subscriber._write.assert_not_called()

    @async_test
    async def test_recursive_field_subscribing(self):
        var = variables.Variable(ExampleRecursiveTupleType)
        field_subscriber = ExampleWritable(int)
        var.a.a.subscribe(field_subscriber)

        with self.assertRaises(base.UninitializedError):
            await var.a.a.read()

        await var.write(ExampleRecursiveTupleType(ExampleTupleType(42, 3.1416), 7), [self])
        self.assertEqual(42, await var.a.a.read())
        field_subscriber._write.assert_called_once_with(42, [self, var.a.a])

        field_subscriber._write.reset_mock()
        await var.write(ExampleRecursiveTupleType(ExampleTupleType(42, 3.1416), 6), [self])
        await var.write(ExampleRecursiveTupleType(ExampleTupleType(42, 2.719), 6), [self])
        field_subscriber._write.assert_not_called()

    @async_test
    async def test_recursive_field_writing(self):
        var = variables.Variable(ExampleRecursiveTupleType)
        subscriber = ExampleWritable(ExampleRecursiveTupleType)
        intermediate_subscriber = ExampleWritable(ExampleTupleType)
        field_subscriber = ExampleWritable(int)
        other_field_subscriber = ExampleWritable(float)
        another_field_subscriber = ExampleWritable(int)
        var.subscribe(subscriber)
        var.a.subscribe(intermediate_subscriber)
        var.a.a.subscribe(field_subscriber)
        var.a.b.subscribe(other_field_subscriber)
        var.b.subscribe(another_field_subscriber)

        with self.assertRaises(base.UninitializedError):
            await var.a.a.write(21, [self])

        await var.write(ExampleRecursiveTupleType(ExampleTupleType(42, 3.1416), 7), [self])

        subscriber._write.reset_mock()
        intermediate_subscriber._write.reset_mock()
        field_subscriber._write.reset_mock()
        other_field_subscriber._write.reset_mock()
        another_field_subscriber._write.reset_mock()

        await var.a.a.write(21, [self])
        self.assertEqual(21, await var.a.a.read())
        self.assertEqual(ExampleTupleType(21, 3.1416), await var.a.read())
        subscriber._write.assert_called_once_with(ExampleRecursiveTupleType(ExampleTupleType(21, 3.1416), 7),
                                                  [self, var.a.a, var.a, var])
        intermediate_subscriber._write.assert_called_once_with(ExampleTupleType(21, 3.1416),
                                                               [self, var.a.a, var.a, var.a])
        field_subscriber._write.assert_called_once_with(21, [self, var.a.a, var.a, var.a.a])
        other_field_subscriber._write.assert_not_called()
        another_field_subscriber._write.assert_not_called()

    @async_test
    async def test_expression_wrapper(self):
        var = variables.Variable(ExampleTupleType, initial_value=ExampleTupleType(42, 3.1416))
        wrapper = var.a.EX
        subscriber = ExampleWritable(int)
        wrapper.subscribe(subscriber)

        self.assertIsInstance(wrapper, expressions.ExpressionBuilder)
        self.assertEqual(42, await wrapper.read())
        await var.a.write(21, [self])
        subscriber._write.assert_called_with(21, [self, var.a, var.a])

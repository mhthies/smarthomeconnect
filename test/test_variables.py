import asyncio
import unittest
import unittest.mock
import warnings
from pathlib import Path
from typing import NamedTuple

import mypy.api

from shc import variables, base, expressions
from ._helper import async_test, ExampleReadable, ExampleWritable, AsyncMock


class SimpleVariableTest(unittest.TestCase):

    @unittest.mock.patch('shc.variables.Variable._publish')
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
        await asyncio.sleep(0.01)
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
        var.field('a').subscribe(field_subscriber)

        with self.assertRaises(TypeError):
            var2 = variables.Variable(float)
            await var2.field('c')  # type: ignore

        with self.assertRaises(KeyError):
            await var.field('c')  # type: ignore

        with self.assertRaises(base.UninitializedError):
            await var.field('a').read()

        await var.write(ExampleTupleType(42, 3.1416), [self])
        self.assertEqual(42, await var.field('a').read())
        await asyncio.sleep(0.01)
        field_subscriber._write.assert_called_once_with(42, [self, var.field('a')])

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
        var.field('a').subscribe(field_subscriber)
        var.field('b').subscribe(other_field_subscriber)

        with self.assertRaises(base.UninitializedError):
            await var.field('a').write(21, [self])

        await var.write(ExampleTupleType(42, 3.1416), [self])
        await asyncio.sleep(0.01)

        subscriber._write.reset_mock()
        field_subscriber._write.reset_mock()
        other_field_subscriber._write.reset_mock()

        await var.field('a').write(21, [self])
        self.assertEqual(21, await var.field('a').read())
        await asyncio.sleep(0.01)
        subscriber._write.assert_called_once_with(ExampleTupleType(21, 3.1416), [self, var.field('a'), var])
        field_subscriber._write.assert_called_once_with(21, [self, var.field('a'), var.field('a')])
        other_field_subscriber._write.assert_not_called()

    @async_test
    async def test_recursive_field_subscribing(self):
        var = variables.Variable(ExampleRecursiveTupleType)
        field_subscriber = ExampleWritable(int)
        var.field('a').field('a').subscribe(field_subscriber)

        with self.assertRaises(KeyError):
            await var.field('a').field('c')  # type: ignore

        with self.assertRaises(base.UninitializedError):
            await var.field('a').field('a').read()

        await var.write(ExampleRecursiveTupleType(ExampleTupleType(42, 3.1416), 7), [self])
        self.assertEqual(42, await var.field('a').field('a').read())
        await asyncio.sleep(0.01)
        field_subscriber._write.assert_called_once_with(42, [self, var.field('a').field('a')])

        field_subscriber._write.reset_mock()
        await var.write(ExampleRecursiveTupleType(ExampleTupleType(42, 3.1416), 6), [self])
        await var.write(ExampleRecursiveTupleType(ExampleTupleType(42, 2.719), 6), [self])
        field_subscriber._write.assert_not_called()

    @async_test
    async def test_recursive_field_writing_legacy(self):
        var = variables.Variable(ExampleRecursiveTupleType)
        subscriber = ExampleWritable(ExampleRecursiveTupleType)
        intermediate_subscriber = ExampleWritable(ExampleTupleType)
        field_subscriber = ExampleWritable(int)
        other_field_subscriber = ExampleWritable(float)
        another_field_subscriber = ExampleWritable(int)

        with warnings.catch_warnings(record=True) as w:
            var.subscribe(subscriber)
            var.a.subscribe(intermediate_subscriber)
            var.a.a.subscribe(field_subscriber)
            var.a.b.subscribe(other_field_subscriber)
            var.b.subscribe(another_field_subscriber)
        self.assertGreaterEqual(len(w), 4)
        self.assertTrue(issubclass(w[0].category, DeprecationWarning))

        with warnings.catch_warnings(record=True):  # There seems to be a bug, that record=False breaks the catching
            with self.assertRaises(AttributeError):
                var_c = var.c
            with self.assertRaises(AttributeError):
                var_c = var.a.c

            with self.assertRaises(base.UninitializedError):
                await var.a.a.write(21, [self])

            await var.write(ExampleRecursiveTupleType(ExampleTupleType(42, 3.1416), 7), [self])
            await asyncio.sleep(0.01)

            subscriber._write.reset_mock()
            intermediate_subscriber._write.reset_mock()
            field_subscriber._write.reset_mock()
            other_field_subscriber._write.reset_mock()
            another_field_subscriber._write.reset_mock()

            await var.a.a.write(21, [self])
            self.assertEqual(21, await var.a.a.read())
            self.assertEqual(ExampleTupleType(21, 3.1416), await var.a.read())
            await asyncio.sleep(0.01)
            subscriber._write.assert_called_once_with(ExampleRecursiveTupleType(ExampleTupleType(21, 3.1416), 7),
                                                      [self, var.a.a, var.a, var])
            intermediate_subscriber._write.assert_called_once_with(
                ExampleTupleType(21, 3.1416), [self, var.a.a, var.a, var.a])
            field_subscriber._write.assert_called_once_with(21, [self, var.a.a, var.a, var.a.a])
            other_field_subscriber._write.assert_not_called()
            another_field_subscriber._write.assert_not_called()

    @async_test
    async def test_recursive_field_writing(self):
        var = variables.Variable(ExampleRecursiveTupleType)
        subscriber = ExampleWritable(ExampleRecursiveTupleType)
        intermediate_subscriber = ExampleWritable(ExampleTupleType)
        field_subscriber = ExampleWritable(int)
        other_field_subscriber = ExampleWritable(float)
        another_field_subscriber = ExampleWritable(int)
        var.subscribe(subscriber)
        var.field('a').subscribe(intermediate_subscriber)
        var.field('a').field('a').subscribe(field_subscriber)
        var.field('a').field('b').subscribe(other_field_subscriber)
        var.field('b').subscribe(another_field_subscriber)

        with self.assertRaises(base.UninitializedError):
            await var.field('a').field('a').write(21, [self])

        await var.write(ExampleRecursiveTupleType(ExampleTupleType(42, 3.1416), 7), [self])
        await asyncio.sleep(0.01)

        subscriber._write.reset_mock()
        intermediate_subscriber._write.reset_mock()
        field_subscriber._write.reset_mock()
        other_field_subscriber._write.reset_mock()
        another_field_subscriber._write.reset_mock()

        await var.field('a').field('a').write(21, [self])
        self.assertEqual(21, await var.field('a').field('a').read())
        self.assertEqual(ExampleTupleType(21, 3.1416), await var.field('a').read())
        await asyncio.sleep(0.01)
        subscriber._write.assert_called_once_with(ExampleRecursiveTupleType(ExampleTupleType(21, 3.1416), 7),
                                                  [self, var.field('a').field('a'), var.field('a'), var])
        intermediate_subscriber._write.assert_called_once_with(
            ExampleTupleType(21, 3.1416),
            [self, var.field('a').field('a'), var.field('a'), var.field('a')])
        field_subscriber._write.assert_called_once_with(
            21,
            [self, var.field('a').field('a'), var.field('a'), var.field('a').field('a')])
        other_field_subscriber._write.assert_not_called()
        another_field_subscriber._write.assert_not_called()

    @async_test
    async def test_expression_wrapper(self):
        var = variables.Variable(ExampleTupleType, initial_value=ExampleTupleType(42, 3.1416))
        wrapper = var.field('a').EX
        subscriber = ExampleWritable(int)
        wrapper.subscribe(subscriber)

        self.assertIsInstance(wrapper, expressions.ExpressionBuilder)
        self.assertEqual(42, await wrapper.read())
        await var.field('a').write(21, [self])
        await asyncio.sleep(0.01)
        subscriber._write.assert_called_with(21, [self, var.field('a'), var.field('a')])


class ConnectedVariablesTest(unittest.TestCase):
    @async_test
    async def test_simple_concurrent_update(self) -> None:
        var1 = variables.Variable(int)
        var2 = variables.Variable(int).connect(var1)

        await asyncio.gather(var1.write(42, []), var2.write(56, []))
        await asyncio.sleep(0.01)
        self.assertEqual(await var1.read(), await var2.read())

    @async_test
    async def test_concurrent_field_update_publishing(self) -> None:
        var1 = variables.Variable(ExampleTupleType)
        var2 = variables.Variable(ExampleTupleType).connect(var1)
        var3 = variables.Variable(int).connect(var2.field('a'))

        writable1 = ExampleWritable(int).connect(var1.field('a'))  # TODO add different delays
        writable3 = ExampleWritable(int).connect(var3)

        await asyncio.gather(var1.write(ExampleTupleType(42, 3.1416), []), var3.write(56, []))
        await asyncio.sleep(0.01)
        self.assertEqual(await var1.field('a').read(), await var3.read())

        self.assertLessEqual(writable1._write.call_count, 3)
        self.assertLessEqual(writable3._write.call_count, 3)
        # 1st arg of 2nd call shall be equal
        self.assertEqual(writable1._write.call_args[0][0], writable3._write.call_args[0][0])


class MyPyPluginTest(unittest.TestCase):
    def test_mypy_plugin(self) -> None:
        asset_dir = Path(__file__).parent / 'assets' / 'mypy_plugin_test'
        result = mypy.api.run(['--config-file',
                               str(asset_dir / 'mypy.ini'),
                               str(asset_dir / 'variable_typing_example.py')])
        self.assertIn("variable_typing_example.py:22: error", result[0])
        self.assertNotIn("variable_typing_example.py:23: error", result[0])
        self.assertIn("variable_typing_example.py:25: error", result[0])
        self.assertNotIn("variable_typing_example.py:26: error", result[0])
        self.assertIn("variable_typing_example.py:27: error", result[0])
        self.assertIn("variable_typing_example.py:28: error", result[0])
        self.assertIn("variable_typing_example.py:29: error", result[0])
        self.assertEqual(1, result[2])

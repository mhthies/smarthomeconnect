"""Test for the command binary interface."""
import asyncio
import unittest
import unittest.mock

from shc.interfaces import command
from test._helper import async_test, ExampleSubscribable, ExampleWritable


class CommandTest(unittest.TestCase):
    """Test cases for the command interface."""

    @async_test
    async def test_command(self) -> None:
        """Test the command interface."""
        timer_mock = ExampleSubscribable(type(None))

        with unittest.mock.patch('shc.interfaces.command.Every', return_value=timer_mock):
            command1 = command.Command("echo available")
            command2 = command.Command("echo not_available")
            command2 = command.Command("echo not_available")

        target_1 = ExampleWritable(str).connect(command1)
        target_2 = ExampleWritable(str).connect(command2)

        await timer_mock.publish(None, [self])
        await asyncio.sleep(1.0)

        target_1._write.assert_called_once_with("available", [command1])
        target_2._write.assert_called_once_with("not_available", [command2])

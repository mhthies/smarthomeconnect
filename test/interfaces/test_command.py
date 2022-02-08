"""Test for the command binary interface."""
import unittest
import unittest.mock

from shc.base import UninitializedError
from shc.interfaces import command
from test._helper import async_test


class CommandTest(unittest.TestCase):
    """Test cases for the command readable object."""

    @async_test
    async def test_command(self) -> None:
        """Test the command readable object."""

        command1 = command.Command(["echo", "Hello, World!"])
        command2 = command.Command("f=World; echo Hello, $f\\!", shell=True)
        command3 = command.Command("definitely-not-a-command-on-your-computer", shell=True)
        command4 = command.Command("definitely-not-a-command-on-your-computer", shell=True, check=True)

        self.assertEqual("Hello, World!", await command1.read())
        self.assertEqual("Hello, World!", await command2.read())
        self.assertEqual("", await command3.read())
        with self.assertRaises(UninitializedError):
            await command4.read()

    @async_test
    async def test_command_exit_code(self) -> None:
        command1 = command.CommandExitCode(["true"])
        command2 = command.CommandExitCode(["false"])
        command3 = command.CommandExitCode("definitely-not-a-command-on-your-computer", shell=True)

        self.assertEqual(0, await command1.read())
        self.assertEqual(1, await command2.read())
        self.assertNotEqual(0, await command3.read())

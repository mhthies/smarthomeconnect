"""Command interface."""
import asyncio
import datetime
import logging

from shc.base import Subscribable
from shc.timer import Every

logger = logging.getLogger(__name__)


class Command(Subscribable[str]):
    """
    A *Subscribable* object that periodically executes a given command and publishes the result.

    :param command: The command to execute incl. arguments and parameters.
    :param interval: The interval in which the command will be executed.
    """
    type = str

    def __init__(self, command: str, interval: datetime.timedelta = datetime.timedelta(seconds=5)):
        """Initalize the command interface."""
        super().__init__()
        self.command = command
        self._timer = Every(interval)
        self._timer.trigger(self._exec)

    async def _exec(self, _v, _o) -> None:
        """Execute the given command."""
        command_process = await asyncio.create_subprocess_shell(
            self.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        std_out, _std_err = await command_process.communicate()

        if _std_err is not None:
            return

        logger.debug("Command output: %s", std_out.decode())

        self._publish(std_out.strip().decode(), [])

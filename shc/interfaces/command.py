"""Command interface."""
import asyncio
import logging
from typing import List, Union, cast

from shc.base import Readable, UninitializedError

logger = logging.getLogger(__name__)


class Command(Readable[str]):
    """
    A *Readable* object that executes a (fixed) given command returns the result when being read.

    This *readable* object can easily be combined with the :class:`shc.misc.PeriodicReader` to periodically publish the
    command's output::

        # Publish "Hello, world!" every 5seconds (the hard way ;) )
        PeriodicReader(Command(['echo', 'Hello, world!']), datetime.timedelta(seconds=5))

    The parameters are similar to subprocess.run()'s:

    :param command: The command to execute incl. arguments and parameters. A single str, when `shell` is True, otherwise
        it should be list of the command and its individual command line arguments.
    :param shell: If True, the command will be within a shell, otherwise it will be started as a plain subprocess
    :param include_std_err: If True, stderr output from the command will be included in the output. This is similar to
        adding '2>&1' to your shell command
    :param check: If True, the exit code of the command will be checked the read() method raises an UninitializedError
        instead of returning the output of the command in case of a non-zero exit code.
    """
    type = str

    def __init__(self, command: Union[str, List[str]], shell=False, include_std_err=False, check=False):
        """Initalize the command interface."""
        super().__init__()
        self.command = command
        self.shell = shell
        assert isinstance(self.command, str) or not self.shell
        self.include_std_err = include_std_err
        self.check = check

    async def read(self) -> str:
        stderr = asyncio.subprocess.STDOUT if self.include_std_err else asyncio.subprocess.DEVNULL
        if self.shell:
            command = cast(str, self.command)
            command_process = await asyncio.create_subprocess_shell(command,
                                                                    stdout=asyncio.subprocess.PIPE,
                                                                    stderr=stderr)
        else:
            command_args = cast(List[str], self.command)
            command_process = await asyncio.create_subprocess_exec(*command_args,
                                                                   stdout=asyncio.subprocess.PIPE,
                                                                   stderr=stderr)

        std_out, _std_err = await command_process.communicate()
        if self.check:
            if command_process.returncode != 0:
                logger.warning("Subprocess %s returned non-zero exit code %s", self.command, command_process.returncode)
                raise UninitializedError()

        std_out_str = std_out.decode().strip()
        logger.debug("Command output: %s", std_out)
        return std_out_str


class CommandExitCode(Readable[int]):
    """
    A *Readable* object that executes a (fixed) given command returns the its exit code when being read.

    This *readable* object can easily be combined with the :class:`shc.misc.PeriodicReader` to periodically publish the
    command's exit code::

        # Publish 1 every 5seconds (the hard way ;) )
        PeriodicReader(Command(['false']), datetime.timedelta(seconds=5))

    The parameters are similar to subprocess.run()'s:

    :param command: The command to execute incl. arguments and parameters. A single str, when `shell` is True, otherwise
        it should be list of the command and its individual command line arguments.
    :param shell: If True, the command will be within a shell, otherwise it will be started as a plain subprocess
    """
    type = int

    def __init__(self, command: Union[str, List[str]], shell=False):
        """Initalize the command interface."""
        super().__init__()
        self.command = command
        self.shell = shell

    async def read(self) -> int:
        if self.shell:
            command = cast(str, self.command)
            command_process = await asyncio.create_subprocess_shell(command,
                                                                    stdout=asyncio.subprocess.DEVNULL,
                                                                    stderr=asyncio.subprocess.DEVNULL)
        else:
            command_args = cast(List[str], self.command)
            command_process = await asyncio.create_subprocess_exec(*command_args,
                                                                   stdout=asyncio.subprocess.DEVNULL,
                                                                   stderr=asyncio.subprocess.DEVNULL)

        result = await command_process.wait()
        return result

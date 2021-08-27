import asyncio
import datetime
import os
import re

from shc.base import Subscribable
from shc.timer import Every

WINDOWS = os.name == 'nt'


class Ping(Subscribable[bool]):
    """
    A simple *Subscribable* object that periodically checks a given network host to be alive, using the ping command,
    and publishes the result as a bool value.

    This can be used for a simple presence monitoring, e.g. by pinging your mobile phone in your local WiFi network.

    :param address: The network host to be checked. Can be any string that can be passed as the host argument to the
        `ping` command, i.e. an IPv4 address, an IPv6 address, a host name of a full-qualified domain name.
    :param interval: The interval in which the host state shall be checked by pinging it
    :param number: The number of ECHO requests to send each time. Passed to `ping` via the `-c` argument (resp. `-n` on
        Windows). The host is considered to be alive (= `True` is published) if any of the sent pings is successfully
        received.
    :param timeout: The timeout for each individual ECHO request in seconds, passed to `ping` via the `-W` argument
        (resp. `-w` on Windows)
    """
    type = bool
    RE_WIN_PING_TTL = re.compile(rb'TTL=\d+\s*\n')

    def __init__(self, address: str, interval: datetime.timedelta = datetime.timedelta(minutes=5), number: int = 5,
                 timeout: float = 1.0):
        super().__init__()
        self.address = address
        self.number = number
        self.timeout = timeout
        self._timer = Every(interval)
        self._timer.trigger(self._exec)

    async def _exec(self, _v, _o) -> None:
        ping_process = await asyncio.create_subprocess_exec(
            'ping',
            '-c' if not WINDOWS else '-n',
            str(self.number),
            '-W' if not WINDOWS else '-w',
            str(self.timeout) if not WINDOWS else str(round(self.timeout * 1000)),
            self.address,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        std_out, _std_err = await ping_process.communicate()
        if ping_process.returncode != 0:
            self._publish(False, [])
            return
        if WINDOWS and not self.RE_WIN_PING_TTL.search(std_out):
            self._publish(False, [])
            return
        self._publish(True, [])

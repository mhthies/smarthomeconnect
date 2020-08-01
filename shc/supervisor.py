import asyncio
import functools
import logging
import signal

logger = logging.getLogger(__name__)

_REGISTERED_INTERFACES = set()


def register_interface(interface):
    _REGISTERED_INTERFACES.add(interface)


async def run():
    logger.info("Starting up shc system ...")
    await asyncio.gather(*(interface.run() for interface in _REGISTERED_INTERFACES))


async def stop():
    logger.info("Shutting down interfaces ...")
    await asyncio.gather(*(interface.stop() for interface in _REGISTERED_INTERFACES))


def handle_signal(sig: int, loop: asyncio.AbstractEventLoop):
    logger.info("Got signal {}. Initiating shutdown ...".format(sig))
    loop.create_task(stop())


def main():
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, functools.partial(handle_signal, sig, loop))
    loop.run_until_complete(run())

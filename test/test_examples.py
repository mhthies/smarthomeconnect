import asyncio
import unittest

import shc


class TestUiShowcase(unittest.TestCase):
    def test_basic(self) -> None:
        # Automatically shutdown after one second
        async def shutdown() -> None:
            await asyncio.sleep(1)
            await shc.supervisor.stop()
        shc.supervisor.event_loop.create_task(shutdown())

        import example.ui_showcase  # type: ignore
        shc.main()


class TestUiLoggingShowcase(unittest.TestCase):
    def test_basic(self) -> None:
        # Automatically shutdown after one second
        async def shutdown() -> None:
            await asyncio.sleep(1)
            await shc.supervisor.stop()
        shc.supervisor.event_loop.create_task(shutdown())

        import example.ui_logging_showcase  # type: ignore
        shc.main()

import asyncio
import unittest

import shc


# Helper coroutine to trigger shutdown after one second automatically
async def shutdown() -> None:
    await asyncio.sleep(1)
    await shc.supervisor.stop()


class BasicTest(unittest.TestCase):
    def test_ui_showcase(self) -> None:
        shc.supervisor.event_loop.create_task(shutdown())
        import example.ui_showcase  # type: ignore
        shc.main()

    def test_ui_logging_showcase(self) -> None:
        shc.supervisor.event_loop.create_task(shutdown())

        import example.ui_logging_showcase  # type: ignore
        shc.main()

    def test_server_client_example(self) -> None:
        shc.supervisor.event_loop.create_task(shutdown())

        # The examples should actually be able to coexist in a single SHC instance
        import example.server_client.server  # type: ignore
        import example.server_client.client  # type: ignore
        shc.main()

    @classmethod
    def setUpClass(cls) -> None:
        shc.supervisor._REGISTERED_INTERFACES.clear()
        shc.timer.timer_supervisor.supervised_timers.clear()

    def tearDown(self) -> None:
        shc.supervisor._REGISTERED_INTERFACES.clear()
        shc.timer.timer_supervisor.supervised_timers.clear()

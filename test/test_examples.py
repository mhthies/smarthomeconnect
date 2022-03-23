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

    def test_tasmota_led_example(self) -> None:
        import example.tasmota_led_ir_with_ui  # type: ignore

    def test_telegram_example(self) -> None:
        import example.telegram  # type: ignore

    def test_pulseaudio_sink_example(self) -> None:
        import example.pulseaudio_sink  # type: ignore

    def test_custom_ui_widet_example(self) -> None:
        import example.custom_ui_widget.main  # type: ignore
        # TODO add selenium test for actual position of the indicator

    @classmethod
    def setUpClass(cls) -> None:
        shc.supervisor._REGISTERED_INTERFACES.clear()
        shc.timer.timer_supervisor.supervised_timers.clear()

    def tearDown(self) -> None:
        shc.supervisor._REGISTERED_INTERFACES.clear()
        shc.timer.timer_supervisor.supervised_timers.clear()

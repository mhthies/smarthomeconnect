import asyncio
import unittest

import shc


def run_shc_for_one_second() -> None:
    async def shutdown_after_one_second() -> None:
        await asyncio.sleep(1)
        await shc.supervisor.stop()

    async def main_task():
        asyncio.create_task(shutdown_after_one_second())
        await shc.supervisor.run()

    asyncio.run(main_task())


class BasicTest(unittest.TestCase):
    def test_ui_showcase(self) -> None:
        import example.ui_showcase  # type: ignore  # noqa: F401

        run_shc_for_one_second()

    def test_ui_logging_showcase(self) -> None:
        import example.ui_logging_showcase  # type: ignore  # noqa: F401

        run_shc_for_one_second()

    def test_server_client_example(self) -> None:
        # The examples should actually be able to coexist in a single SHC instance
        import example.server_client.client  # type: ignore  # noqa: F401
        import example.server_client.server  # type: ignore  # noqa: F401

        run_shc_for_one_second()

    def test_tasmota_led_example(self) -> None:
        import example.tasmota_led_ir_with_ui  # type: ignore  # noqa: F401

    def test_telegram_example(self) -> None:
        import example.telegram  # type: ignore  # noqa: F401

    def test_pulseaudio_sink_example(self) -> None:
        import example.pulseaudio_sink  # type: ignore  # noqa: F401

    def test_knx_specifics_example(self) -> None:
        import example.knx_specifics  # type: ignore  # noqa: F401

    def test_custom_ui_widet_example(self) -> None:
        import example.custom_ui_widget.main  # type: ignore  # noqa: F401
        # TODO add selenium test for actual position of the indicator

    def test_sun_position_weather_forecast_example(self) -> None:
        import example.sun_position_weather_forecast  # type: ignore  # noqa: F401

    @classmethod
    def setUpClass(cls) -> None:
        shc.supervisor._REGISTERED_INTERFACES.clear()
        shc.timer.timer_supervisor.supervised_timers.clear()

    def tearDown(self) -> None:
        shc.supervisor._REGISTERED_INTERFACES.clear()
        shc.timer.timer_supervisor.supervised_timers.clear()

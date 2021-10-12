import abc
import asyncio
import logging
from collections import defaultdict, deque
from typing import NamedTuple, List, Optional, Generic, Type, Any, DefaultDict, Tuple, Callable, Deque
import ctypes as c

from pulsectl import (  # type: ignore
    PulseEventInfo, PulseEventFacilityEnum, PulseEventTypeEnum, PulseSinkInfo, PulseSourceInfo, PulseServerInfo,
    PulseVolumeInfo, PulseStateEnum, PulseDisconnected)
from pulsectl_asyncio import PulseAsync  # type: ignore

import shc.conversion
from shc.base import Connectable, Subscribable, Readable, T, UninitializedError, Writable
from shc.datatypes import RangeFloat1, Balance
from shc.interfaces._helper import SupervisedClientInterface

logger = logging.getLogger(__name__)


class PulseVolumeRaw(NamedTuple):
    """
    TODO
    """
    values: list = []
    map: list = []


class PulseVolumeBalance(NamedTuple):
    """
    TODO

    .. warning:
        Conversion methods :meth:`as_channels` and :meth:`from_channels`, which are used as default converters into/from
        PulseVolumeRaw objects, require the libpulse shared library.
    """
    volume: RangeFloat1 = RangeFloat1(1.0)
    balance: Balance = Balance(0.0)
    fade: Balance = Balance(0.0)
    lfe_balance: Balance = Balance(0.0)
    normalized_values: list = []
    map: list = []

    def as_channels(self) -> PulseVolumeRaw:
        from pulsectl._pulsectl import PA_CVOLUME, PA_CHANNEL_MAP, PA_CHANNELS_MAX, PA_VOLUME_NORM  # type: ignore
        from shc.interfaces._pulse_ffi import pa_volume_t, pa_cvolume_set_lfe_balance, pa_cvolume_set_fade, \
            pa_cvolume_set_balance, pa_cvolume_scale  # type: ignore

        l = len(self.normalized_values)
        cvolume = PA_CVOLUME(l, (pa_volume_t * PA_CHANNELS_MAX)(*self.normalized_values))
        cmap = PA_CHANNEL_MAP(l, (c.c_int * PA_CHANNELS_MAX)(*self.map))
        pa_cvolume_set_lfe_balance(cvolume, cmap, self.lfe_balance)
        pa_cvolume_set_fade(cvolume, cmap, self.fade)
        pa_cvolume_set_balance(cvolume, cmap, self.balance)
        pa_cvolume_scale(cvolume, round(self.volume * PA_VOLUME_NORM))
        return PulseVolumeRaw([v / PA_VOLUME_NORM for v in cvolume.values[:cvolume.channels]], self.map)

    @classmethod
    def from_channels(cls, raw_volume: PulseVolumeRaw) -> "PulseVolumeBalance":
        from pulsectl._pulsectl import PA_CVOLUME, PA_CHANNEL_MAP, PA_CHANNELS_MAX, PA_VOLUME_NORM
        from shc.interfaces._pulse_ffi import pa_volume_t, pa_cvolume_set_lfe_balance, pa_cvolume_set_fade, \
            pa_cvolume_set_balance, pa_cvolume_scale, pa_cvolume_max, pa_cvolume_get_balance, pa_cvolume_get_fade, \
            pa_cvolume_get_lfe_balance

        l = len(raw_volume.values)
        cvolume = PA_CVOLUME(l, (pa_volume_t * PA_CHANNELS_MAX)(*(round(PA_VOLUME_NORM * v)
                                                                  for v in raw_volume.values)))
        cmap = PA_CHANNEL_MAP(l, (c.c_int * PA_CHANNELS_MAX)(*raw_volume.map))
        volume = pa_cvolume_max(cvolume) / PA_VOLUME_NORM
        pa_cvolume_scale(cvolume, PA_VOLUME_NORM)
        balance = pa_cvolume_get_balance(cvolume, cmap)
        pa_cvolume_set_balance(cvolume, cmap, 0.0)
        fade = pa_cvolume_get_fade(cvolume, cmap)
        pa_cvolume_set_fade(cvolume, cmap, 0.0)
        lfe_balance = pa_cvolume_get_lfe_balance(cvolume, cmap)
        pa_cvolume_set_lfe_balance(cvolume, cmap, 0.0)
        return cls(RangeFloat1(volume), Balance(balance), Balance(fade), Balance(lfe_balance),
                   list(cvolume.values)[:l], raw_volume.map)


shc.conversion.register_converter(PulseVolumeRaw, PulseVolumeBalance, PulseVolumeBalance.from_channels)
shc.conversion.register_converter(PulseVolumeBalance, PulseVolumeRaw, lambda v: v.as_channels())


class PulseAudioInterface(SupervisedClientInterface):
    """
    Interface for controlling a Pulseaudio server and receiving status feedback, esp. sink and source volumes, muting,
    and level monitoring.

    :param pulse_client_name: Client name reported to the Pulseaudio server when connecting.
    :param pulse_server_socket: Address of the Pulseaudio server socket, e.g. "unix:/run/user/1000/pulse/native". If not
        specified or None, the system default Pulseaudio instance is used.
    :param auto_reconnect: If True (default), the interface tries to reconnect automatically with
        exponential backoff (1.25 ^ n seconds sleep), when the Pulseaudio event subscription exits unexpectedly, e.g.
        due to a connection loss with the Pulseaudio server. Otherwise, the complete SHC system is shut down on
        such errors.
    :param failsafe_start: If True and auto_reconnect is True, the interface allows SHC to start up, even if the
        connection and event subscription with the Pulseaudio server fails in the first try. The connection is retried
        in background with exponential backoff (see `auto_reconnect` option). Otherwise (default), the first connection
        attempt on startup is not retried and will raise an exception from `start()` on failure, even if
        `auto_reconnect` is True.
    """
    def __init__(self, pulse_client_name: str = "smarthomeconnect", pulse_server_socket: Optional[str] = None,
                 auto_reconnect: bool = True, failsafe_start: bool = False):
        super().__init__(auto_reconnect, failsafe_start)
        self.pulse = PulseAsync(pulse_client_name, server=pulse_server_socket)
        self.sink_connectors_by_id: DefaultDict[int, List["SinkConnector"]] = defaultdict(list)
        self.sink_connectors_by_name: DefaultDict[Optional[str], List["SinkConnector"]] = defaultdict(list)
        self.source_connectors_by_id: DefaultDict[int, List["SourceConnector"]] = defaultdict(list)
        self.source_connectors_by_name: DefaultDict[Optional[str], List["SourceConnector"]] = defaultdict(list)

        self._default_sink_name_connector = DefaultNameConnector(self.pulse, "default_sink_name")
        self._default_source_name_connector = DefaultNameConnector(self.pulse, "default_source_name")
        self._subscribe_server = False
        self._subscribe_sinks = False
        self._subscribe_sources = False

        # A dict for keeping track of the SHC value update origin of changes we are currently applying to the Pulseaudio
        # server, so that we can correctly apply the original origin list to the resulting Pulseaudio event
        self._change_event_origin: DefaultDict[Tuple[PulseEventFacilityEnum, int], Deque[List[Any]]] = defaultdict(deque)

    async def _connect(self) -> None:
        await self.pulse.connect()

    async def _disconnect(self) -> None:
        self.pulse.disconnect()

    async def _subscribe(self) -> None:
        server_info = await self.pulse.server_info()
        self._default_sink_name_connector._update(server_info, [])
        self._default_source_name_connector._update(server_info, [])
        for sink_info in await self.pulse.sink_list():
            sink_connectors = self.sink_connectors_by_name.get(sink_info.name, [])
            if sink_info.name == server_info.default_sink_name:
                sink_connectors += self.sink_connectors_by_name.get(None, [])
            if sink_connectors:
                logging.debug("Pulseaudio sink \"%s\" is already available. Mapping %s connectors to sink id %s",
                              sink_info.name, len(sink_connectors), sink_info.index)
            for connector in sink_connectors:
                try:
                    connector.change_id(sink_info.index)
                    self.sink_connectors_by_id[sink_info.index].append(connector)
                    connector.on_change(sink_info, [])
                except Exception as e:
                    logging.error("Error while initializing connector %s with current data of sink", connector,
                                  exc_info=e)
        for source_info in await self.pulse.source_list():
            source_connectors = self.source_connectors_by_name.get(source_info.name, [])
            if source_info.name == server_info.default_source_name:
                source_connectors += self.source_connectors_by_name.get(None, [])
            if source_connectors:
                logging.debug("Pulseaudio source \"%s\" is already available. Mapping %s connectors to source id %s",
                              source_info.name, len(source_connectors), source_info.index)
            for source_connector in source_connectors:
                try:
                    source_connector.current_id = source_info.index
                    self.source_connectors_by_id[source_info.index].append(source_connector)
                    source_connector.on_change(source_info, [])
                except Exception as e:
                    logging.error("Error while initializing connector %s with current data of source", source_connector,
                                  exc_info=e)

    async def _run(self) -> None:
        self._running.set()
        subscribe_facilities = []
        if self._subscribe_server:
            subscribe_facilities.append('server')
        if self._subscribe_sinks:
            subscribe_facilities.append('sink')
        if self._subscribe_sources:
            subscribe_facilities.append('source')
        async for event in self.pulse.subscribe_events(*subscribe_facilities):
            try:
                await self._dispatch_pulse_event(event)
            except Exception as e:
                logger.error("Error while dispatching PulseAudio event %s", event, exc_info=e)

    async def _dispatch_pulse_event(self, event: PulseEventInfo) -> None:
        logger.debug("Dispatching Pulse audio event: %s", event)
        if event.t is PulseEventTypeEnum.new:
            if event.facility is PulseEventFacilityEnum.sink:
                data = await self.pulse.sink_info(event.index)
                name = data.name
                for connector in self.sink_connectors_by_name.get(name, []):
                    connector.change_id(event.index)
                    self.sink_connectors_by_id[event.index].append(connector)
                    connector.on_change(data, [])
            elif event.facility is PulseEventFacilityEnum.source:
                data = await self.pulse.source_info(event.index)
                name = data.name
                for source_connector in self.source_connectors_by_name.get(name, []):
                    source_connector.change_id(event.index)
                    self.source_connectors_by_id[event.index].append(source_connector)
                    source_connector.on_change(data, [])

        elif event.t is PulseEventTypeEnum.remove:
            if event.facility is PulseEventFacilityEnum.sink:
                for connector in self.sink_connectors_by_id.get(event.index, []):
                    connector.change_id(None)
                if event.index in self.sink_connectors_by_id:
                    del self.sink_connectors_by_id[event.index]
            elif event.facility is PulseEventFacilityEnum.source:
                for source_connector in self.source_connectors_by_id.get(event.index, []):
                    source_connector.change_id(None)
                if event.index in self.source_connectors_by_id:
                    del self.source_connectors_by_id[event.index]

        elif event.t is PulseEventTypeEnum.change:
            # Check if the event has probably been caused by a value update from SHC. In this case, we should have the
            # original origin stored in self.event_origin and can apply it to the publishing of the event
            try:
                index = 0 if event.t == PulseEventFacilityEnum.server else event.index
                origin = self._change_event_origin[(event.facility, index)].popleft()
            except IndexError:
                origin = []

            if event.facility is PulseEventFacilityEnum.sink:
                data = await self.pulse.sink_info(event.index)
                for connector in self.sink_connectors_by_id.get(event.index, []):
                    connector.on_change(data, origin)
            elif event.facility is PulseEventFacilityEnum.source:
                data = await self.pulse.source_info(event.index)
                for source_connector in self.source_connectors_by_id.get(event.index, []):
                    source_connector.on_change(data, origin)

            elif event.facility is PulseEventFacilityEnum.server:
                # For server change events, we need to update our default_*_name connectors and possibly change the
                # current_id of all the default_sink/source_* connectors (and update them with the current state of the
                # new default sink/source)
                server_info = await self.pulse.server_info()
                self._default_sink_name_connector._update(server_info, origin)
                self._default_source_name_connector._update(server_info, origin)
                # Update default sink/source connectors
                default_sink_data = await self.pulse.get_sink_by_name(server_info.default_sink_name)
                default_source_data = await self.pulse.get_source_by_name(server_info.default_source_name)
                for connector in self.sink_connectors_by_name.get(None, []):
                    if connector.current_id is not None:
                        try:
                            self.sink_connectors_by_id[connector.current_id].remove(connector)
                        except ValueError:
                            pass
                    connector.change_id(default_sink_data.index)
                    self.sink_connectors_by_id[default_sink_data.index].append(connector)
                    connector.on_change(default_sink_data, [])  # should we set the original origin here?
                for source_connector in self.source_connectors_by_name.get(None, []):
                    if source_connector.current_id is not None:
                        try:
                            self.source_connectors_by_id[source_connector.current_id].remove(source_connector)
                        except ValueError:
                            pass
                    source_connector.change_id(default_source_data.index)
                    self.source_connectors_by_id[default_source_data.index].append(source_connector)
                    source_connector.on_change(default_source_data, [])  # should we set the original origin here?

    def _register_origin_callback(self, facility: PulseEventFacilityEnum, index: int, origin: List[Any]) -> None:
        subscribed_facilities = {PulseEventFacilityEnum.sink: self._subscribe_sinks,
                                 PulseEventFacilityEnum.source: self._subscribe_sources,
                                 PulseEventFacilityEnum.server: self._subscribe_server}
        # Avoid infinite growing of event_origin dict's lists, by adding origins of events that will never be
        # removed b/c we do not subscribe this kind of events.
        if not subscribed_facilities[facility]:
            return
        self._change_event_origin[(facility, index)].append(origin)

    def sink_volume(self, sink_name: str) -> "SinkVolumeConnector":
        self._subscribe_sinks = True
        connector = SinkVolumeConnector(self.pulse, self._register_origin_callback)
        self.sink_connectors_by_name[sink_name].append(connector)
        return connector

    def sink_muted(self, sink_name: str) -> "SinkMuteConnector":
        self._subscribe_sinks = True
        connector = SinkMuteConnector(self.pulse, self._register_origin_callback)
        self.sink_connectors_by_name[sink_name].append(connector)
        return connector

    def sink_running(self, sink_name: str) -> Readable[bool]:
        self._subscribe_sinks = True
        connector = SinkStateConnector(self.pulse)
        self.sink_connectors_by_name[sink_name].append(connector)
        return connector

    def sink_peak_monitor(self, sink_name: str, frequency: int = 1) -> "SinkPeakConnector":
        self._subscribe_sinks = True
        connector = SinkPeakConnector(self.pulse, frequency)
        self.sink_connectors_by_name[sink_name].append(connector)
        return connector

    def default_sink_volume(self) -> "SinkVolumeConnector":
        self._subscribe_server = True
        self._subscribe_sinks = True
        connector = SinkVolumeConnector(self.pulse, self._register_origin_callback)
        self.sink_connectors_by_name[None].append(connector)
        return connector

    def default_sink_muted(self) -> "SinkMuteConnector":
        self._subscribe_server = True
        self._subscribe_sinks = True
        connector = SinkMuteConnector(self.pulse, self._register_origin_callback)
        self.sink_connectors_by_name[None].append(connector)
        return connector

    def default_sink_running(self) -> Readable[bool]:
        self._subscribe_server = True
        self._subscribe_sinks = True
        connector = SinkStateConnector(self.pulse)
        self.sink_connectors_by_name[None].append(connector)
        return connector

    def default_sink_peak_monitor(self, frequency: int = 1) -> "SinkPeakConnector":
        self._subscribe_server = True
        connector = SinkPeakConnector(self.pulse, frequency)
        self.sink_connectors_by_name[None].append(connector)
        return connector

    def default_sink_name(self) -> "DefaultNameConnector":
        self._subscribe_server = True
        return self._default_sink_name_connector

    def source_volume(self, source_name: str) -> Connectable[PulseVolumeRaw]: ...  # TODO
    def source_muted(self, source_name: str) -> Connectable[bool]: ...  # TODO
    def source_running(self, source_name: str) -> Connectable[bool]: ...  # TODO

    def source_peak_monitor(self, source_name: str, frequency: int = 1) -> "SourcePeakConnector":
        self._subscribe_sources = True
        connector = SourcePeakConnector(self.pulse, frequency)
        self.source_connectors_by_name[source_name].append(connector)
        return connector

    def default_source_volume(self) -> Connectable[PulseVolumeRaw]: ...  # TODO
    def default_source_muted(self) -> Connectable[bool]: ...  # TODO
    def default_source_running(self) -> Connectable[bool]: ...  # TODO

    def default_source_peak_monitor(self, frequency: int = 1) -> "SourcePeakConnector":
        self._subscribe_server = True
        connector = SourcePeakConnector(self.pulse, frequency)
        self.source_connectors_by_name[None].append(connector)
        return connector

    def default_source_name(self) -> "DefaultNameConnector":
        self._subscribe_server = True
        return self._default_source_name_connector


class SinkConnector(metaclass=abc.ABCMeta):
    def __init__(self):
        super().__init__()
        self.current_id: Optional[int] = None

    def on_change(self, data: PulseSinkInfo, origin: List[Any]) -> None:
        pass

    def change_id(self, index: Optional[int]) -> None:
        self.current_id = index


class SourceConnector(metaclass=abc.ABCMeta):
    def __init__(self):
        super().__init__()
        self.current_id: Optional[int] = 0

    def on_change(self, data: PulseSourceInfo, origin: List[Any]) -> None:
        pass

    def change_id(self, index: Optional[int]) -> None:
        self.current_id = index


class SinkAttributeConnector(Subscribable[T], Readable[T], SinkConnector, Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, pulse: PulseAsync, type_: Type[T]):
        self.type = type_
        super().__init__()
        self.pulse = pulse

    def on_change(self, data: PulseSinkInfo, origin: List[Any]) -> None:
        self._publish(self._convert_from_pulse(data), origin)

    @abc.abstractmethod
    def _convert_from_pulse(self, data: PulseSinkInfo) -> T:
        pass

    async def read(self) -> T:
        if self.current_id is None:
            raise UninitializedError()
        data = await self.pulse.sink_info(self.current_id)
        return self._convert_from_pulse(data)


class SinkStateConnector(SinkAttributeConnector[bool]):
    def __init__(self, pulse: PulseAsync):
        super().__init__(pulse, bool)

    def _convert_from_pulse(self, data: PulseSinkInfo) -> bool:
        return data.state == PulseStateEnum.running

    def change_id(self, index: Optional[int]) -> None:
        super().change_id(index)
        if index is None:
            self._publish(False, [])


class SinkMuteConnector(SinkAttributeConnector[bool], Writable[bool]):
    def __init__(self, pulse: PulseAsync,
                 register_origin_callback: Callable[[PulseEventFacilityEnum, int, List[Any]], None]):
        super().__init__(pulse, bool)
        self.register_origin_callback = register_origin_callback

    def _convert_from_pulse(self, data: PulseSinkInfo) -> bool:
        return bool(data.mute)

    async def _write(self, value: T, origin: List[Any]) -> None:
        if self.current_id is None:
            raise RuntimeError("PulseAudio sink id for {} is currently not defined".format(repr(self)))
        self.register_origin_callback(PulseEventFacilityEnum.sink, self.current_id, origin)
        await self.pulse.sink_mute(self.current_id, value)


class SinkVolumeConnector(SinkAttributeConnector[PulseVolumeRaw], Writable[PulseVolumeRaw]):
    def __init__(self, pulse: PulseAsync,
                 register_origin_callback: Callable[[PulseEventFacilityEnum, int, List[Any]], None]):
        super().__init__(pulse, PulseVolumeRaw)
        self.register_origin_callback = register_origin_callback

    def _convert_from_pulse(self, data: PulseSinkInfo) -> PulseVolumeRaw:
        return PulseVolumeRaw(data.volume.values, data.channel_map)

    async def _write(self, value: PulseVolumeRaw, origin: List[Any]) -> None:
        if self.current_id is None:
            raise RuntimeError("PulseAudio sink id for {} is currently not defined".format(repr(self)))
        self.register_origin_callback(PulseEventFacilityEnum.sink, self.current_id, origin)
        await self.pulse.sink_volume_set(self.current_id, PulseVolumeInfo(value.values))


class SinkPeakConnector(SinkConnector, Subscribable[RangeFloat1]):
    type = RangeFloat1

    def __init__(self, pulse: PulseAsync, frequency: int):
        super().__init__()
        self.pulse = pulse
        self.frequency = frequency
        self.task: Optional[asyncio.Task] = None

    def change_id(self, index: Optional[int]) -> None:
        if self.task and index != self.current_id:
            self.task.cancel()
            self.task = None
        super().change_id(index)
        if index is not None and not self.task:
            self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        data = await self.pulse.sink_info(self.current_id)
        try:
            async for value in self.pulse.subscribe_peak_sample(data.monitor_source, self.frequency):
                self._publish(RangeFloat1(value), [])
        except (asyncio.CancelledError, PulseDisconnected):
            pass


class SourcePeakConnector(SourceConnector, Subscribable[RangeFloat1]):
    type = RangeFloat1

    def __init__(self, pulse: PulseAsync, frequency: int):
        super().__init__()
        self.pulse = pulse
        self.frequency = frequency
        self.task: Optional[asyncio.Task] = None

    def change_id(self, index: Optional[int]) -> None:
        if self.task and index != self.current_id:
            self.task.cancel()
            self.task = None
        super().change_id(index)
        if index is not None and not self.task:
            self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        data = await self.pulse.source_info(self.current_id)
        try:
            async for value in self.pulse.subscribe_peak_sample(data.name, self.frequency):
                self._publish(RangeFloat1(value), [])
        except (asyncio.CancelledError, PulseDisconnected):
            pass


class DefaultNameConnector(Subscribable[str], Readable[str]):  # TODO make writable
    type = str

    def __init__(self, pulse: PulseAsync, attr: str):
        super().__init__()
        self.pulse = pulse
        self.attr = attr

    def _update(self, server_info: PulseServerInfo, origin: List[Any]) -> None:
        self._publish(getattr(server_info, self.attr), origin)

    async def read(self) -> str:
        server_info = await self.pulse.server_info()
        return getattr(server_info, self.attr)

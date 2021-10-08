import abc
import asyncio
import logging
from collections import defaultdict
from typing import NamedTuple, List, Optional, Generic, Type, Any, DefaultDict
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
    values: list = []
    map: list = []


class PulseVolumeBalance(NamedTuple):
    volume: RangeFloat1 = 1.0
    balance: Balance = 0.0
    fade: Balance = 0.0
    lfe_balance: Balance = 0.0
    normalized_values: list = []
    map: list = []

    def as_channels(self) -> PulseVolumeRaw:
        from pulsectl._pulsectl import PA_CVOLUME, PA_CHANNEL_MAP, PA_CHANNELS_MAX, PA_VOLUME_NORM
        from shc.interfaces._pulse_ffi import pa_volume_t, pa_cvolume_set_lfe_balance, pa_cvolume_set_fade, \
            pa_cvolume_set_balance, pa_cvolume_scale

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
    def __init__(self):
        super().__init__()
        # TODO allow specifying client name and server connection
        self.pulse = PulseAsync()
        self.sink_connectors_by_id: DefaultDict[int, List["SinkConnector"]] = defaultdict(list)
        self.sink_connectors_by_name: DefaultDict[Optional[str], List["SinkConnector"]] = defaultdict(list)
        self.source_connectors_by_id: DefaultDict[int, List["SourceConnector"]] = defaultdict(list)
        self.source_connectors_by_name: DefaultDict[Optional[str], List["SourceConnector"]] = defaultdict(list)

        self._default_sink_name_connector = DefaultNameConnector(self.pulse, "default_sink_name")
        self._default_source_name_connector = DefaultNameConnector(self.pulse, "default_source_name")
        self._subscribe_server = False
        self._subscribe_sinks = False
        self._subscribe_sources = False

    async def _connect(self) -> None:
        await self.pulse.connect()

    async def _disconnect(self) -> None:
        self.pulse.disconnect()

    async def _subscribe(self) -> None:
        server_info = await self.pulse.server_info()
        self._default_sink_name_connector._update(server_info)
        self._default_source_name_connector._update(server_info)
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
                    connector.on_change(sink_info)
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
                    source_connector.on_change(source_info)
                except Exception as e:
                    logging.error("Error while initializing connector %s with current data of source", source_connector,
                                  exc_info=e)

    async def _run(self) -> None:
        self._running.set()
        async for event in self.pulse.subscribe_events('sink', 'source', 'server'):
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
                    connector.on_change(data)
            elif event.facility is PulseEventFacilityEnum.source:
                data = await self.pulse.source_info(event.index)
                name = data.name
                for source_connector in self.source_connectors_by_name.get(name, []):
                    source_connector.change_id(event.index)
                    self.source_connectors_by_id[event.index].append(source_connector)
                    source_connector.on_change(data)
        elif event.t is PulseEventTypeEnum.remove:
            if event.facility is PulseEventFacilityEnum.sink:
                for connector in self.sink_connectors_by_id.get(event.index, []):
                    connector.change_id(0)
                if event.index in self.sink_connectors_by_id:
                    del self.sink_connectors_by_id[event.index]
            elif event.facility is PulseEventFacilityEnum.source:
                for source_connector in self.source_connectors_by_id.get(event.index, []):
                    source_connector.change_id(0)
                if event.index in self.source_connectors_by_id:
                    del self.source_connectors_by_id[event.index]

        elif event.t is PulseEventTypeEnum.change:
            if event.facility is PulseEventFacilityEnum.sink:
                data = await self.pulse.sink_info(event.index)
                for connector in self.sink_connectors_by_id.get(event.index, []):
                    connector.on_change(data)
            elif event.facility is PulseEventFacilityEnum.source:
                data = await self.pulse.source_info(event.index)
                for source_connector in self.source_connectors_by_id.get(event.index, []):
                    source_connector.on_change(data)
            elif event.facility is PulseEventFacilityEnum.server:
                server_info = await self.pulse.server_info()
                self._default_sink_name_connector._update(server_info)
                self._default_source_name_connector._update(server_info)
                # Update default sink/source connectors
                default_sink_data = await self.pulse.get_sink_by_name(server_info.default_sink_name)
                default_source_data = await self.pulse.get_source_by_name(server_info.default_source_name)
                for connector in self.sink_connectors_by_name.get(None, []):
                    try:
                        self.sink_connectors_by_id[connector.current_id].remove(connector)
                    except ValueError:
                        pass
                    connector.change_id(default_sink_data.index)
                    self.sink_connectors_by_id[default_sink_data.index].append(connector)
                    connector.on_change(default_sink_data)
                for source_connector in self.source_connectors_by_name.get(None, []):
                    try:
                        self.source_connectors_by_id[source_connector.current_id].remove(source_connector)
                    except ValueError:
                        pass
                    source_connector.change_id(default_source_data.index)
                    self.source_connectors_by_id[default_source_data.index].append(source_connector)
                    source_connector.on_change(default_source_data)

    def sink_volume(self, sink_name: str) -> "SinkVolumeConnector":
        connector = SinkVolumeConnector(self.pulse)
        self.sink_connectors_by_name[sink_name].append(connector)
        return connector

    def sink_muted(self, sink_name: str) -> "SinkMuteConnector":
        connector = SinkMuteConnector(self.pulse)
        self.sink_connectors_by_name[sink_name].append(connector)
        return connector

    def sink_running(self, sink_name: str) -> Readable[bool]:
        connector = SinkStateConnector(self.pulse)
        self.sink_connectors_by_name[sink_name].append(connector)
        return connector

    def sink_peak_monitor(self, sink_name: str, frequency: int = 1) -> "SinkPeakConnector":
        connector = SinkPeakConnector(self.pulse, frequency)
        self.sink_connectors_by_name[sink_name].append(connector)
        return connector

    def default_sink_volume(self) -> "SinkVolumeConnector":
        connector = SinkVolumeConnector(self.pulse)
        self.sink_connectors_by_name[None].append(connector)
        return connector

    def default_sink_muted(self) -> "SinkMuteConnector":
        connector = SinkMuteConnector(self.pulse)
        self.sink_connectors_by_name[None].append(connector)
        return connector

    def default_sink_running(self) -> Readable[bool]:
        connector = SinkStateConnector(self.pulse)
        self.sink_connectors_by_name[None].append(connector)
        return connector

    def default_sink_peak_monitor(self, frequency: int = 1) -> "SinkPeakConnector":
        connector = SinkPeakConnector(self.pulse, frequency)
        self.sink_connectors_by_name[None].append(connector)
        return connector

    def default_sink_name(self) -> "DefaultNameConnector":
        self._subscribe_server = True
        self._subscribe_sinks = True
        return self._default_sink_name_connector

    def source_volume(self, source_name: str) -> Connectable[PulseVolumeRaw]: ...  # TODO
    def source_muted(self, source_name: str) -> Connectable[bool]: ...  # TODO
    def source_running(self, source_name: str) -> Connectable[bool]: ...  # TODO

    def source_peak_monitor(self, source_name: str, frequency: int = 1) -> "SourcePeakConnector":
        connector = SourcePeakConnector(self.pulse, frequency)
        self.source_connectors_by_name[source_name].append(connector)
        return connector

    def default_source_volume(self) -> Connectable[PulseVolumeRaw]: ...  # TODO
    def default_source_muted(self) -> Connectable[bool]: ...  # TODO
    def default_source_running(self) -> Connectable[bool]: ...  # TODO

    def default_source_peak_monitor(self, frequency: int = 1) -> "SourcePeakConnector":
        connector = SourcePeakConnector(self.pulse, frequency)
        self.source_connectors_by_name[None].append(connector)
        return connector

    def default_source_name(self) -> "DefaultNameConnector":
        self._subscribe_server = True
        self._subscribe_sources = True
        return self._default_source_name_connector


class SinkConnector(metaclass=abc.ABCMeta):
    def __init__(self):
        super().__init__()
        self.current_id: int = 0

    def on_change(self, data: PulseSinkInfo) -> None:
        pass

    def change_id(self, index: int) -> None:
        self.current_id = index


class SourceConnector(metaclass=abc.ABCMeta):
    def __init__(self):
        super().__init__()
        self.current_id: int = 0

    def on_change(self, data: PulseSourceInfo) -> None:
        pass

    def change_id(self, index: int) -> None:
        self.current_id = index


class SinkAttributeConnector(Subscribable[T], Readable[T], SinkConnector, Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, pulse: PulseAsync, type_: Type[T]):
        self.type = type_
        super().__init__()
        self.pulse = pulse

    def on_change(self, data: PulseSinkInfo) -> None:
        self._publish(self._convert_from_pulse(data), [])

    @abc.abstractmethod
    def _convert_from_pulse(self, data: PulseSinkInfo) -> T:
        pass

    async def read(self) -> T:
        if self.current_id:
            raise UninitializedError
        data = await self.pulse.sink_info(self.current_id)
        return self._convert_from_pulse(data)


class SinkStateConnector(SinkAttributeConnector[bool]):
    def __init__(self, pulse: PulseAsync):
        super().__init__(pulse, bool)

    def _convert_from_pulse(self, data: PulseSinkInfo) -> bool:
        return data.state == PulseStateEnum.running

    def change_id(self, index: int) -> None:
        super().change_id(index)
        if not index:
            self._publish(False, [])


class SinkMuteConnector(SinkAttributeConnector[bool], Writable[bool]):
    def __init__(self, pulse: PulseAsync):
        super().__init__(pulse, bool)

    def _convert_from_pulse(self, data: PulseSinkInfo) -> bool:
        return bool(data.mute)

    async def _write(self, value: T, origin: List[Any]) -> None:
        if not self.current_id:
            raise RuntimeError("PulseAudio sink id for {} is currently not defined".format(repr(self)))
        # TODO register origin for incoming update
        await self.pulse.sink_mute(self.current_id, value)


class SinkVolumeConnector(SinkAttributeConnector[PulseVolumeRaw], Writable[PulseVolumeRaw]):
    def __init__(self, pulse: PulseAsync):
        super().__init__(pulse, PulseVolumeRaw)

    def _convert_from_pulse(self, data: PulseSinkInfo) -> PulseVolumeRaw:
        return PulseVolumeRaw(data.volume.values, data.channel_map)

    async def _write(self, value: PulseVolumeRaw, origin: List[Any]) -> None:
        if not self.current_id:
            raise RuntimeError("PulseAudio sink id for {} is currently not defined".format(repr(self)))
        # TODO register origin for incoming update
        await self.pulse.sink_volume_set(self.current_id, PulseVolumeInfo(value.values))


class SinkPeakConnector(SinkConnector, Subscribable[RangeFloat1]):
    type = RangeFloat1

    def __init__(self, pulse: PulseAsync, frequency: int):
        super().__init__()
        self.pulse = pulse
        self.frequency = frequency
        self.task: Optional[asyncio.Task] = None

    def change_id(self, index: int) -> None:
        if self.task and index != self.current_id:
            self.task.cancel()
            self.task = None
        super().change_id(index)
        if index and not self.task:
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

    def change_id(self, index: int) -> None:
        if self.task and index != self.current_id:
            self.task.cancel()
            self.task = None
        super().change_id(index)
        if index and not self.task:
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

    def _update(self, server_info: PulseServerInfo) -> None:
        self._publish(getattr(server_info, self.attr), [])

    async def read(self) -> str:
        server_info = await self.pulse.server_info()
        return getattr(server_info, self.attr)

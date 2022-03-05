# Copyright 2021 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
import abc
import asyncio
import logging
from collections import defaultdict, deque
from typing import (
    NamedTuple, List, Optional, Generic, Type, Any, DefaultDict, Tuple, Callable, Deque, Set, TYPE_CHECKING)
import ctypes as c

if TYPE_CHECKING:
    from pulsectl import (
        PulseEventInfo, PulseSinkInfo, PulseSourceInfo, PulseServerInfo, PulseVolumeInfo)
    from pulsectl_asyncio import PulseAsync

import shc.conversion
from shc.base import Connectable, Subscribable, Readable, T, UninitializedError, Writable
from shc.datatypes import RangeFloat1, Balance
from shc.interfaces._helper import SupervisedClientInterface

logger = logging.getLogger(__name__)


class PulseVolumeRaw(NamedTuple):
    """
    "raw" representation of the volume setting of a Pulseaudio sink or source with individual channel volume values.

    :param values: List of float values of the volume setting of each individual channel of the sink/source from 0.0 to
            1.0
    :param map: Pulseaudio channel map as a list of integer channel positions, according to the libpulse
            `pa_channel_position` enum. E.g. [0] for mono; [1, 2] for normal stereo (left, right); [1, 2, 5, 6, 3, 7]
            for typical 5.1 surround devices. See https://freedesktop.org/software/pulseaudio/doxygen/channelmap_8h.html
            for reference. This is required for converting into the component-based :class:`PulseVolumeComponents`
            representation.
    """
    values: list = []
    map: list = []


class PulseVolumeComponents(NamedTuple):
    """
    abstract "component-based" representation of the volume setting of a Pulseaudio sink or source

    .. warning:
        Conversion methods :meth:`as_channels` and :meth:`from_channels`, which are used as default converters into/from
        :class:`PulseVolumeRaw` objects, require the libpulse shared library. This might be a problem when using and
        converting these datatypes on a remote SHC server, different from the SHC instance running the
        :class:`PulseAudioInterface`.

    :param volume: Master volume of the sink/source. Corresponds to the maximum individual channel volume
    :param balance: left/right balance (-1.0 means 100% left, +1.0 means 100% right).
    :param fade: rear/front balance (-1.0 means 100% rear speakers, +1.0 means 100% front speakers). If no surround
            channels are present, it is always 0.0.
    :param lfe_balance: subwoofer balance (-1.0 means no subwoofer, +1.0 means only subwoofer). If no subwoofer/LFE
            channel is present, the value is always 0.0
    :param normalized_values: The channel values after resetting the master volume, balance, fade and lfe_balance
            to their default values. This allows to modify these volume components but keep additional individual
            channel differences intact.
    :param map: Pulseaudio channel map as a list of integer channel positions, according to the libpulse
            `pa_channel_position` enum. E.g. [0] for mono; [1, 2] for normal stereo (left, right); [1, 2, 5, 6, 3, 7]
            for typical 5.1 surround devices. See https://freedesktop.org/software/pulseaudio/doxygen/channelmap_8h.html
            for reference. This is required for the conversion functions to/from :class:`PulseVolumeRaw`.
    """
    volume: RangeFloat1 = RangeFloat1(1.0)
    balance: Balance = Balance(0.0)
    fade: Balance = Balance(0.0)
    lfe_balance: Balance = Balance(0.0)
    normalized_values: list = []
    map: list = []

    def as_channels(self) -> PulseVolumeRaw:
        """
        Assemble a :class:`PulseVolumeRaw` volume object from the component-based representation and the additional
        derivations in the `normalized_values` field.

        This method uses C function bindings from libpulse to apply the balance, face, etc. to the channel
        volume values, using the channel map. Thus, the `libpulse` C shared library is required to use this method.

        This method is the SHC default converter from :class:`PulseVolumeComponents` to :class:`PulseVolumeRaw`.
        """
        from pulsectl._pulsectl import PA_CVOLUME, PA_CHANNEL_MAP, PA_CHANNELS_MAX, PA_VOLUME_NORM
        from shc.interfaces._pulse_ffi import pa_volume_t, pa_cvolume_set_lfe_balance, pa_cvolume_set_fade, \
            pa_cvolume_set_balance, pa_cvolume_scale

        num_channels = len(self.normalized_values)
        cvolume = PA_CVOLUME(num_channels, (pa_volume_t * PA_CHANNELS_MAX)(*self.normalized_values))
        cmap = PA_CHANNEL_MAP(num_channels, (c.c_int * PA_CHANNELS_MAX)(*self.map))
        pa_cvolume_set_lfe_balance(cvolume, cmap, self.lfe_balance)
        pa_cvolume_set_fade(cvolume, cmap, self.fade)
        pa_cvolume_set_balance(cvolume, cmap, self.balance)
        pa_cvolume_scale(cvolume, round(self.volume * PA_VOLUME_NORM))
        return PulseVolumeRaw([v / PA_VOLUME_NORM for v in cvolume.values[:cvolume.channels]], self.map)

    @classmethod
    def from_channels(cls, raw_volume: PulseVolumeRaw) -> "PulseVolumeComponents":
        """
        Convert a :class:`PulseVolumeRaw` volume object into the component-based representation.

        This method uses C function bindings from libpulse to calculate the balance, face, etc. from the channel volume
        values and the channel map. Thus, the `libpulse` C shared library is required to use this method.

        This method is the SHC default converter from :class:`PulseVolumeRaw` to :class:`PulseVolumeComponents`.
        """
        from pulsectl._pulsectl import PA_CVOLUME, PA_CHANNEL_MAP, PA_CHANNELS_MAX, PA_VOLUME_NORM
        from shc.interfaces._pulse_ffi import pa_volume_t, pa_cvolume_set_lfe_balance, pa_cvolume_set_fade, \
            pa_cvolume_set_balance, pa_cvolume_scale, pa_cvolume_max, pa_cvolume_get_balance, pa_cvolume_get_fade, \
            pa_cvolume_get_lfe_balance

        num_channels = len(raw_volume.values)
        cvolume = PA_CVOLUME(num_channels, (pa_volume_t * PA_CHANNELS_MAX)(*(round(PA_VOLUME_NORM * v)
                                                                             for v in raw_volume.values)))
        cmap = PA_CHANNEL_MAP(num_channels, (c.c_int * PA_CHANNELS_MAX)(*raw_volume.map))
        volume = pa_cvolume_max(cvolume) / PA_VOLUME_NORM
        pa_cvolume_scale(cvolume, PA_VOLUME_NORM)
        balance = pa_cvolume_get_balance(cvolume, cmap)
        pa_cvolume_set_balance(cvolume, cmap, 0.0)
        fade = pa_cvolume_get_fade(cvolume, cmap)
        pa_cvolume_set_fade(cvolume, cmap, 0.0)
        lfe_balance = pa_cvolume_get_lfe_balance(cvolume, cmap)
        pa_cvolume_set_lfe_balance(cvolume, cmap, 0.0)
        return cls(RangeFloat1(volume), Balance(balance), Balance(fade), Balance(lfe_balance),
                   list(cvolume.values)[:num_channels], raw_volume.map)


shc.conversion.register_converter(PulseVolumeRaw, PulseVolumeComponents, PulseVolumeComponents.from_channels)
shc.conversion.register_converter(PulseVolumeComponents, PulseVolumeRaw, lambda v: v.as_channels())


class PulseAudioInterface(SupervisedClientInterface):
    """
    Interface for controlling a Pulseaudio server and receiving status feedback, esp. sink and source volumes, muting,
    and level monitoring.

    The interface is based on the pulsectl and pulsectl-asyncio python packages, which internally use C function
    bindings to the Pulseaudio client shared library `libpulse`. Thus, this library must be installed on the system
    where SHC is running, for the PulseAudio interface to work. In Debian and Ubuntu, its contained in the `libpulse0`
    package, on Arch Linux the package is named `libpulse`.

    Currently the interface provides connectors for the following tasks:

    - subscribe to, read and change volume of a Pulseaudio sink (output device) or source (input device)
    - subscribe to, read and change mute state of a Pulseaudio sink or source
    - subscribe to and read state (running vs. idle/suspended) of a sink or source
    - monitor audio level of a sink or source
    - subscribe to, read and change the current default sink or default source by name

    All of the sink/source connectors are available in two different flavors: They can either be bound to a specific
    sink/source by name or follow the current default sink/source of the Pulseaudio server. Reading from connectors with
    a fixed sink/source name will raise an :class`shc.UninitializedError` if no such sink/source is present. They will
    automatically become active as soon as the sink/source appears. Default sink/source connectors will always publish
    the new respective value when the default sink/source changes on the server.

    Named sink/source connectors:

    - :meth:`sink_volume`
    - :meth:`sink_muted`
    - :meth:`sink_running`
    - :meth:`sink_peak_monitor`
    - :meth:`source_volume`
    - :meth:`source_muted`
    - :meth:`source_running`
    - :meth:`source_peak_monitor`

    Default sink/source connectors:

    - :meth:`default_sink_volume`
    - :meth:`default_sink_muted`
    - :meth:`default_sink_running`
    - :meth:`default_sink_peak_monitor`
    - :meth:`default_source_volume`
    - :meth:`default_source_muted`
    - :meth:`default_source_running`
    - :meth:`default_source_peak_monitor`

    Server state connectors:

    - :meth:`default_sink_name`
    - :meth:`default_source_name`

    All \\*_volume connectors use the :class:`PulseVolumeRaw` type for representing the sink's/source's volume setting,
    which contains a float volume setting for each individual channel of the sink/source (e.g. 6 individual values for a
    5.1 surround codec). Typically, you'll want to show and control the volume in more tangible components like
    *master volume*, *balance*, *fade* (front/rear) and subwoofer balance. For this, the raw volume can be converted
    into the :class:`PulseVolumeComponents` type, representing these components as separate fields (but still keeping
    the information about any further derivations in the individual channels). Thus, a typical application of the
    volume connectors would look like this::

        interface = PulseAudioInterface()
        volume_components = shc.Variable(PulseVolumeComponents)\\
            .connect(interface.default_sink_volume(), convert=True)  # convert PulseVolumeRaw and PulseVolumeComponents

        slider = shc.web.widgets.Slider("Volume").connect(volume_components.field('volume'))
        balance_slider = shc.web.widgets.Slider("Balance").connect(volume_components.field('balance'), convert=True)


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
        from pulsectl_asyncio import PulseAsync

        self.pulse = PulseAsync(pulse_client_name, server=pulse_server_socket)
        self.sink_connectors_by_id: DefaultDict[int, List["SinkConnector"]] = defaultdict(list)
        self.sink_connectors_by_name: DefaultDict[Optional[str], List["SinkConnector"]] = defaultdict(list)
        self.source_connectors_by_id: DefaultDict[int, List["SourceConnector"]] = defaultdict(list)
        self.source_connectors_by_name: DefaultDict[Optional[str], List["SourceConnector"]] = defaultdict(list)

        self._default_sink_name_connector = DefaultNameConnector(
            self.pulse, "default_sink_name", self._register_origin_callback)
        self._default_source_name_connector = DefaultNameConnector(
            self.pulse, "default_source_name", self._register_origin_callback)
        #: A subset of {'source', 'sink', 'server'}
        self._subscribe_facilities: Set[str] = set()

        #: A dict for keeping track of the SHC value update origin of changes we are currently applying to the
        #: Pulseaudio server, so that we can correctly apply the original origin list to the resulting Pulseaudio event
        self._change_event_origin: DefaultDict[Tuple[str, int], Deque[List[Any]]] = defaultdict(deque)

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
                    source_connector.change_id(source_info.index)
                    self.source_connectors_by_id[source_info.index].append(source_connector)
                    source_connector.on_change(source_info, [])
                except Exception as e:
                    logging.error("Error while initializing connector %s with current data of source", source_connector,
                                  exc_info=e)

    async def _run(self) -> None:
        self._running.set()
        async for event in self.pulse.subscribe_events(*self._subscribe_facilities):
            try:
                await self._dispatch_pulse_event(event)
            except Exception as e:
                logger.error("Error while dispatching PulseAudio event %s", event, exc_info=e)

    async def _dispatch_pulse_event(self, event: "PulseEventInfo") -> None:
        from pulsectl import PulseEventTypeEnum, PulseEventFacilityEnum
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
                index = 0 if event.facility == PulseEventFacilityEnum.server else event.index
                origin = self._change_event_origin[(event.facility._value, index)].popleft()
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

    def _register_origin_callback(self, facility: str, index: int, origin: List[Any]) -> None:
        # Avoid infinite growing of event_origin dict's lists, by adding origins of events that will never be
        # removed b/c we do not subscribe this kind of events.
        if facility not in self._subscribe_facilities:
            return
        self._change_event_origin[(facility, index)].append(origin)

    def sink_volume(self, sink_name: str) -> "SinkVolumeConnector":
        self._subscribe_facilities.add('sink')
        connector = SinkVolumeConnector(self.pulse, self._register_origin_callback)
        self.sink_connectors_by_name[sink_name].append(connector)
        return connector

    def sink_muted(self, sink_name: str) -> "SinkMuteConnector":
        self._subscribe_facilities.add('sink')
        connector = SinkMuteConnector(self.pulse, self._register_origin_callback)
        self.sink_connectors_by_name[sink_name].append(connector)
        return connector

    def sink_running(self, sink_name: str) -> "SinkStateConnector":
        self._subscribe_facilities.add('sink')
        connector = SinkStateConnector(self.pulse)
        self.sink_connectors_by_name[sink_name].append(connector)
        return connector

    def sink_peak_monitor(self, sink_name: str, frequency: int = 1) -> "SinkPeakConnector":
        self._subscribe_facilities.add('sink')
        connector = SinkPeakConnector(self.pulse, frequency)
        self.sink_connectors_by_name[sink_name].append(connector)
        return connector

    def default_sink_volume(self) -> "SinkVolumeConnector":
        self._subscribe_facilities.add('server')
        self._subscribe_facilities.add('sink')
        connector = SinkVolumeConnector(self.pulse, self._register_origin_callback)
        self.sink_connectors_by_name[None].append(connector)
        return connector

    def default_sink_muted(self) -> "SinkMuteConnector":
        self._subscribe_facilities.add('server')
        self._subscribe_facilities.add('sink')
        connector = SinkMuteConnector(self.pulse, self._register_origin_callback)
        self.sink_connectors_by_name[None].append(connector)
        return connector

    def default_sink_running(self) -> "SinkStateConnector":
        self._subscribe_facilities.add('server')
        self._subscribe_facilities.add('sink')
        connector = SinkStateConnector(self.pulse)
        self.sink_connectors_by_name[None].append(connector)
        return connector

    def default_sink_peak_monitor(self, frequency: int = 1) -> "SinkPeakConnector":
        self._subscribe_facilities.add('server')
        connector = SinkPeakConnector(self.pulse, frequency)
        self.sink_connectors_by_name[None].append(connector)
        return connector

    def default_sink_name(self) -> "DefaultNameConnector":
        self._subscribe_facilities.add('server')
        return self._default_sink_name_connector

    def source_volume(self, source_name: str) -> "SourceVolumeConnector":
        self._subscribe_facilities.add('source')
        connector = SourceVolumeConnector(self.pulse, self._register_origin_callback)
        self.source_connectors_by_name[source_name].append(connector)
        return connector

    def source_muted(self, source_name: str) -> "SourceMuteConnector":
        self._subscribe_facilities.add('source')
        connector = SourceMuteConnector(self.pulse, self._register_origin_callback)
        self.source_connectors_by_name[source_name].append(connector)
        return connector

    def source_running(self, source_name: str) -> "SourceStateConnector":
        self._subscribe_facilities.add('source')
        connector = SourceStateConnector(self.pulse)
        self.source_connectors_by_name[source_name].append(connector)
        return connector

    def source_peak_monitor(self, source_name: str, frequency: int = 1) -> "SourcePeakConnector":
        self._subscribe_facilities.add('source')
        connector = SourcePeakConnector(self.pulse, frequency)
        self.source_connectors_by_name[source_name].append(connector)
        return connector

    def default_source_volume(self) -> "SourceVolumeConnector":
        self._subscribe_facilities.add('source')
        self._subscribe_facilities.add('server')
        connector = SourceVolumeConnector(self.pulse, self._register_origin_callback)
        self.source_connectors_by_name[None].append(connector)
        return connector

    def default_source_muted(self) -> "SourceMuteConnector":
        self._subscribe_facilities.add('source')
        self._subscribe_facilities.add('server')
        connector = SourceMuteConnector(self.pulse, self._register_origin_callback)
        self.source_connectors_by_name[None].append(connector)
        return connector

    def default_source_running(self) -> "SourceStateConnector":
        self._subscribe_facilities.add('source')
        self._subscribe_facilities.add('server')
        connector = SourceStateConnector(self.pulse)
        self.source_connectors_by_name[None].append(connector)
        return connector

    def default_source_peak_monitor(self, frequency: int = 1) -> "SourcePeakConnector":
        self._subscribe_facilities.add('server')
        connector = SourcePeakConnector(self.pulse, frequency)
        self.source_connectors_by_name[None].append(connector)
        return connector

    def default_source_name(self) -> "DefaultNameConnector":
        self._subscribe_facilities.add('server')
        return self._default_source_name_connector


class SinkConnector(metaclass=abc.ABCMeta):
    def __init__(self):
        super().__init__()
        self.current_id: Optional[int] = None

    def on_change(self, data: "PulseSinkInfo", origin: List[Any]) -> None:
        pass

    def change_id(self, index: Optional[int]) -> None:
        self.current_id = index


class SourceConnector(metaclass=abc.ABCMeta):
    def __init__(self):
        super().__init__()
        self.current_id: Optional[int] = None

    def on_change(self, data: "PulseSourceInfo", origin: List[Any]) -> None:
        pass

    def change_id(self, index: Optional[int]) -> None:
        self.current_id = index


class SinkAttributeConnector(Subscribable[T], Readable[T], SinkConnector, Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, pulse: "PulseAsync", type_: Type[T]):
        self.type = type_
        super().__init__()
        self.pulse = pulse

    def on_change(self, data: "PulseSinkInfo", origin: List[Any]) -> None:
        self._publish(self._convert_from_pulse(data), origin)

    @abc.abstractmethod
    def _convert_from_pulse(self, data: "PulseSinkInfo") -> T:
        pass

    async def read(self) -> T:
        if self.current_id is None:
            raise UninitializedError()
        data = await self.pulse.sink_info(self.current_id)
        return self._convert_from_pulse(data)


class SourceAttributeConnector(Subscribable[T], Readable[T], SourceConnector, Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, pulse: "PulseAsync", type_: Type[T]):
        self.type = type_
        super().__init__()
        self.pulse = pulse

    def on_change(self, data: "PulseSourceInfo", origin: List[Any]) -> None:
        self._publish(self._convert_from_pulse(data), origin)

    @abc.abstractmethod
    def _convert_from_pulse(self, data: "PulseSourceInfo") -> T:
        pass

    async def read(self) -> T:
        if self.current_id is None:
            raise UninitializedError()
        data = await self.pulse.source_info(self.current_id)
        return self._convert_from_pulse(data)


class SinkStateConnector(SinkAttributeConnector[bool]):
    def __init__(self, pulse: "PulseAsync"):
        super().__init__(pulse, bool)

    def _convert_from_pulse(self, data: "PulseSinkInfo") -> bool:
        from pulsectl import PulseStateEnum

        return data.state == PulseStateEnum.running

    def change_id(self, index: Optional[int]) -> None:
        super().change_id(index)
        if index is None:
            self._publish(False, [])


class SourceStateConnector(SourceAttributeConnector[bool]):
    def __init__(self, pulse: "PulseAsync"):
        super().__init__(pulse, bool)

    def _convert_from_pulse(self, data: "PulseSinkInfo") -> bool:
        from pulsectl import PulseStateEnum

        return data.state == PulseStateEnum.running

    def change_id(self, index: Optional[int]) -> None:
        super().change_id(index)
        if index is None:
            self._publish(False, [])


class SinkMuteConnector(SinkAttributeConnector[bool], Writable[bool]):
    def __init__(self, pulse: "PulseAsync", register_origin_callback: Callable[[str, int, List[Any]], None]):
        super().__init__(pulse, bool)
        self.register_origin_callback = register_origin_callback

    def _convert_from_pulse(self, data: "PulseSinkInfo") -> bool:
        return bool(data.mute)

    async def _write(self, value: T, origin: List[Any]) -> None:
        if self.current_id is None:
            raise RuntimeError("PulseAudio sink id for {} is currently not defined".format(repr(self)))
        self.register_origin_callback('sink', self.current_id, origin)
        await self.pulse.sink_mute(self.current_id, value)


class SourceMuteConnector(SourceAttributeConnector[bool], Writable[bool]):
    def __init__(self, pulse: "PulseAsync", register_origin_callback: Callable[[str, int, List[Any]], None]):
        super().__init__(pulse, bool)
        self.register_origin_callback = register_origin_callback

    def _convert_from_pulse(self, data: "PulseSinkInfo") -> bool:
        return bool(data.mute)

    async def _write(self, value: T, origin: List[Any]) -> None:
        if self.current_id is None:
            raise RuntimeError("PulseAudio source id for {} is currently not defined".format(repr(self)))
        self.register_origin_callback('source', self.current_id, origin)
        await self.pulse.source_mute(self.current_id, value)


class SinkVolumeConnector(SinkAttributeConnector[PulseVolumeRaw], Writable[PulseVolumeRaw]):
    def __init__(self, pulse: "PulseAsync", register_origin_callback: Callable[[str, int, List[Any]], None]):
        super().__init__(pulse, PulseVolumeRaw)
        self.register_origin_callback = register_origin_callback

    def _convert_from_pulse(self, data: "PulseSinkInfo") -> PulseVolumeRaw:
        return PulseVolumeRaw(data.volume.values, data.channel_list_raw)

    async def _write(self, value: PulseVolumeRaw, origin: List[Any]) -> None:
        from pulsectl import PulseVolumeInfo

        if self.current_id is None:
            raise RuntimeError("PulseAudio sink id for {} is currently not defined".format(repr(self)))
        self.register_origin_callback('sink', self.current_id, origin)
        await self.pulse.sink_volume_set(self.current_id, PulseVolumeInfo(value.values))


class SourceVolumeConnector(SourceAttributeConnector[PulseVolumeRaw], Writable[PulseVolumeRaw]):
    def __init__(self, pulse: "PulseAsync", register_origin_callback: Callable[[str, int, List[Any]], None]):
        super().__init__(pulse, PulseVolumeRaw)
        self.register_origin_callback = register_origin_callback

    def _convert_from_pulse(self, data: "PulseSinkInfo") -> PulseVolumeRaw:
        return PulseVolumeRaw(data.volume.values, data.channel_list_raw)

    async def _write(self, value: PulseVolumeRaw, origin: List[Any]) -> None:
        from pulsectl import PulseVolumeInfo

        if self.current_id is None:
            raise RuntimeError("PulseAudio source id for {} is currently not defined".format(repr(self)))
        self.register_origin_callback('source', self.current_id, origin)
        await self.pulse.source_volume_set(self.current_id, PulseVolumeInfo(value.values))


class SinkPeakConnector(SinkConnector, Subscribable[RangeFloat1]):
    type = RangeFloat1

    def __init__(self, pulse: "PulseAsync", frequency: int):
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
        from pulsectl import PulseDisconnected

        data = await self.pulse.sink_info(self.current_id)
        try:
            async for value in self.pulse.subscribe_peak_sample(data.monitor_source_name, self.frequency):
                self._publish(RangeFloat1(value), [])
        except (asyncio.CancelledError, PulseDisconnected):
            pass
        except Exception as e:
            logger.error("Error while monitoring peaks of sink %s:", data.name, exc_info=e)


class SourcePeakConnector(SourceConnector, Subscribable[RangeFloat1]):
    type = RangeFloat1

    def __init__(self, pulse: "PulseAsync", frequency: int):
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
        from pulsectl import PulseDisconnected

        data = await self.pulse.source_info(self.current_id)
        try:
            async for value in self.pulse.subscribe_peak_sample(data.name, self.frequency):
                self._publish(RangeFloat1(value), [])
        except (asyncio.CancelledError, PulseDisconnected):
            pass
        except Exception as e:
            logger.error("Error while monitoring peaks of source %s:", data.name, exc_info=e)


class DefaultNameConnector(Subscribable[str], Readable[str], Writable[str]):
    type = str

    def __init__(self, pulse: "PulseAsync", attr: str, register_origin_callback: Callable[[str, int, List[Any]], None]):
        super().__init__()
        self.pulse = pulse
        self.attr = attr
        self.register_origin_callback = register_origin_callback

    def _update(self, server_info: "PulseServerInfo", origin: List[Any]) -> None:
        self._publish(getattr(server_info, self.attr), origin)

    async def read(self) -> str:
        server_info = await self.pulse.server_info()
        return getattr(server_info, self.attr)

    async def _write(self, value: str, origin: List[Any]) -> None:
        self.register_origin_callback('server', 0, origin)
        if self.attr == 'default_source_name':
            await self.pulse.source_default_set(value)
        else:
            await self.pulse.sink_default_set(value)

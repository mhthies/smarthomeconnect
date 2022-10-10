import asyncio
import io
import json
import logging
from typing import IO, Any, Dict, Tuple, Optional, Generic, List, Type
from pathlib import Path

import aiofile

from shc.base import Readable, T, Writable, UninitializedError
from shc.conversion import from_json
from shc.supervisor import AbstractInterface


FOOTER = b'"_": null\n}\n'
NUM_BUFFER_SPACES = 10
MAX_ABANDONED_LINES = 50

logger = logging.getLogger(__name__)


class FilePersistenceStore(AbstractInterface):
    """
    A value persistence backend for storing values in a single JSON file

    The goal is to write values to disk as fast as possible to persist them across graceful restarts and not-so-graceful
    restarts (= crashes) of SHC or the host operating system. Any number of named and Readable+Writable Connector
    objects are used to *write* to a specific persisted value and allow to *read* it back, typically for initialization
    of stateful in-memory objects like Variable objects.

    Usage example::

        from pathlib import Path
        import shc
        from shc.log.file_persistence import FilePersistenceStore

        persistence_store = FilePersistenceStore(Path("/var/lib/shc/persistence.json"))

        temp_setpoint = shc.Variable(float, name="temp_setpoint")\
            .connect(persistence_store.connector(float, "temp_setpoint"), read=True)

    In this persistence store implementation, the values are serialized using their `canonical JSON representation
    <datatypes.json>`_ and written to
    as values of a JSON object in a JSON file, indexed by the connector's name. To avoid writing overhead when updating
    a single value, individual values are updated in-place in the JSON-file. To make this possible, we maintain a map
    of byte-offsets of the individual fields insert some spaces as buffer for growing values after each value. In case
    the new value representation's length exceeds the old length + buffer, we clear the whole key-value pair with spaces
    and append it as a new line at the end of the file.

    Now and then, we can rewrite the whole file (esp. at startup) to truncate those empty bloat lines. Rewriting,
    however, is done in crash-safe way, i.e. we first rewrite the data to a new temporary file and afterwards replace
    the original file atomically.

    The file is intended to be a valid JSON file as a whole at all times (after each completed write process). However,
    due to the occasional rewriting and replacement of the file, an open file handle to the file may not stay valid. By
    rewriting the file right at startup, the JSON file is brought to the required formatting. Thus, it may be altered
    arbitrarily while SHC is shut down.

    :param file: Path of the JSON file to be used for persistence. Will be created if not already exists. If already
        existent, it must be a valid JSON file with a single object as top-level structure.
    """
    def __init__(self, file: Path):
        super().__init__()
        self.file = file
        self._file_ready = asyncio.Event()
        self._file_mutex = asyncio.Lock()
        #: element name -> (offset, key_length, value_capacity)
        self._element_map: Dict[str, Tuple[int, int, int]] = {}
        self._footer_offset = 0
        self._abandoned_lines = 0
        self._fd: aiofile.BinaryFileWrapper

    async def start(self) -> None:
        file_exists = await asyncio.get_event_loop().run_in_executor(None, self.file.exists)
        if file_exists:
            logger.info("Using existing file persistence store at %s ...", self.file)
            fd = aiofile.async_open(self.file, 'rb')
            assert isinstance(fd, aiofile.BinaryFileWrapper)
            self._fd = fd
            await self._fd.file.open()
            await self.rewrite()
        else:
            logger.info("Creating new file persistence store at %s ...", self.file)
            fd = aiofile.async_open(self.file, 'xb+')
            assert isinstance(fd, aiofile.BinaryFileWrapper)
            self._fd = fd
            await self._fd.file.open()
            await self._fd.write(b"{\n" + FOOTER)
            self._footer_offset = 2
        self._file_ready.set()

    async def stop(self) -> None:
        await self._fd.close()

    async def rewrite(self):
        # Create temp file
        logger.info("Staring rewrite file persistence store %s ...", self.file)
        tmp_file = self.file.with_name(self.file.name + ".tmp")

        async with self._file_mutex:
            # Read all current data in main file as JSON document
            self._fd.seek(0)
            data = json.loads((await self._fd.read()).decode('utf-8'))
            assert isinstance(data, dict)

            # Re-write data into temp file
            new_fd = aiofile.async_open(tmp_file, 'xb+')
            assert isinstance(new_fd, aiofile.BinaryFileWrapper)
            await new_fd.file.open()
            await new_fd.write(b"{\n")
            new_map = {}
            for key, value in data.items():
                if key == '_':
                    continue
                start = new_fd.tell()
                key_written = await new_fd.write(b'"' + key.encode() + b'":')
                value_written = await new_fd.write(json.dumps(value, separators=(',', ':')).encode('utf-8')
                                                   + (b' ' * NUM_BUFFER_SPACES) + b',\n')
                new_map[key] = (start, key_written, value_written-2)  # Do not count the ',\n' into the available length
            self._footer_offset = new_fd.tell()
            await new_fd.write(FOOTER)
            await new_fd.file.fsync()

            # Overwrite main file with temp file and replace file descriptor
            await self._fd.close()
            await asyncio.get_event_loop().run_in_executor(None, tmp_file.replace, self.file)
            new_fd.seek(0)
            self._fd = new_fd
            self._element_map = new_map
            self._abandoned_lines = 0
        logger.info("Rewrite of file persistence store %s finished.", self.file)

    async def get_element(self, name: str) -> Optional[Any]:
        await self._file_ready.wait()
        async with self._file_mutex:
            if name not in self._element_map:
                return None
            offset, key_length, capacity = self._element_map[name]
            self._fd.seek(offset + key_length)
            return json.loads((await self._fd.read(capacity)).decode('utf-8'))

    async def set_element(self, name: str, value: Any) -> None:
        await self._file_ready.wait()
        data = json.dumps(value, separators=(',', ':')).encode('utf-8')
        logger.debug("Writing to file persistence store %s: %s = %s ...", name, data)
        length = len(data)
        await self._file_ready.wait()
        async with self._file_mutex:
            if name in self._element_map:
                offset, key_length, capacity = self._element_map[name]
                if length > capacity:
                    # Clear out current element line with spaces and activate appending a new line to the end of the
                    # file
                    self._fd.seek(offset)
                    await self._fd.write(b' ' * (key_length + capacity + 1))  # overwrite ',' at the end with ' '
                    self._abandoned_lines += 1
                    append = True
                else:
                    self._fd.seek(offset + key_length)
                    await self._fd.write(data + (b' ' * (capacity - length)))
                    append = False
                    logger.debug("Updated file persistence store in-place")
            else:
                append = True
            if append:
                self._fd.seek(self._footer_offset)  # overwrite full-footer at the end of the file to rewrite it later
                start = self._fd.tell()
                key_written = await self._fd.write(b'"' + name.encode() + b'":')
                value_written = await self._fd.write(json.dumps(value, separators=(',', ':')).encode('utf-8')
                                                     + (b' ' * NUM_BUFFER_SPACES) + b',\n')
                self._footer_offset = self._fd.tell()
                await self._fd.write(FOOTER)
                self._element_map[name] = (start, key_written, value_written - 2)
                logger.debug("Updated file persistence store with append for key %s at offset 0x%02x", name, start)
                # ↑ Do not count the ',\n' into the available length
            await self._fd.file.fsync()

        if self._abandoned_lines > MAX_ABANDONED_LINES:
            try:
                await self.rewrite()
            except Exception as e:
                logger.error("Error while rewriting file persistence store %s:", exc_info=e)

    def connector(self, type_: Type[T], name: str) -> "FilePersistenceConnector[T]":
        """
        Get a connector for writing and reading a specific named value to/form the persistence file.

        :param type_: Data type of the values to be stored by this connector
        :param name: The name to identify the specific value. Any string except for "_" is allowed.
        :return: A *Writable* and *Readable* object that accesses the value identified by the given `name`.
        """
        return FilePersistenceConnector(type_, self, name)


class FilePersistenceConnector(Readable[T], Writable[T], Generic[T]):
    def __init__(self, type_: Type[T], interface: FilePersistenceStore, name: str):
        if name == "_":
            raise ValueError("Connector name '_' is not allowed in FilePersistenceStore.")
        self.type = type_
        super().__init__()
        self.interface = interface
        self.name = name

    async def read(self) -> T:
        value = await self.interface.get_element(self.name)
        if value is None:
            raise UninitializedError()
        return from_json(self.type, value)

    async def _write(self, value: T, origin: List[Any]) -> None:
        await self.interface.set_element(self.name, value)

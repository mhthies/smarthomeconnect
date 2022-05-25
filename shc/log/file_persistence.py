import asyncio
import io
import json
from typing import IO, Any, Dict, Tuple, Optional, Generic, List, Type
from pathlib import Path

import aiofile

from shc.base import Readable, T, Writable
from shc.supervisor import AbstractInterface


FOOTER = b'"_": null\n}\n'
FOOTER_LEN = len(FOOTER)
MAX_ABANDONED_LINES = 50


class FilePersistenceStore(AbstractInterface):
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
            self._fd = aiofile.async_open(self.file, 'rb')
            await self._fd.file.open()
            await self.rewrite()
        else:
            self._fd = aiofile.async_open(self.file, 'xb+')
            await self._fd.file.open()
            await self._fd.write(b"{\n" + FOOTER)
        self._file_ready.set()

    async def stop(self) -> None:
        await self._fd.close()

    async def rewrite(self):
        # Create temp file
        # TODO handle errors while creating file
        tmp_file = self.file.with_name(self.file.name + ".tmp")

        async with self._file_mutex:
            # Read all current data in main file as JSON document
            self._fd.seek(0)
            data = json.loads((await self._fd.read()).decode('utf-8'))
            assert isinstance(data, dict)

            # Re-write data into temp file
            new_fd: aiofile.BinaryFileWrapper = aiofile.async_open(tmp_file, 'xb+')
            await new_fd.file.open()
            await new_fd.write(b"{\n")
            new_map = {}
            for key, value in data.items():
                if key == '_':
                    continue
                start = new_fd.tell()
                key_written = await new_fd.write(b'"' + key.encode() + b'":')
                value_written = await new_fd.write(json.dumps(value, separators=(',', ':')).encode('utf-8')
                                                   + (b' ' * 10) + b',\n')
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
            else:
                append = True
            if append:
                self._fd.seek(self._footer_offset)  # overwrite full-footer at the end of the file to rewrite it later
                start = self._fd.tell()
                key_written = await self._fd.write(b'"' + name.encode() + b'":')
                value_written = await self._fd.write(json.dumps(value, separators=(',', ':')).encode('utf-8')
                                                     + (b' ' * 10) + b',\n')
                self._footer_offset = self._fd.tell()
                await self._fd.write(FOOTER)
                self._element_map[name] = (start, key_written, value_written - 2)
                # ↑ Do not count the ',\n' into the available length
            await self._fd.file.fsync()

        if self._abandoned_lines > MAX_ABANDONED_LINES:
            await self.rewrite()

    def connector(self, type_: Type[T], name: str) -> "FilePersistenceConnector[T]":
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
        return await self.interface.get_element(self.name)

    async def _write(self, value: T, origin: List[Any]) -> None:
        await self.interface.set_element(self.name, value)

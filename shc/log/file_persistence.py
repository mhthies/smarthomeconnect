import asyncio
import io
import json
from typing import IO, Any, Dict, Tuple, Optional, Generic, List, Type
from pathlib import Path

from shc.base import Readable, T, Writable
from shc.supervisor import AbstractInterface


FOOTER = b'"_": null\n}\n'
FOOTER_LEN = len(FOOTER)
MAX_ABANDONED_LINES = 50


class FilePersistenceStore(AbstractInterface):
    def __init__(self, file: Path):
        super().__init__()
        self.file = file
        self.file_ready = asyncio.Event()
        self.file_mutex = asyncio.Lock()
        #: element name -> (offset, key_length, value_capacity)
        self.element_map: Dict[str, Tuple[int, int, int]] = {}
        self.abandoned_lines = 0
        self.fd: IO[bytes]

    async def start(self) -> None:
        # TODO make check non-blocking
        if self.file.is_file():
            # TODO make open non-blocking
            self.fd: IO[bytes] = self.file.open('rb+')
            await self.rewrite()
        else:
            # TODO make open non-blocking
            self.fd = self.file.open('xb')
            # TODO make write non-blocking
            self.fd.write(b"{\n" + FOOTER)
            # TODO make flush non-blocking
            self.fd.flush()
        self.file_ready.set()

    async def stop(self) -> None:
        self.fd.close()

    async def rewrite(self):
        # Create temp file
        # TODO handle errors while creating file
        tmp_file = self.file.with_name(self.file.name + ".tmp")

        async with self.file_mutex:
            # Read all current data in main file as JSON document
            self.fd.seek(0)
            data = json.load(io.TextIOWrapper(self.fd, encoding="utf-8-sig"))
            assert isinstance(data, dict)

            # Re-write data into temp file
            # TODO make open non-blocking
            # TODO make writes non-blocking
            new_fd = tmp_file.open('xb+')
            new_fd.write(b"{\n")
            new_map = {}
            for key, value in data.items():
                if key == '_':
                    continue
                start = new_fd.tell()
                key_written = new_fd.write(b'"' + key.encode() + b'":')
                value_written = new_fd.write(json.dumps(value, separators=(',', ':')).encode('utf-8')
                                             + (b' ' * 10) + b',\n')
                new_map[key] = (start, key_written, value_written-2)  # Do not count the ',\n' into the available length
            new_fd.write(FOOTER)
            # TODO make flush non-blocking
            new_fd.flush()

            # Overwrite main file with temp file and replace file descriptor
            self.fd.close()
            # TODO make replace non-blocking
            tmp_file.replace(self.file)
            new_fd.seek(0)
            self.fd = new_fd
            self.element_map = new_map
            self.abandoned_lines = 0

    async def get_element(self, name: str) -> Optional[Any]:
        await self.file_ready.wait()
        async with self.file_mutex:
            if name not in self.element_map:
                return None
            offset, key_length, capacity = self.element_map[name]
            self.fd.seek(offset+key_length)
            # TODO make read non-blocking
            return json.loads(self.fd.read(capacity).decode('utf-8'))

    async def set_element(self, name: str, value: Any) -> None:
        await self.file_ready.wait()
        data = json.dumps(value, separators=(',', ':')).encode('utf-8')
        length = len(data)
        await self.file_ready.wait()
        async with self.file_mutex:
            if name in self.element_map:
                offset, key_length, capacity = self.element_map[name]
                if length > capacity:
                    # Clear out current element line with spaces and activate appending a new line to the end of the file
                    self.fd.seek(offset)
                    self.fd.write(b' '*(key_length+capacity+1))  # overwrite ',' at the end with ' '
                    self.abandoned_lines += 1
                    append = True
                else:
                    self.fd.seek(offset+key_length)
                    self.fd.write(data + (b' ' * (capacity-length)))
                    append = False
            else:
                append = True
            if append:
                self.fd.seek(-FOOTER_LEN, 2)  # overwrite full-footer at the end of the file to rewrite it later
                start = self.fd.tell()
                key_written = self.fd.write(b'"' + name.encode() + b'":')
                value_written = self.fd.write(json.dumps(value, separators=(',', ':')).encode('utf-8')
                                              + (b' ' * 10) + b',\n')
                self.fd.write(FOOTER)
                self.element_map[name] = (start, key_written, value_written - 2)  # Do not count the ',\n' into the available length
            # TODO make flush non-blocking
            self.fd.flush()

        if self.abandoned_lines > MAX_ABANDONED_LINES:
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

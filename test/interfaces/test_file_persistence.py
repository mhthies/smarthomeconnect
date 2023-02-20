import json
import tempfile
import unittest
from pathlib import Path

import shc.base
from shc.log import file_persistence
from .._helper import InterfaceThreadRunner
from ..test_variables import ExampleTupleType


class FilePersistenceTest(unittest.TestCase):
    def test_simple_create(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runner = InterfaceThreadRunner(file_persistence.FilePersistenceStore, Path(tempdir) / "store.json")
            interface: file_persistence.FilePersistenceStore = runner.interface
            try:
                conn1 = interface.connector(float, "conn1")
                conn2 = interface.connector(ExampleTupleType, "conn2")
                runner.start()
                runner.run_coro(conn1.write(0.0, [self]))
                runner.run_coro(conn2.write(ExampleTupleType(42, 3.14), [self]))
                runner.run_coro(conn1.write(3.14, [self]))
            finally:
                runner.stop()

            runner2 = InterfaceThreadRunner(file_persistence.FilePersistenceStore, Path(tempdir) / "store.json")
            interface2: file_persistence.FilePersistenceStore = runner2.interface
            try:

                conn21 = interface2.connector(float, "conn1")
                conn22 = interface2.connector(ExampleTupleType, "conn2")
                conn23 = interface2.connector(int, "conn3")

                runner2.start()
                self.assertEqual(3.14, runner2.run_coro(conn21.read()))
                self.assertEqual(ExampleTupleType(42, 3.14), runner2.run_coro(conn22.read()))
                with self.assertRaises(shc.base.UninitializedError):
                    runner2.run_coro(conn23.read())
            finally:
                runner2.stop()

    def test_existing_json(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.json"
            with open(path, 'w') as f:
                json.dump({"conn1": 3.14, "conn2": [56, 0.0]}, f)

            runner = InterfaceThreadRunner(file_persistence.FilePersistenceStore, Path(tempdir) / "store.json")
            interface: file_persistence.FilePersistenceStore = runner.interface

            try:
                conn1 = interface.connector(float, "conn1")
                conn2 = interface.connector(ExampleTupleType, "conn2")

                runner.start()
                runner.run_coro(conn1.write(2.72, [self]))
                self.assertEqual(ExampleTupleType(56, 0.0), runner.run_coro(conn2.read()))
                self.assertEqual(2.72, runner.run_coro(conn1.read()))
            finally:
                runner.stop()

            with open(path) as f:
                data = json.load(f)
            self.assertEqual(2.72, data["conn1"])
            self.assertEqual([56, 0.0], data["conn2"])

    def test_intermittent_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runner = InterfaceThreadRunner(file_persistence.FilePersistenceStore, Path(tempdir) / "store.json")
            interface: file_persistence.FilePersistenceStore = runner.interface

            try:
                conn1 = interface.connector(int, "conn1")
                conn2 = interface.connector(str, "conn2")

                runner.start()
                # 100 cycles, after each 10 cycles, we check the JSON file (in a
                # Since we abandon 1 line per cycle (see below), this should trigger at least one full rewrite
                for i in range(1, 11):
                    for j in range(1, 11):
                        n = i*10+j
                        runner.run_coro(conn1.write(n, [self]))
                        # String grows more than our buffer in each cycle → new line each cycle
                        text = "0123456789ab" * n
                        runner.run_coro(conn2.write(text, [self]))
                        self.assertEqual(n, runner.run_coro(conn1.read()))
                        self.assertEqual(text, runner.run_coro(conn2.read()))

                    with open(Path(tempdir) / "store.json") as f:
                        lines = len(f.readlines())
                        f.seek(0)
                        data = json.load(f)
                    self.assertLessEqual(lines, 55)
                    self.assertEqual(n, data["conn1"])
                    self.assertEqual(text, data["conn2"])
            finally:
                runner.stop()

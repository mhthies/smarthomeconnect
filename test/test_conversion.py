import datetime
import json
import unittest

from shc import conversion, Variable


class ConverterRegistrationTest(unittest.TestCase):
    def test_missing_converters(self) -> None:
        with self.assertRaises(TypeError):
            conversion.get_converter(float, datetime.date)
        with self.assertRaises(TypeError):
            json.dumps({'var': Variable(bool)}, cls=conversion.SHCJsonEncoder)
        with self.assertRaises(TypeError):
            fake_json_data = {'var': {'x': 'foobar'}}
            conversion.from_json(Variable, fake_json_data['var'])


class DefaultConverterTest(unittest.TestCase):
    def test_default_conversions(self) -> None:
        self.assertEqual(5, conversion.get_converter(float, int)(5.0))
        self.assertEqual(5.0, conversion.get_converter(float, int)(5))
        self.assertTrue(conversion.get_converter(float, bool)(5.0))
        self.assertTrue(conversion.get_converter(int, bool)(5))
        self.assertEqual("5.0", conversion.get_converter(float, str)(5.0))
        self.assertEqual("5", conversion.get_converter(int, str)(5))
        self.assertEqual(5, conversion.get_converter(str, int)("5"))
        self.assertEqual(5.3, conversion.get_converter(str, float)("5.3"))

    def test_default_json_converters(self) -> None:
        date1 = datetime.date(2020, 5, 17)
        datetime1 = datetime.datetime(2020, 5, 17, 17, 35, 19, 5005)
        datetime2 = datetime.datetime(2020, 5, 17, 17, 35, 19, 5005,
                                      tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
        timedelta1 = datetime.timedelta(days=5, hours=7, minutes=3, milliseconds=25)

        serialized = json.dumps({
            'int': 5,
            'bool': True,
            'float': 5.3,
            'date1': date1,
            'datetime1': datetime1,
            'datetime2': datetime2,
            'timedelta1': timedelta1,
        }, cls=conversion.SHCJsonEncoder)

        deserialized = json.loads(serialized)

        self.assertEqual(5, conversion.from_json(int, deserialized['int']))
        self.assertEqual(True, conversion.from_json(bool, deserialized['bool']))
        self.assertEqual(5.3, conversion.from_json(float, deserialized['float']))
        self.assertEqual(date1, conversion.from_json(datetime.date, deserialized['date1']))
        self.assertEqual(datetime1, conversion.from_json(datetime.datetime, deserialized['datetime1']))
        self.assertEqual(datetime2, conversion.from_json(datetime.datetime, deserialized['datetime2']))
        self.assertEqual(timedelta1, conversion.from_json(datetime.timedelta, deserialized['timedelta1']))

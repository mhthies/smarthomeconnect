
Datatypes and Type Conversions
==============================

SHC's *Connectable* objects are designed to work with simple ("scalar") Python types, basic structured types, specifically NamedTuples, and Enums.
Basically, thanks to Python's dynamic nature, any Python type can be used as a value type by connectable objects.
However, some of SHC's features work much better with simple types, e.g. the :ref:`dynamic type checking and automatic type conversions <base.typing>` and the builtin :ref:`JSON serialization<datatypes.json>` (e.g. for the :ref:`REST API <web.rest>` and :meth:`MQTT <shc.interfaces.mqtt.MQTTClientInterface.topic_json>`).

Examples for well supported Python builtin types and standard-library types:

- :class:`bool`
- :class:`int`
- :class:`float`
- :class:`str`
- :class:`datetime.datetime`
- :class:`datetime.date`
- :class:`datetime.time`
- :class:`datetime.timedelta`

In addition, SHC specifies some derived types of these builtin types with addtional semantics (see next section) and some NamedTuples for commonly used and interface-specific data structures:

- :class:`shc.datatypes.RGBUInt8`
- :class:`shc.datatypes.RGBFloat1`
- :class:`shc.datatypes.HSVFloat1`
- :class:`shc.datatypes.RGBWUInt8`
- :class:`shc.datatypes.CCTUInt8`
- :class:`shc.datatypes.RGBCCTUInt8`
- :class:`shc.interfaces.knx.KNXHVACMode`
- :class:`shc.interfaces.knx.KNXUpDown`
- :class:`shc.interfaces.pulse.PulseVolumeRaw`
- :class:`shc.interfaces.pulse.PulseVolumeComponents`


.. _datatypes.newtype:

Newtype paradigm in SHC
-----------------------

To make :ref:`type checking and automatic type conversions <base.typing>` more useful, SHC makes use of the "Newtype" paradigm (known e.g. from `Haskell <https://wiki.haskell.org/Newtype>`_ and `Rust <https://doc.rust-lang.org/book/ch19-04-advanced-types.html#using-the-newtype-pattern-for-type-safety-and-abstraction>`_):
When a Connectable object's values have special additional semantics, a derived type is used instead of the plain scalar type to specify these semantics.
This allows the type checking to check for mismatched value semantics of connected objects (even with the same scalar type) and to chose the correct type converstion automatically.
A good example for this method are the different integer types for 0-100% ranges provided by SHC:

* :class:`RangeUInt8 <shc.datatypes.RangeUInt8>` is derived from `int` and its instances shall be values from 0 (0%) to 255 (100%)
* :class:`RangeInt0To100 <shc.datatypes.RangeInt0To100>` is derived from `int` and its instances shall be values from 0 (0%) to 100 (100%)

Obviously, values of these two types are compatible on a syntactic level, but not on a semantic level.
SHC provides default converters for converting both of these types into plain :class:`int`, as well as default converters to convert them to :class:`RangeFloat1` and into each other (with the appropriate scaling).

List of New Types included with SHC:

- :class:`shc.datatypes.RangeFloat1` 
- :class:`shc.datatypes.RangeUInt8` 
- :class:`shc.datatypes.RangeInt0To100`
- :class:`shc.datatypes.AngleUInt8`
- :class:`shc.datatypes.Balance`


.. _datatypes.default_converters:

Default converters
------------------

SHC maintains a global dict of default conversion functions for pairs of types to convert values from the one type into the other type.
These default converters are used by :meth:`.subscribe() <shc.base.Subscribable.subscribe>`, :meth:`.set_provider() <shc.base.Reading.set_provider>` and :meth:`.connect() <shc.base.Connectable.connect>`, when `convert=True` is given.
See :ref:`base.typing` for more information.
To retrieve a default converter from that global dict, use :func:`shc.conversion.get_converter`.

Reasonable default converters for the scalar builtin Python types and the additional New Types and NamedTuples provided by SHC are already included with SHC.
To add additional default converters, e.g. for custom types to be used with SHC, use :func:`shc.conversion.register_converter`.


.. _datatypes.json:

JSON conversion
---------------

Different modules of SHC require to serialize values into JSON data or deserialize them back into objects of the respective value type.
Similar to the default converters, the :mod:`shc.conversion` module provides a global uniform and extensible way to do this:

- For encoding, the :class:`shc.conversion.SHCJsonEncoder` class can be used as an `encoderclass` with Python's builtin JSON module::

      serialized_value = json.dumps(value, cls=shc.conversion.SHCJsonEncoder)

  This also allows to convert lists, dicts, etc. of supported values to the respective JSON representation.

- For decoding, use the usual JSON deserialization methods and afterwards apply :func:`shc.conversion.from_json` to the resulting object to convert it to the expected value type, e.g.::
    
      value = shc.conversion.from_json(json.loads(serialized_value), shc.datatypes.RangeFloat1)

The two converters natively support simple builtin types, Enums and NamedTuples by default, as well as any derived types from these (e.g. for :ref:`Newtypes <datatypes.newtype>`).
To add support for further types, :func:`shc.conversion.register_json_conversion` can be used to register the required converter functions.


``shc.datatypes`` Module Reference
----------------------------------

.. automodule:: shc.datatypes
    :members:
    :member-order: bysource


``shc.conversion`` Module Reference
-----------------------------------

.. py:module:: shc.conversion

.. autofunction:: register_converter
.. autofunction:: get_converter

.. autofunction:: register_json_conversion
.. autoclass:: SHCJsonEncoder
.. autofunction:: from_json

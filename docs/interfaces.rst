
.. _interfaces:

Interfaces
==========

Modules in the `shc.interfaces` package provide Interface classes which can be instantiated in an SHC project to connect the SHC server to external systems like KNX busses, DMX equipment or other SHC instances.
Typically, an interface instance connects to a single external system via a given address (e.g. a single remote SHC instance, a KNX bus) and provides methods to create :ref:`Connectable objects <base.connectable_objects>` for individual items/values within that system (e.g. remote SHC api objects, KNX group addresses).
These *Connectable* objects can then be used to interact with the remote system.
Multiple instances of the same interface class can be created to connect to multiple external systems of the same type.

See the following sections for more information about a specific interface:

.. toctree::
    :glob:
    :maxdepth: 1

    interfaces/*

For creating custom SHC interfaces, see the following guideline:

.. toctree::
    :maxdepth: 1

    interfaces_custom


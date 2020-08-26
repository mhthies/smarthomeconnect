
.. _timer:

Timers
======

.. py:currentmodule:: shc.timer


The :mod:`shc.timer` module provides two different kinds of timer objects to be used in SHC configuration:
"Schedule Timers" are *Subscribable* objects, that publish a `None` value regularly, based on some configurable schedule, e.g. with a fixed interval, a pattern of allowed datetime values or some amout of time after application startup.
They are usually used to trigger a :ref:`Logic Handler <base.logic-handlers>` on a regular base.
"Delay Timers" on the other hand, take a subscribable object and re-publish its published values after a certain delay time (following different rules)


.. _timer.schedule-timers:

Schedule Timers
---------------

.. autoclass:: Once
    :members:
    :special-members:

.. autoclass:: Every
    :members:
    :special-members:

.. autoclass:: At
    :members:
    :special-members:

.. autoclass:: EveryNth

.. autofunction:: _random_time


Convenience Timer Decorators
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. autodecorator:: once
.. autodecorator:: every
.. autodecorator:: at


.. _timer.delay-timers:

Delay Timers
------------

TODO
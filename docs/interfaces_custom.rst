
Creating Custom Interfaces
--------------------------

TODO


Interface Base and Helper Classes Reference
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. automodule:: shc.supervisor

    .. autoclass:: AbstractInterface
        :members:

    .. autoclass:: ServiceStatus

    .. autoclass:: InterfaceStatus

    .. autofunction:: interface_failure


.. automodule:: shc.interfaces._helper

    .. autoclass:: ReadableStatusInterface

        .. automethod:: _get_status

    .. autoclass:: SubscribableStatusInterface

    .. autoclass:: SubscribableStatusConnector

        .. automethod:: update_status

    .. autoclass:: SupervisedClientInterface

        .. automethod:: __init__
        .. automethod:: _connect
        .. automethod:: _run
        .. automethod:: _subscribe
        .. automethod:: _disconnect
        .. automethod:: wait_running

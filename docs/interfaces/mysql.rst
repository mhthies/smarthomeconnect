
MySQL Database Interface
========================

The MySQL interface allows to using a MySQL (or MariaDB or Percona) server for :ref:`data_logging` and/or persistence.

Setup
-----

The MySQL interface does (currently) not include automated database setup or database schema migration, so the database needs to be set up manually.
Typically, this includes chosing a secure password for the database connection and running the following commands in a mysql console with root privileges:

.. code-block:: mysql

    CREATE DATABASE 'shc';
    CREATE USER 'shc'@'localhost' IDENTIFIED BY '<password>';
    GRANT SELECT, INSERT, UPDATE ON shc.* TO  'shc'@'localhost';
    FLUSH PRIVILEGES;

    USE shc;

    CREATE TABLE log (
        name VARCHAR(256) NOT NULL,
        ts DATETIME(6) NOT NULL,
        value_int INTEGER,
        value_float FLOAT,
        value_str LONGTEXT,
        KEY name_ts(name, ts)
    );

    CREATE TABLE `persistence` (
        name VARCHAR(256) NOT NULL,
        ts DATETIME(6) NOT NULL,
        value LONGTEXT,
        UNIQUE KEY name(name)
    );

Usage
-----

With the database setup listed above, the database can be used in an SHC project with the following code (or similar)::

    import shc
    import shc.interfaces.mysql

    # you may want to load the database password from some configfile to keep it out of your project code
    mysql_interface = shc.interfaces.mysql.MySQLConnector(host="localhost", db="shc", user="shc", password="<password>")

    # ...

    # a variable with logging
    my_room_temperature = shc.Variable(float, "my_room_temperature") \
        # example for connecting to the real world:
        #.connect(mqtt_interface.topic_string("temp/my_room"), convert=true) \
        .connect(mysql_interface.variable(float, "my_room_temperature"))

    # a variable with persistence
    my_room_temperature = shc.Variable(bool, "temperature_control_active") \
        .connect(mysql_interface.persistence_variable(bool, "temperature_control_active"), read=true)


Module Documentation
--------------------

.. automodule:: shc.interfaces.mysql

    .. autoclass:: MySQLConnector

        .. automethod:: variable
        .. automethod:: persistence_variable

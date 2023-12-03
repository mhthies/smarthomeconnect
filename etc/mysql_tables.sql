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

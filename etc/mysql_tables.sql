CREATE TABLE log (
    name VARCHAR(256) NOT NULL,
    ts DATETIME NOT NULL,
    value VARCHAR(4096),
    KEY name_ts(name, ts)
);

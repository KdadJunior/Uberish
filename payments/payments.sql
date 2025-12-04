DROP TABLE IF EXISTS balances;

CREATE TABLE balances (
    username TEXT PRIMARY KEY,
    balance REAL NOT NULL DEFAULT 0.0
);


DROP TABLE IF EXISTS listings;

CREATE TABLE listings (
    listingid INTEGER PRIMARY KEY,
    driver_username TEXT NOT NULL,
    day TEXT NOT NULL,
    price REAL NOT NULL
);


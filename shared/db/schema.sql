-- Assets schema.
--
-- Design notes:
--  * asset_code is the natural PRIMARY KEY -> unique, indexed, O(1)-ish
--    lookups by code (SQLite B-tree, effectively O(log n)).
--  * We add secondary indices on the columns the tools filter by most
--    (employee_name, category, location) so search/recommend/aggregate tools
--    stay O(log n + k) instead of O(n) full scans as the table grows. On 21
--    rows this is academic; the point is the schema scales cleanly if the
--    client later loads thousands of assets.
--  * Column names use snake_case internally; the CSV's "Asset Code" style
--    headers are mapped during seeding.

DROP TABLE IF EXISTS assets;

CREATE TABLE assets (
    asset_code    TEXT PRIMARY KEY,
    asset_name    TEXT NOT NULL,
    category      TEXT NOT NULL,
    employee_name TEXT NOT NULL,
    location      TEXT NOT NULL,
    purchase_date TEXT NOT NULL           -- stored as-is (dd-Mon-yy) from source
);

CREATE INDEX idx_assets_employee ON assets(employee_name);
CREATE INDEX idx_assets_category ON assets(category);
CREATE INDEX idx_assets_location ON assets(location);
CREATE INDEX idx_assets_name     ON assets(asset_name);

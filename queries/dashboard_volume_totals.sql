SELECT
    COALESCE(SUM(foreign_trade_volume), 0) AS total_ft,
    COALESCE(SUM(memzuc_151_volume), 0)    AS total_151,
    COALESCE(SUM(memzuc_152_volume), 0)    AS total_152,
    COALESCE(SUM(credit_limit), 0)         AS total_limit
FROM CustomerDetail

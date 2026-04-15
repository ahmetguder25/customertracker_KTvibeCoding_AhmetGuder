-- T-SQL MERGE: insert or update a Customer row synced from SRVDNZ.
-- Replaces the SQLite ON CONFLICT(Customerid) DO UPDATE idiom.
-- Parameters (12):
--   1  Customerid            INT
--   2  CustomerName          NVARCHAR
--   3  credit_limit          DECIMAL
--   4  credit_limit_currency NVARCHAR
--   5  foreign_trade_volume  DECIMAL
--   6  memzuc_151_volume     DECIMAL
--   7  memzuc_152_volume     DECIMAL
--   8  value_segment         NVARCHAR
--   9  branch                NVARCHAR
--   10 region                NVARCHAR
--   11 portfolio_manager     NVARCHAR
--   12 CustomerClassName     NVARCHAR
MERGE INTO BOA.ZZZ.Customer AS target
USING (
    SELECT
        ?  AS Customerid,
        ?  AS CustomerName,
        ?  AS credit_limit,
        ?  AS credit_limit_currency,
        ?  AS foreign_trade_volume,
        ?  AS memzuc_151_volume,
        ?  AS memzuc_152_volume,
        ?  AS value_segment,
        ?  AS branch,
        ?  AS region,
        ?  AS portfolio_manager,
        ?  AS CustomerClassName
) AS source ON target.Customerid = source.Customerid
WHEN MATCHED THEN
    UPDATE SET
        CustomerName          = source.CustomerName,
        credit_limit          = source.credit_limit,
        credit_limit_currency = source.credit_limit_currency,
        foreign_trade_volume  = source.foreign_trade_volume,
        memzuc_151_volume     = source.memzuc_151_volume,
        memzuc_152_volume     = source.memzuc_152_volume,
        value_segment         = source.value_segment,
        branch                = source.branch,
        region                = source.region,
        portfolio_manager     = source.portfolio_manager,
        CustomerClassName     = source.CustomerClassName,
        IsStructured          = 1
WHEN NOT MATCHED THEN
    INSERT (
        Customerid, CustomerName, credit_limit, credit_limit_currency,
        foreign_trade_volume, memzuc_151_volume, memzuc_152_volume,
        value_segment, branch, region, portfolio_manager, CustomerClassName, IsStructured
    )
    VALUES (
        source.Customerid, source.CustomerName, source.credit_limit,
        source.credit_limit_currency, source.foreign_trade_volume,
        source.memzuc_151_volume, source.memzuc_152_volume,
        source.value_segment, source.branch, source.region,
        source.portfolio_manager, source.CustomerClassName, 1
    );

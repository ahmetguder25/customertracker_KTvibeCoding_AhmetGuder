SELECT 
    c.Customerid,
    c.CustomerName,
    c.PortfolioOwnerName,
    c.BranchName,
    c.ValueSegment,
    c.ReginalOfficeName,
    (
        SELECT TOP 1 CONVERT(BIGINT,ROUND(TotalLimit,0) ) as TotalLimit
        FROM BOADWH.FRG.ForeignTradeScenarioAndLabel f
        WHERE f.Customerid = c.Customerid
        ORDER BY f.ReportDate DESC
    ) AS TotalLimit,
    'TRY' AS credit_limit_currency,
    1 AS foreign_trade_volume,
    1 AS memzuc_151_volume,
    1 AS memzuc_152_volume
FROM BOADWH.CUS.Customer c
WHERE c.Customerid = ?

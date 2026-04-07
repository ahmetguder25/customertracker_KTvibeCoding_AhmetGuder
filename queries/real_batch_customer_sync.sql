SELECT 
    c.Customerid,
    c.CustomerName,
    c.PortfolioOwnerName as portfolio_manager,
    c.BranchName as branch,
    c.ValueSegment as value_segment,
    c.ReginalOfficeName as region,
    c.CustomerClassName,
    (
        SELECT TOP 1 CONVERT(BIGINT,ROUND(TotalLimit,0) ) as TotalLimit
        FROM BOADWH.FRG.ForeignTradeScenarioAndLabel f
        WHERE f.AccountNumber = c.Customerid
        ORDER BY f.ReportDate DESC
    ) AS TotalLimit,
    (
        SELECT TOP 1 KRISectorCode 
        FROM BOADWH.LNS.AssetQualityCustomerTable a
        WHERE a.AccountNumber = c.Customerid
        ORDER BY a.AssetQualityReportId DESC
    ) AS sector,
    'TRY' AS credit_limit_currency,
    1 AS foreign_trade_volume,
    1 AS memzuc_151_volume,
    1 AS memzuc_152_volume,
    1 AS IsStructured
FROM BOADWH.CUS.Customer c
WHERE c.Customerid IN ({ids})

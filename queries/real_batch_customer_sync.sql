SET NOCOUNT ON;

DROP TABLE IF EXISTS #a;
SELECT MAX(reportdate) as reportdate INTO #a FROM BOADWH.FRG.ForeignTradeScenarioandLabel;
 
DROP TABLE IF EXISTS #b;
SELECT MAX(AssetQualityReportID) as AssetQualityReportID INTO #b FROM BOADWH.LNS.AssetQualityCustomerTable;
 
DROP TABLE IF EXISTS #c;
SELECT AccountNumber, KRISectorCode INTO #c
FROM BOADWH.LNS.AssetQualityCustomerTable a
WHERE a.AccountNumber in ({ids})
  AND AssetQualityReportId = (SELECT AssetQualityReportId FROM #b);

DROP TABLE IF EXISTS #d;
SELECT AccountNumber, CONVERT(BIGINT,ROUND(TotalLimit,0) ) as TotalLimit
INTO #d
FROM BOADWH.FRG.ForeignTradeScenarioAndLabel f
WHERE f.AccountNumber in ({ids})
  AND ReportDate = (SELECT ReportDate FROM #a);
 
SELECT 
    c.Customerid AS Customerid,
    c.CustomerName AS CustomerName,
    c.PortfolioOwnerName AS portfolio_manager,
    c.BranchName AS branch,
    c.ValueSegment AS value_segment,
    c.ReginalOfficeName AS region,
    c.CustomerClassName AS CustomerClassName,
    f1.TotalLimit AS TotalLimit,
    a1.KRISectorCode AS sector,
    'TRY' AS credit_limit_currency,
    1 AS foreign_trade_volume,
    1 AS memzuc_151_volume,
    1 AS memzuc_152_volume,
    1 AS IsStructured
FROM BOADWH.CUS.Customer c
OUTER APPLY ( SELECT TOP 1 KRISectorCode FROM #c a WHERE a.AccountNumber = c.Customerid ) as a1
OUTER APPLY ( SELECT TOP 1 TotalLimit FROM #d d WHERE d.AccountNumber = c.Customerid ) as f1
WHERE c.Customerid IN ({ids});

SELECT 
    c.Customerid,
    c.CustomerName,
    c.PortfolioOwnerName,
    c.BranchName,
    c.ValueSegment,
    c.ReginalOfficeName,
    (
        SELECT TOP 1 TotalLimit 
        FROM BOADWH.FRG.ForeignTradeScenarioAndLabel f
        WHERE f.Customerid = c.Customerid
        ORDER BY f.ReportDate DESC
    ) AS TotalLimit
FROM BOADWH.CUS.Customer c
WHERE c.Customerid = ?

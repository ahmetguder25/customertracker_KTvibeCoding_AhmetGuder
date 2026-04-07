SELECT 
    Customerid AS Customerid, 
    CustomerName AS CustomerName, 
    Null AS sector, 
    BranchName AS branch, 
    ReginalOfficeName AS region, 
    ValueSegment AS value_segment, 
    PortfolioOwnerName AS portfolio_manager, 
    CustomerClassName AS CustomerClassName,
    1 AS IsStructured
FROM BOADWH.CUS.Customer
WHERE Customerid = ?

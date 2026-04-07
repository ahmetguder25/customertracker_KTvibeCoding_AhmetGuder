SELECT 
    Customerid, 
    CustomerName, 
    Null as sector, 
    BranchName as branch, 
    ReginalOfficeName as region, 
    ValueSegment as value_segment, 
    PortfolioOwnerName as portfolio_manager, 
    CustomerClassName,
    1 as IsStructured
FROM BOADWH.CUS.Customer
WHERE Customerid = ?

INSERT INTO Customer (
    Customerid, CustomerName, PortfolioOwnerName, 
    BranchName, ValueSegment, RegionalOfficeName
) VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(Customerid) DO UPDATE SET
    CustomerName = excluded.CustomerName,
    PortfolioOwnerName = excluded.PortfolioOwnerName,
    BranchName = excluded.BranchName,
    ValueSegment = excluded.ValueSegment,
    RegionalOfficeName = excluded.RegionalOfficeName

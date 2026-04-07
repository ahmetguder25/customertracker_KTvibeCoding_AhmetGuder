SELECT Customerid, CustomerName, PortfolioOwnerName, BranchName, ValueSegment, RegionalOfficeName
FROM CUS.Customer
WHERE Customerid = ?

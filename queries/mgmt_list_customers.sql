SELECT c.Customerid, c.CustomerName, c.PortfolioOwnerName AS portfolio_manager, cd.sector
FROM Customer c
JOIN CustomerDetail cd ON c.Customerid = cd.Customerid
ORDER BY c.Customerid DESC

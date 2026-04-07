SELECT c.Customerid, c.CustomerName, c.PortfolioOwnerName AS portfolio_manager, cd.sector, cd.LogoFilename, cd.credit_limit
FROM Customer c
JOIN CustomerDetail cd ON c.Customerid = cd.Customerid
WHERE c.Customerid = ?

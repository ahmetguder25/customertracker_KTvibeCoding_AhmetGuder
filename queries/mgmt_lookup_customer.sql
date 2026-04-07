SELECT c.Customerid, c.CustomerName, c.PortfolioOwnerName AS portfolio_manager, cd.sector,
       CASE WHEN cd.Customerid IS NOT NULL THEN 1 ELSE 0 END AS IsStructured
FROM Customer c
LEFT JOIN CustomerDetail cd ON c.Customerid = cd.Customerid
WHERE c.Customerid = ?

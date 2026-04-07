SELECT c.Customerid, c.CustomerName, c.PortfolioOwnerName AS portfolio_manager, cd.sector,
       COUNT(d.id) AS deal_count, SUM(d.deal_size) AS total_deal_size
FROM Customer c
JOIN CustomerDetail cd ON c.Customerid = cd.Customerid
LEFT JOIN CustomerDeals d ON c.Customerid = d.customerid
GROUP BY c.Customerid
ORDER BY c.CustomerName

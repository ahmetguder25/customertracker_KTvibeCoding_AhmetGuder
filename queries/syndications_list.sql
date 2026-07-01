SELECT m.DealId, m.ProductCode, p.ProductName, c.CustomerName, c.Customerid,
       s.Amount, s.Pricing, s.FEC, s.Status, s.ExpectedDate
FROM BOA.STR.MainDeals m
JOIN BOA.STR.Syndication s ON m.DealId = s.DealId
JOIN BOA.CUS.Customer c ON m.CustomerId = c.Customerid
LEFT JOIN BOA.COR.Product p ON m.ProductCode = p.ProductCode
ORDER BY s.ExpectedDate DESC

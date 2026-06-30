SELECT m.DealId, m.ProductCode, c.CustomerName, c.Customerid,
       s.Amount, s.Pricing, s.FEC, s.Status, s.ExpectedDate
FROM BOA.STR.MainDeals m
JOIN BOA.STF.ForeignLoan s ON m.DealId = s.DealId
JOIN BOA.CUS.Customer c ON m.CustomerId = c.Customerid
ORDER BY s.ExpectedDate DESC

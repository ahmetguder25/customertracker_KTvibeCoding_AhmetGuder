SELECT Customerid, CustomerName, sector, branch, region, value_segment, portfolio_manager, IsStructured
FROM Customer
WHERE Customerid = ?

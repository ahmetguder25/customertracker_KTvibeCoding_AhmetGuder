SELECT Customerid, CustomerName, sector, branch, region, value_segment, portfolio_manager, CustomerClassName, IsStructured
FROM Customer
WHERE Customerid = ?

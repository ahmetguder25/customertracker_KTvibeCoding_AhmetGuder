SELECT d.*, c.CustomerName
FROM CustomerDeals d
JOIN Customer c ON d.customerid = c.Customerid
WHERE d.id = ?

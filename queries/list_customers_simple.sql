SELECT c.Customerid, c.CustomerName
FROM Customer c
JOIN CustomerDetail cd ON c.Customerid = cd.Customerid
ORDER BY c.CustomerName

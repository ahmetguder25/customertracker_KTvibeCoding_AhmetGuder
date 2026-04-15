SELECT d.*, c.CustomerName
FROM BOA.ZZZ.CustomerDeals d
JOIN BOA.ZZZ.Customer c ON d.customerid = c.Customerid
WHERE d.id = ?

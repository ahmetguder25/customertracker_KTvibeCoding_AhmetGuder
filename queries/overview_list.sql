SELECT c.*, COUNT(d.id) AS deal_count, SUM(d.deal_size) AS total_deal_size
FROM Customer c
LEFT JOIN CustomerDeals d ON c.Customerid = d.customerid
WHERE c.IsStructured = 1
GROUP BY c.Customerid
ORDER BY c.CustomerName

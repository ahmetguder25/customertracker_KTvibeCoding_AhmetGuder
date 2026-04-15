SELECT d.*, c.CustomerName, c.sector, c.credit_limit, c.value_segment,
       c.branch, c.region, c.portfolio_manager, c.foreign_trade_volume,
       c.memzuc_151_volume, c.memzuc_152_volume
FROM BOA.ZZZ.CustomerDeals d
JOIN BOA.ZZZ.Customer c ON d.customerid = c.Customerid
WHERE c.IsStructured = 1
ORDER BY c.CustomerName, d.created_at DESC

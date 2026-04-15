SELECT
    c.Customerid, c.CustomerName, c.credit_limit, c.credit_limit_currency,
    c.foreign_trade_volume, c.memzuc_151_volume, c.memzuc_152_volume,
    c.value_segment, c.branch, c.sector, c.region, c.portfolio_manager,
    c.CustomerClassName, c.IsStructured, c.LogoFilename,
    COUNT(d.id) AS deal_count, SUM(d.deal_size) AS total_deal_size
FROM BOA.ZZZ.Customer c
LEFT JOIN BOA.ZZZ.CustomerDeals d ON c.Customerid = d.customerid
WHERE c.IsStructured = 1
GROUP BY
    c.Customerid, c.CustomerName, c.credit_limit, c.credit_limit_currency,
    c.foreign_trade_volume, c.memzuc_151_volume, c.memzuc_152_volume,
    c.value_segment, c.branch, c.sector, c.region, c.portfolio_manager,
    c.CustomerClassName, c.IsStructured, c.LogoFilename
ORDER BY c.CustomerName

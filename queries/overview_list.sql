SELECT
    c.Customerid, c.CustomerName, c.credit_limit, c.credit_limit_currency,
    c.foreign_trade_volume, c.memzuc_151_volume, c.memzuc_152_volume,
    c.value_segment, c.branch, c.sector, c.region, c.portfolio_manager,
    c.CustomerClassName, c.IsStructured, c.LogoFilename,
    COUNT(d.DealId) AS deal_count, 0 AS total_deal_size
FROM BOA.CUS.Customer c
LEFT JOIN BOA.STR.MainDeals d ON c.Customerid = d.CustomerId
WHERE c.IsStructured = 1
GROUP BY
    c.Customerid, c.CustomerName, c.credit_limit, c.credit_limit_currency,
    c.foreign_trade_volume, c.memzuc_151_volume, c.memzuc_152_volume,
    c.value_segment, c.branch, c.sector, c.region, c.portfolio_manager,
    c.CustomerClassName, c.IsStructured, c.LogoFilename
ORDER BY c.CustomerName

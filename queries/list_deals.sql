SELECT d.*, c.CustomerName, cd.sector, cd.credit_limit, c.ValueSegment AS value_segment,
       c.BranchName AS branch, c.RegionalOfficeName AS region, c.PortfolioOwnerName AS portfolio_manager, cd.foreign_trade_volume,
       cd.memzuc_151_volume, cd.memzuc_152_volume
FROM CustomerDeals d
JOIN Customer c ON d.customerid = c.Customerid
JOIN CustomerDetail cd ON c.Customerid = cd.Customerid
ORDER BY d.created_at DESC

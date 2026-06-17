SELECT d.DealId AS id, d.ProductCode, NULL AS deal_size, NULL AS currency, NULL AS status, NULL AS created_at
FROM BOA.STR.MainDeals d
WHERE d.CustomerId = ?
ORDER BY d.DealId DESC

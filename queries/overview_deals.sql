SELECT *
FROM BOA.ZZZ.CustomerDeals
WHERE customerid = ?
  AND IsActive = 1
ORDER BY created_at DESC

SELECT status, COUNT(*) AS cnt
FROM BOA.ZZZ.CustomerDeals
WHERE IsActive = 1
GROUP BY status

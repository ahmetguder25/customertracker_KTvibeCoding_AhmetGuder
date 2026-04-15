SELECT status, COUNT(*) AS cnt
FROM BOA.ZZZ.CustomerDeals
GROUP BY status

SELECT status, COUNT(*) AS cnt
FROM CustomerDeals
GROUP BY status

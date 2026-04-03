SELECT region, COUNT(*) AS cnt
FROM Customer
WHERE IsStructured = 1
  AND region IS NOT NULL
  AND region != ''
GROUP BY region

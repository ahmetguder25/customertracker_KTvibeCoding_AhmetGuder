SELECT region, COUNT(*) AS cnt
FROM BOA.ZZZ.Customer
WHERE IsStructured = 1
  AND region IS NOT NULL
  AND region != ''
GROUP BY region

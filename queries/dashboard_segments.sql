SELECT value_segment, COUNT(*) AS cnt
FROM Customer
WHERE IsStructured = 1
  AND value_segment IS NOT NULL
  AND value_segment != ''
GROUP BY value_segment

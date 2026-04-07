SELECT c.ValueSegment AS value_segment, COUNT(*) AS cnt
FROM Customer c
JOIN CustomerDetail cd ON c.Customerid = cd.Customerid
WHERE c.ValueSegment IS NOT NULL
  AND c.ValueSegment != ''
GROUP BY c.ValueSegment

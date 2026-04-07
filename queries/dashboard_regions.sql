SELECT c.RegionalOfficeName AS region, COUNT(*) AS cnt
FROM Customer c
JOIN CustomerDetail cd ON c.Customerid = cd.Customerid
WHERE c.RegionalOfficeName IS NOT NULL
  AND c.RegionalOfficeName != ''
GROUP BY c.RegionalOfficeName

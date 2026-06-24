SELECT *
FROM BOA.CUS.Comment
WHERE customer_id = ?
  AND IsActive = 1
ORDER BY created_at DESC

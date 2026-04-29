SELECT *
FROM BOA.ZZZ.Comment
WHERE customer_id = ?
  AND IsActive = 1
ORDER BY created_at DESC

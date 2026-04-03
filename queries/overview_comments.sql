SELECT *
FROM Comment
WHERE customer_id = ?
ORDER BY created_at DESC

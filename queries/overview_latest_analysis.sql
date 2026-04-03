SELECT *
FROM CustomerAnalysis
WHERE customer_id = ? AND LanguageId = ?
ORDER BY created_at DESC
LIMIT 1

SELECT TOP 1 *
FROM BOA.ZZZ.CustomerAnalysis
WHERE customer_id = ? AND LanguageId = ?
ORDER BY created_at DESC

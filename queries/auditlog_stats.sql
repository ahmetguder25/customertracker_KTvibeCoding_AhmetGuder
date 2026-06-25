-- Multiple result sets are typically returned by executing separate queries or joined
-- We'll just provide a few queries to be run sequentially for stats.
-- Query 1: Total requests today
SELECT COUNT(*) as TotalRequests 
FROM BOA.COR.AuditLog 
WHERE CAST(Timestamp AS DATE) = CAST(GETDATE() AS DATE);

-- Query 2: Unique users today
SELECT COUNT(DISTINCT UserID) as UniqueUsers
FROM BOA.COR.AuditLog
WHERE CAST(Timestamp AS DATE) = CAST(GETDATE() AS DATE) AND UserID IS NOT NULL;

-- Query 3: Error count today (status >= 400)
SELECT COUNT(*) as ErrorCount
FROM BOA.COR.AuditLog
WHERE CAST(Timestamp AS DATE) = CAST(GETDATE() AS DATE) AND StatusCode >= 400;

-- Query 4: Avg response time today
SELECT ISNULL(AVG(DurationMs), 0) as AvgResponseTime
FROM BOA.COR.AuditLog
WHERE CAST(Timestamp AS DATE) = CAST(GETDATE() AS DATE);

INSERT INTO BOA.COR.AuditLog 
    (UserID, Username, Environment, Method, Path, Blueprint, Endpoint,
     StatusCode, DurationMs, IPAddress, UserAgent, ErrorMessage, RequestBody)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

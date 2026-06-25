CREATE TABLE BOA.COR.AuditLog (
    LogID         BIGINT IDENTITY(1,1) PRIMARY KEY,
    Timestamp     DATETIME NOT NULL DEFAULT GETDATE(),
    UserID        INT,
    Username      NVARCHAR(100),
    Environment   NVARCHAR(20),
    Method        NVARCHAR(10),
    Path          NVARCHAR(500),
    Blueprint     NVARCHAR(50),
    Endpoint      NVARCHAR(100),
    StatusCode    SMALLINT,
    DurationMs    INT,
    IPAddress     NVARCHAR(45),
    UserAgent     NVARCHAR(300),
    ErrorMessage  NVARCHAR(2000),
    RequestBody   NVARCHAR(2000)
)

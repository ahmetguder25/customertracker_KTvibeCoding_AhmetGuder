CREATE TABLE BOA.COR.Stakeholder (
    StakeholderID INT IDENTITY(5100001,1) PRIMARY KEY,
    FullName      NVARCHAR(200) NOT NULL,
    Organization  NVARCHAR(200),
    Department    NVARCHAR(200),
    Email         NVARCHAR(200),
    IsActive      TINYINT NOT NULL DEFAULT 1,
    CreatedAt     DATETIME NOT NULL DEFAULT GETDATE()
)

CREATE TABLE BOA.WIT.WorkItem (
    ItemID      INT IDENTITY(4100001,1) PRIMARY KEY,
    ParentType  NVARCHAR(20) NOT NULL,
    ParentID    INT NOT NULL,
    Title       NVARCHAR(300) NOT NULL,
    Description NVARCHAR(MAX),
    Status      NVARCHAR(20) NOT NULL DEFAULT 'not_started',
    Deadline    DATE,
    SortOrder   INT NOT NULL DEFAULT 0,
    IsActive    TINYINT NOT NULL DEFAULT 1,
    CreatedAt   DATETIME NOT NULL DEFAULT GETDATE(),
    UpdatedAt   DATETIME
)

CREATE TABLE BOA.ZZZ.WorkSubItem (
    SubItemID    INT IDENTITY(4110001,1) PRIMARY KEY,
    ParentItemID INT NOT NULL,
    Title        NVARCHAR(300) NOT NULL,
    Status       NVARCHAR(20) NOT NULL DEFAULT 'not_started',
    Deadline     DATE,
    SortOrder    INT NOT NULL DEFAULT 0,
    IsActive     TINYINT NOT NULL DEFAULT 1,
    CreatedAt    DATETIME NOT NULL DEFAULT GETDATE(),
    FOREIGN KEY (ParentItemID) REFERENCES BOA.ZZZ.WorkItem(ItemID)
)

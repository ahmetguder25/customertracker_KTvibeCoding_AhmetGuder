CREATE TABLE BOA.WIT.WorkItemAssignee (
    AssigneeID    INT IDENTITY(4130001,1) PRIMARY KEY,
    ItemID        INT NOT NULL,
    StakeholderID INT,
    UserID        INT,
    IsActive      TINYINT NOT NULL DEFAULT 1,
    FOREIGN KEY (ItemID) REFERENCES BOA.WIT.WorkItem(ItemID)
)

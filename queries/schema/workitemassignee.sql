CREATE TABLE BOA.ZZZ.WorkItemAssignee (
    AssigneeID    INT IDENTITY(4130001,1) PRIMARY KEY,
    ItemID        INT NOT NULL,
    StakeholderID INT NOT NULL,
    IsActive      TINYINT NOT NULL DEFAULT 1,
    FOREIGN KEY (ItemID)        REFERENCES BOA.ZZZ.WorkItem(ItemID),
    FOREIGN KEY (StakeholderID) REFERENCES BOA.ZZZ.Stakeholder(StakeholderID)
)

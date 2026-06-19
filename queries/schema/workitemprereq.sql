CREATE TABLE BOA.ZZZ.WorkItemPrerequisite (
    LinkID         INT IDENTITY(4120001,1) PRIMARY KEY,
    ItemID         INT NOT NULL,
    RequiresItemID INT NOT NULL,
    IsActive       TINYINT NOT NULL DEFAULT 1,
    FOREIGN KEY (ItemID)         REFERENCES BOA.ZZZ.WorkItem(ItemID),
    FOREIGN KEY (RequiresItemID) REFERENCES BOA.ZZZ.WorkItem(ItemID)
)

SET IDENTITY_INSERT BOA.WIT.WorkItem ON;
INSERT INTO BOA.WIT.WorkItem (ItemID, ParentType, ParentID, Title, Description, Status, Deadline, SortOrder, IsActive, CreatedAt, UpdatedAt)
SELECT ItemID, ParentType, ParentID, Title, Description, Status, Deadline, SortOrder, IsActive, CreatedAt, UpdatedAt
FROM BOA.ZZZ.WorkItem z
WHERE NOT EXISTS (SELECT 1 FROM BOA.WIT.WorkItem w WHERE w.ItemID = z.ItemID);
SET IDENTITY_INSERT BOA.WIT.WorkItem OFF;

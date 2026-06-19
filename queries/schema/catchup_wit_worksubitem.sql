SET IDENTITY_INSERT BOA.WIT.WorkSubItem ON;
INSERT INTO BOA.WIT.WorkSubItem (SubItemID, ParentItemID, Title, Status, Deadline, SortOrder, IsActive, CreatedAt)
SELECT z.SubItemID, z.ParentItemID, z.Title, z.Status, z.Deadline, z.SortOrder, z.IsActive, z.CreatedAt
FROM BOA.ZZZ.WorkSubItem z
WHERE NOT EXISTS (SELECT 1 FROM BOA.WIT.WorkSubItem w WHERE w.SubItemID = z.SubItemID)
  AND EXISTS (SELECT 1 FROM BOA.WIT.WorkItem wi WHERE wi.ItemID = z.ParentItemID);
SET IDENTITY_INSERT BOA.WIT.WorkSubItem OFF;

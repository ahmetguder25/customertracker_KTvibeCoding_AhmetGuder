SET IDENTITY_INSERT BOA.WIT.WorkSubItem ON;
INSERT INTO BOA.WIT.WorkSubItem (SubItemID, ParentItemID, Title, Status, Deadline, SortOrder, IsActive, CreatedAt)
SELECT si.SubItemID, si.ParentItemID, si.Title, si.Status, si.Deadline, si.SortOrder, si.IsActive, si.CreatedAt
FROM BOA.ZZZ.WorkSubItem si
WHERE EXISTS (SELECT 1 FROM BOA.WIT.WorkItem wi WHERE wi.ItemID = si.ParentItemID);
SET IDENTITY_INSERT BOA.WIT.WorkSubItem OFF;

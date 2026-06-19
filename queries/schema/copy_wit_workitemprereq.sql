SET IDENTITY_INSERT BOA.WIT.WorkItemPrerequisite ON;
INSERT INTO BOA.WIT.WorkItemPrerequisite (LinkID, ItemID, RequiresItemID, IsActive)
SELECT p.LinkID, p.ItemID, p.RequiresItemID, p.IsActive
FROM BOA.ZZZ.WorkItemPrerequisite p
WHERE EXISTS (SELECT 1 FROM BOA.WIT.WorkItem wi WHERE wi.ItemID = p.ItemID)
  AND EXISTS (SELECT 1 FROM BOA.WIT.WorkItem wi WHERE wi.ItemID = p.RequiresItemID);
SET IDENTITY_INSERT BOA.WIT.WorkItemPrerequisite OFF;

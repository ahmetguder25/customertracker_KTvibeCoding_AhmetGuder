SET IDENTITY_INSERT BOA.WIT.WorkItemAssignee ON;
INSERT INTO BOA.WIT.WorkItemAssignee (AssigneeID, ItemID, StakeholderID, UserID, IsActive)
SELECT a.AssigneeID, a.ItemID, a.StakeholderID, a.UserID, a.IsActive
FROM BOA.ZZZ.WorkItemAssignee a
WHERE EXISTS (SELECT 1 FROM BOA.WIT.WorkItem wi WHERE wi.ItemID = a.ItemID);
SET IDENTITY_INSERT BOA.WIT.WorkItemAssignee OFF;

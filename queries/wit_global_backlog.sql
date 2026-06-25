-- Global backlog: all work items across projects and syndications
SELECT
    w.ItemID,
    w.ParentType,
    w.ParentID,
    w.Title,
    w.Description,
    w.Status,
    w.Deadline,
    w.SortOrder,
    w.IsActive,
    w.CreatedAt,
    w.UpdatedAt,
    CASE w.ParentType
        WHEN 'project' THEN (
            SELECT p.ProjectName FROM BOA.STR.Project p WHERE p.ProjectID = w.ParentID
        )
        WHEN 'syndication' THEN (
            SELECT c.CustomerName + ' / Syndication #' + CAST(m.DealId AS NVARCHAR)
            FROM BOA.STR.MainDeals m
            JOIN BOA.CUS.Customer c ON m.CustomerId = c.Customerid
            WHERE m.DealId = w.ParentID
        )
    END AS ParentName,
    (
        SELECT STRING_AGG(
            COALESCE('S-' + CAST(wa.StakeholderID AS NVARCHAR), 'U-' + CAST(wa.UserID AS NVARCHAR)),
            ','
        )
        FROM BOA.WIT.WorkItemAssignee wa
        WHERE wa.ItemID = w.ItemID AND wa.IsActive = 1
    ) AS AssigneeIDs,
    (
        SELECT STRING_AGG(
            COALESCE(s.FullName, u.username + ' ' + ISNULL(u.surname, '')),
            ', '
        )
        FROM BOA.WIT.WorkItemAssignee wa
        LEFT JOIN BOA.COR.Stakeholder s ON wa.StakeholderID = s.StakeholderID
        LEFT JOIN BOA.COR.[User] u ON wa.UserID = u.id
        WHERE wa.ItemID = w.ItemID AND wa.IsActive = 1
    ) AS Assignees,
    (
        SELECT COUNT(*) FROM BOA.WIT.WorkSubItem si
        WHERE si.ParentItemID = w.ItemID AND si.IsActive = 1
    ) AS SubItemCount,
    (
        SELECT COUNT(*) FROM BOA.WIT.WorkSubItem si
        WHERE si.ParentItemID = w.ItemID AND si.IsActive = 1 AND si.Status = 'done'
    ) AS SubItemDone
FROM BOA.WIT.WorkItem w
WHERE w.IsActive = 1
ORDER BY
    w.ParentType ASC,
    w.ParentID ASC,
    w.SortOrder ASC,
    w.Deadline ASC,
    w.ItemID ASC

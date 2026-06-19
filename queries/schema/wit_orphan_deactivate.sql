-- Deactivate Syndication items whose DealId no longer exists
UPDATE BOA.WIT.WorkItem SET IsActive=0
WHERE ParentType='syndication' AND IsActive=1
    AND ParentID NOT IN (SELECT DealId FROM BOA.STR.MainDeals);

-- Deactivate Project items whose ProjectID no longer exists
UPDATE BOA.WIT.WorkItem SET IsActive=0
WHERE ParentType='project' AND IsActive=1
    AND ParentID NOT IN (SELECT ProjectID FROM BOA.ZZZ.Project);

CREATE TABLE BOA.ZZZ.Project (
    ProjectID   INT IDENTITY(3200001,1) PRIMARY KEY,
    ProjectName NVARCHAR(300) NOT NULL,
    Description NVARCHAR(MAX),
    Status      NVARCHAR(50) NOT NULL DEFAULT 'Planning',
    Owner       NVARCHAR(100),
    StartDate   DATE,
    Deadline    DATE,
    ObjectiveID INT,
    IsActive    TINYINT NOT NULL DEFAULT 1,
    CreatedAt   DATETIME NOT NULL DEFAULT GETDATE(),
    UpdatedAt   DATETIME,
    FOREIGN KEY (ObjectiveID) REFERENCES BOA.ZZZ.Objective(ObjectiveID)
)

CREATE TABLE BOA.ZZZ.KeyResult (
    KRID          INT IDENTITY(3110001,1) PRIMARY KEY,
    ObjectiveID   INT NOT NULL,
    Title         NVARCHAR(300) NOT NULL,
    TargetValue   DECIMAL(18,2) NOT NULL DEFAULT 0,
    AchievedValue DECIMAL(18,2) NOT NULL DEFAULT 0,
    PipelineValue DECIMAL(18,2) NOT NULL DEFAULT 0,
    Unit          NVARCHAR(50),
    CalcMethod    NVARCHAR(20)  NOT NULL DEFAULT 'count',
    IsActive      TINYINT NOT NULL DEFAULT 1,
    FOREIGN KEY (ObjectiveID) REFERENCES BOA.ZZZ.Objective(ObjectiveID)
)

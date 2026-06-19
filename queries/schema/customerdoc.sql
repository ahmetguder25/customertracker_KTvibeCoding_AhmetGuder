CREATE TABLE BOA.COR.CustomerDocument (
    DocID        INT IDENTITY(1,1) PRIMARY KEY,
    CustomerID   INT NOT NULL,
    DocName      NVARCHAR(255) NOT NULL,
    DocTypeCode  INT NOT NULL,
    FileName     NVARCHAR(500) NOT NULL,
    FileExt      NVARCHAR(20)  NOT NULL,
    UploadedBy   NVARCHAR(100),
    UploadedAt   DATETIME DEFAULT CURRENT_TIMESTAMP,
    IsActive     BIT DEFAULT 1
)

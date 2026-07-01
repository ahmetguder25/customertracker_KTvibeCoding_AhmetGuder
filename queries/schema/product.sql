CREATE TABLE BOA.COR.Product (
    ProductID           INT IDENTITY(1,1) PRIMARY KEY,
    ProductCode         NVARCHAR(50)  NOT NULL,
    ProductName         NVARCHAR(200) NOT NULL,
    ResourceCode        NVARCHAR(50)  NULL,
    IsActive            TINYINT NOT NULL DEFAULT 1
)

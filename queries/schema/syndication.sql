CREATE TABLE BOA.STR.Syndication (
    DealId INT PRIMARY KEY,
    Amount FLOAT,
    Pricing FLOAT,
    FEC INT,
    Status NVARCHAR(50),
    ExpectedDate DATE,
    FOREIGN KEY (DealId) REFERENCES BOA.STR.MainDeals(DealId)
)

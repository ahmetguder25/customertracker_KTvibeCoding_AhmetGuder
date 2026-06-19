CREATE TABLE BOA.STR.MainDeals (
    DealId INT IDENTITY(1,1) PRIMARY KEY,
    ProductCode NVARCHAR(50),
    CustomerId INT NOT NULL,
    FOREIGN KEY (CustomerId) REFERENCES BOA.CUS.Customer(Customerid)
)

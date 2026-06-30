CREATE TABLE BOA.STF.ForeignLoanDetail (
    DealDetailId INT IDENTITY(1,1) PRIMARY KEY,
    DealId INT NOT NULL,
    BankName NVARCHAR(200),
    Amount FLOAT,
    OfferPricing FLOAT,
    FOREIGN KEY (DealId) REFERENCES BOA.STF.ForeignLoan(DealId)
)

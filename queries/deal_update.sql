UPDATE BOA.ZZZ.CustomerDeals
SET contact_name        = ?,
    deal_size           = ?,
    expected_pricing_pa = ?,
    currency            = ?,
    status              = ?,
    dealtype            = ?,
    notes               = ?
WHERE id = ?

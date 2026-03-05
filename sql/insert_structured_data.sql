-- =============================================================================
-- AGL Energy — Sample customer account data for agl_structured
-- Covers key churn scenarios:
--   CUST0003: HIGH RISK — property FOR SALE + bill shock (primary demo customer)
--   CUST0005: HIGH RISK — property FOR RENT (move-out imminent)
--   CUST0002: MEDIUM RISK — contract expiry in 45 days
--   CUST0004: MEDIUM RISK — bill shock + conditional discount removed
--   CUST0006: PROTECTED — life support (lead must NEVER be emitted)
--   CUST0007: PROTECTED — on hardship program (lead must NEVER be emitted)
--   CUST0001: LOW RISK — stable, no signals
--   CUST0008: LOW RISK — solar customer, net credit balance
-- =============================================================================

INSERT INTO [dbo].[agl_structured] (
    [account_id],
    [customer_id],
    [service_address],
    [tariff_name],
    [contract_type],
    [contract_end_date],
    [last_bill_amount],
    [prev_bill_amount],
    [conditional_discount_removed],
    [property_listing_status],
    [property_listing_date],
    [is_life_support],
    [is_hardship],
    [fuel_type]
)
VALUES
-- CUST0001: Low risk — stable variable customer, no churn signals
('ACC00001', 'CUST0001', '12 Acacia Ave, Chatswood NSW 2067',
 'AGL Essentials',   'VARIABLE', NULL,
 320.00, 310.00, 0, NULL,        NULL,                   0, 0, 'ELECTRICITY'),

-- CUST0002: Medium risk — fixed-term contract expiring in 45 days
-- Customers off contract are far more likely to start comparing and switch.
('ACC00002', 'CUST0002', '7 Banksia Rd, Parramatta NSW 2150',
 'AGL 1-Year Fixed', 'FIXED',    DATEADD(day, 45, GETUTCDATE()),
 280.00, 275.00, 0, NULL,        NULL,                   0, 0, 'ELECTRICITY'),

-- CUST0003: HIGH RISK — service address listed FOR SALE (detected 5 days ago)
--           + bill shock: $510 vs $380 last quarter (+34%)
--           Primary demo scenario: proactive property market signal + bill complaint
('ACC00003', 'CUST0003', '33 Wattle St, Ultimo NSW 2007',
 'AGL Standing Offer','VARIABLE', NULL,
 510.00, 380.00, 0, 'FOR_SALE',  DATEADD(day, -5, GETUTCDATE()), 0, 0, 'DUAL'),

-- CUST0004: Medium-high risk — bill shock ($445 vs $337, +32%) AND
--           conditional pay-on-time discount recently removed
('ACC00004', 'CUST0004', '91 Grevillea Cres, Homebush NSW 2140',
 'AGL Essentials',   'VARIABLE', NULL,
 445.00, 337.00, 1, NULL,        NULL,                   0, 0, 'ELECTRICITY'),

-- CUST0005: High risk — service address listed FOR RENT (2 days ago)
--           Classic move-out scenario: landlord is renting out the property
('ACC00005', 'CUST0005', '2/18 Jacaranda Pl, Pyrmont NSW 2009',
 'AGL Essentials',   'VARIABLE', NULL,
 195.00, 190.00, 0, 'FOR_RENT',  DATEADD(day, -2, GETUTCDATE()), 0, 0, 'ELECTRICITY'),

-- CUST0006: PROTECTED — life support equipment registered
--           AER-mandated: lead generation MUST be suppressed regardless of score
('ACC00006', 'CUST0006', '44 Boronia St, Penrith NSW 2750',
 'AGL Standing Offer','VARIABLE', NULL,
 620.00, 600.00, 0, NULL,        NULL,                   1, 0, 'ELECTRICITY'),

-- CUST0007: PROTECTED — active AGL hardship program customer
--           NECF obligations: must NOT be targeted for commercial retention offers
('ACC00007', 'CUST0007', '17 Wonga Rd, Blacktown NSW 2148',
 'AGL Essentials',   'VARIABLE', NULL,
 0.00,   290.00, 0, NULL,        NULL,                   0, 1, 'ELECTRICITY'),

-- CUST0008: Low risk — solar customer with feed-in tariff, net credit balance
--           Stable: bill credit due to solar export, no move-out or price signals
('ACC00008', 'CUST0008', '5 Mulga Way, Castle Hill NSW 2154',
 'AGL Solar Savers', 'VARIABLE', NULL,
 85.00,   95.00, 0, NULL,        NULL,                   0, 0, 'ELECTRICITY'),

-- CUST0009: Medium risk — contract expiring in 30 days + discount removed
--           Double signal: switching window opening AND loyalty discount gone
('ACC00009', 'CUST0009', '88 Bottlebrush Dr, Ryde NSW 2112',
 'AGL 2-Year Fixed', 'FIXED',    DATEADD(day, 30, GETUTCDATE()),
 310.00, 300.00, 1, NULL,        NULL,                   0, 0, 'DUAL'),

-- CUST0010: High risk — property FOR SALE + contract expiring in 20 days
--           Strongest possible combination: moving out AND coming off fixed term
('ACC00010', 'CUST0010', '101 Ironbark Ave, Penrith NSW 2750',
 'AGL 1-Year Fixed', 'FIXED',    DATEADD(day, 20, GETUTCDATE()),
 390.00, 370.00, 0, 'FOR_SALE',  DATEADD(day, -1, GETUTCDATE()), 0, 0, 'ELECTRICITY');
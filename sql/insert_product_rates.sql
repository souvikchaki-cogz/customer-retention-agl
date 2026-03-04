-- Sample advertised rates based on IMB Bank Australia Owner Occupier P&I rates as of Sep 2025.
-- This data is for demonstration purposes only.

INSERT INTO dbo.product_rates (product_name, advertised_rate, rate_type, last_updated) VALUES
('IMB 1-Year Fixed',        5.39, 'FIXED',    GETUTCDATE()),
('IMB 2-Year Fixed',        4.99, 'FIXED',    GETUTCDATE()),
('IMB 3-Year Fixed',        5.19, 'FIXED',    GETUTCDATE()),
('IMB 4-Year Fixed',        5.59, 'FIXED',    GETUTCDATE()),
('IMB Essentials Home Loan',5.66, 'VARIABLE', GETUTCDATE());
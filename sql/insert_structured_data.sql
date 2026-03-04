-- Sample data for the Structured table, extended with product_name and interest-only fields
-- Today's date for reference: 2025-09-21

INSERT INTO [dbo].[Structured] ([account_id], [customer_id], [product_name], [remaining_years], [is_broker_originated], [interest_rate], [is_interest_only], [interest_only_end_date]) VALUES
('ACC00001', 'CUST0001', 'IMB 3-Year Fixed',        5.25,  1, 3.75, 0, NULL),
('ACC00002', 'CUST0002', 'IMB Essentials Home Loan', 10.00, 0, 4.10, 0, NULL),
('ACC00003', 'CUST0003', 'IMB Essentials Home Loan',  2.50, 1, 5.00, 1, '2025-11-15'),
('ACC00004', 'CUST0004', 'IMB 2-Year Fixed',         15.00, 0, 3.25, 0, NULL),
('ACC00005', 'CUST0005', 'IMB Essentials Home Loan',  7.75, 0, 4.50, 0, NULL),
('ACC00006', 'CUST0006', 'IMB Essentials Home Loan',  1.20, 1, 6.00, 0, NULL),
('ACC00007', 'CUST0007', 'IMB 4-Year Fixed',         12.00, 0, 3.95, 1, '2026-08-01'),
('ACC00008', 'CUST0008', 'IMB 1-Year Fixed',          3.00, 1, 4.75, 0, NULL),
('ACC00009', 'CUST0009', 'IMB Essentials Home Loan',  8.50, 0, 3.60, 0, NULL),
('ACC00010', 'CUST0010', 'IMB 2-Year Fixed',          0.75, 1, 5.50, 0, NULL);
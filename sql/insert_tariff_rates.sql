-- =============================================================================
-- AGL Energy — Sample tariff rates for agl_tariff_rates
-- Based on publicly available AGL NSW residential rates (approximate, 2025-2026).
-- For demonstration purposes only.
--
-- Joined to agl_structured on tariff_name in activity_fetch_structured()
-- to enrich customer records with usage_rate_kwh and supply_charge.
-- feed_in_tariff is non-NULL only for solar-eligible tariffs.
-- =============================================================================

INSERT INTO [dbo].[agl_tariff_rates]
    ([tariff_name], [usage_rate_kwh], [supply_charge], [feed_in_tariff], [rate_type], [last_updated])
VALUES
-- Standing offer — highest usage rate, default tariff if no market offer applied
('AGL Standing Offer',  0.3295, 1.2100, NULL,   'FLAT',     GETUTCDATE()),

-- Essentials — most common market offer, flat rate
('AGL Essentials',      0.2890, 1.1800, NULL,   'FLAT',     GETUTCDATE()),

-- Fixed 1-year — competitive rate locked for 12 months
('AGL 1-Year Fixed',    0.2750, 1.1500, NULL,   'FLAT',     GETUTCDATE()),

-- Fixed 2-year — slightly higher than 1-year, longer price certainty
('AGL 2-Year Fixed',    0.2810, 1.1600, NULL,   'FLAT',     GETUTCDATE()),

-- Solar Savers — same usage rate as Essentials, includes feed-in tariff
-- feed_in_tariff: amount paid per kWh exported to the grid
('AGL Solar Savers',    0.2890, 1.1800, 0.0800, 'FLAT',     GETUTCDATE()),

-- Time of Use — lower off-peak rate, higher peak rate
-- Peak / shoulder / off-peak split is handled in the billing layer;
-- usage_rate_kwh here represents the off-peak rate for scoring purposes
('AGL Time of Use',     0.1850, 1.2000, NULL,   'TOU',      GETUTCDATE());
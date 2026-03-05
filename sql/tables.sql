-- =============================================================================
-- AGL Energy Customer Churn Retention System — Database Schema
-- All tables use the agl_ prefix for namespace isolation.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- agl_structured
-- Core customer account features used by the structured scoring engine.
-- Populated from AGL's CIS (Customer Information System).
-- Proactive churn signals: property_listing_status is set by the property
-- market scanning job (see agl_property_market_signals).
-- -----------------------------------------------------------------------------
CREATE TABLE [dbo].[agl_structured] (
    [id]                           INT           IDENTITY(1, 1)  NOT NULL,
    [account_id]                   VARCHAR(50)                   NOT NULL,
    [customer_id]                  VARCHAR(50)                   NOT NULL,
    [service_address]              NVARCHAR(255)                 NULL,       -- Full service address (used for property market X-ref)
    [tariff_name]                  NVARCHAR(100)                 NULL,       -- e.g. 'AGL Essentials', 'AGL 1-Year Fixed'
    [contract_type]                VARCHAR(20)                   NULL,       -- 'FIXED', 'VARIABLE', 'MARKET'
    [contract_end_date]            DATE                          NULL,       -- NULL = month-to-month (no fixed term)
    [last_bill_amount]             FLOAT(53)                     NULL,       -- Most recent quarterly bill ($AUD)
    [prev_bill_amount]             FLOAT(53)                     NULL,       -- Prior quarter bill ($AUD) — used for bill shock delta
    [conditional_discount_removed] BIT           NOT NULL DEFAULT 0,        -- 1 = pay-on-time or loyalty discount expired
    [property_listing_status]      VARCHAR(20)                   NULL,       -- NULL | 'FOR_SALE' | 'FOR_RENT'  (from property market scan)
    [property_listing_date]        DATE                          NULL,       -- Date address appeared on Domain / REA
    [is_life_support]              BIT           NOT NULL DEFAULT 0,        -- AER protected class — lead generation MUST be suppressed
    [is_hardship]                  BIT           NOT NULL DEFAULT 0,        -- On AGL hardship program — lead generation MUST be suppressed
    [fuel_type]                    VARCHAR(10)                   NULL,       -- 'ELECTRICITY' | 'GAS' | 'DUAL'
    CONSTRAINT [PK_agl_structured] PRIMARY KEY CLUSTERED ([id] ASC)
);


-- -----------------------------------------------------------------------------
-- agl_tariff_rates
-- Advertised tariff rates by product name.
-- Joined to agl_structured on tariff_name in activity_fetch_structured.
-- Replaces the banking dbo.product_rates table.
-- -----------------------------------------------------------------------------
CREATE TABLE [dbo].[agl_tariff_rates] (
    [tariff_name]    NVARCHAR(100) NOT NULL,           -- e.g. 'AGL Essentials', 'AGL Solar Savers'
    [usage_rate_kwh] FLOAT         NOT NULL,           -- Usage charge ($/kWh)
    [supply_charge]  FLOAT         NOT NULL,           -- Daily supply charge ($/day)
    [feed_in_tariff] FLOAT                 NULL,       -- Solar feed-in rate ($/kWh) — NULL if not applicable
    [rate_type]      VARCHAR(20)           NULL,       -- 'FLAT' | 'TOU' | 'DEMAND'
    [last_updated]   DATETIME2     NOT NULL,
    CONSTRAINT [PK_agl_tariff_rates] PRIMARY KEY CLUSTERED ([tariff_name])
);


-- -----------------------------------------------------------------------------
-- agl_notes
-- Operational stream of customer interaction notes (call centre, chat, CRM).
-- Source events for the Azure Durable Functions pipeline.
-- -----------------------------------------------------------------------------
CREATE TABLE [dbo].[agl_notes] (
    [note_id]     NVARCHAR(64)  NOT NULL,
    [customer_id] NVARCHAR(64)  NOT NULL,
    [created_ts]  DATETIME2     NOT NULL,
    [note_text]   NVARCHAR(MAX) NULL,
    CONSTRAINT [PK_agl_notes] PRIMARY KEY CLUSTERED ([note_id])
);


-- -----------------------------------------------------------------------------
-- agl_notes_snapshot
-- Point-in-time snapshot of agl_notes for replay / backtesting.
-- -----------------------------------------------------------------------------
CREATE TABLE [dbo].[agl_notes_snapshot] (
    [note_id]     NVARCHAR(64)  NOT NULL,
    [customer_id] NVARCHAR(64)  NOT NULL,
    [created_ts]  DATETIME2     NOT NULL,
    [note_text]   NVARCHAR(MAX) NULL,
    CONSTRAINT [PK_agl_notes_snapshot] PRIMARY KEY CLUSTERED ([note_id])
);


-- -----------------------------------------------------------------------------
-- agl_customers_snapshot
-- Historical snapshot of key account metrics for trend analysis.
-- Useful for tracking bill amount and tariff changes over time.
-- -----------------------------------------------------------------------------
CREATE TABLE [dbo].[agl_customers_snapshot] (
    [snapshot_id]   BIGINT    IDENTITY(1, 1) NOT NULL,
    [customer_id]   NVARCHAR(64)             NOT NULL,
    [snapshot_ts]   DATETIME2                NOT NULL,
    [tariff_name]   NVARCHAR(100)            NULL,
    [bill_amount]   FLOAT                    NULL,       -- Bill at time of snapshot ($AUD)
    [contract_type] VARCHAR(20)              NULL,
    CONSTRAINT [PK_agl_customers_snapshot] PRIMARY KEY CLUSTERED ([snapshot_id] ASC)
);


-- -----------------------------------------------------------------------------
-- agl_closures
-- Records confirmed account closures (actual churn events).
-- Used for model validation — ground truth for churn label.
-- closure_reason enables stratified analysis by churn driver.
-- -----------------------------------------------------------------------------
CREATE TABLE [dbo].[agl_closures] (
    [closure_id]     BIGINT     IDENTITY(1, 1) NOT NULL,
    [customer_id]    NVARCHAR(64)              NOT NULL,
    [closure_ts]     DATETIME2                 NOT NULL,
    [closure_reason] VARCHAR(50)               NULL,    -- 'MOVE_OUT' | 'PRICE_SWITCH' | 'UNKNOWN'
    CONSTRAINT [PK_agl_closures] PRIMARY KEY CLUSTERED ([closure_id] ASC)
);


-- -----------------------------------------------------------------------------
-- agl_rules_library
-- Versioned YAML rulesets driving the text matching engine.
-- Only one row should have status = 'ACTIVE' at any time.
-- New rules approved via the webapp are appended to the ACTIVE ruleset YAML
-- and a new ACTIVE version row is inserted (prior rows set to INACTIVE).
-- -----------------------------------------------------------------------------
CREATE TABLE [dbo].[agl_rules_library] (
    [version]      NVARCHAR(32)  NOT NULL,              -- Semantic version, e.g. '1.0.3'
    [status]       NVARCHAR(16)  NOT NULL,              -- 'ACTIVE' | 'DRAFT' | 'INACTIVE'
    [activated_ts] DATETIME2     NOT NULL,
    [ruleset_yaml] NVARCHAR(MAX) NOT NULL,
    CONSTRAINT [PK_agl_rules_library] PRIMARY KEY CLUSTERED ([version])
);


-- -----------------------------------------------------------------------------
-- agl_lead_cards
-- Output table — one row per retention lead generated by the pipeline.
-- Created by activity_write_lead_card when churn score >= LEAD_SCORE_THRESHOLD.
-- explanation_text is PII-scrubbed before insert.
-- -----------------------------------------------------------------------------
CREATE TABLE [dbo].[agl_lead_cards] (
    [lead_id]                  BIGINT        IDENTITY(1, 1) NOT NULL,
    [customer_id]              NVARCHAR(64)                 NOT NULL,
    [note_id]                  NVARCHAR(64)                 NULL,
    [score]                    FLOAT                        NOT NULL,   -- Churn score in [0, 1]
    [rule_hits_json]           NVARCHAR(MAX)                NULL,       -- JSON array of text rule hits
    [structured_snapshot_json] NVARCHAR(MAX)                NULL,       -- JSON snapshot of agl_structured features at time of scoring
    [explanation_text]         NVARCHAR(MAX)                NULL,       -- LLM-generated human-readable explanation (PII-scrubbed)
    [agent_version]            NVARCHAR(32)                 NULL,
    [ruleset_version]          NVARCHAR(32)                 NULL,
    [created_ts]               DATETIME2                    NOT NULL,
    CONSTRAINT [PK_agl_lead_cards] PRIMARY KEY CLUSTERED ([lead_id] ASC)
);


-- -----------------------------------------------------------------------------
-- agl_discovery_cards
-- AI-generated candidate churn trigger themes, created by the batch
-- discovery workflow (batch/discovery_workflow.py).
-- Analysts review CANDIDATE entries and APPROVE or REJECT via the webapp.
-- APPROVED entries are merged into the active ruleset in agl_rules_library.
-- -----------------------------------------------------------------------------
CREATE TABLE [dbo].[agl_discovery_cards] (
    [discovery_id]  BIGINT        IDENTITY(1, 1) NOT NULL,
    [phrase]        NVARCHAR(512)                NULL,       -- Human-readable trigger description
    [support]       INT                          NULL,       -- Count of customers exhibiting this behaviour
    [lift]          FLOAT                        NULL,       -- Lift over base churn rate
    [odds_ratio]    FLOAT                        NULL,       -- Odds ratio vs non-exhibiting population
    [fdr]           FLOAT                        NULL,       -- False discovery rate
    [examples_json] NVARCHAR(MAX)                NULL,       -- JSON array of example phrases
    [status]        NVARCHAR(16)                 NOT NULL DEFAULT 'CANDIDATE',  -- 'CANDIDATE' | 'APPROVED' | 'REJECTED'
    [created_ts]    DATETIME2                    NOT NULL,
    CONSTRAINT [PK_agl_discovery_cards] PRIMARY KEY CLUSTERED ([discovery_id] ASC)
);


-- -----------------------------------------------------------------------------
-- agl_property_market_signals   *** NEW — no banking equivalent ***
-- Populated by a scheduled job that scans Domain.com.au / REA Group listings
-- and fuzzy-matches listed property addresses against agl_structured.service_address.
--
-- This is the foundation for PROACTIVE churn detection:
-- a customer's property appearing on the market is the strongest possible
-- early signal of an imminent move-out — often weeks before they contact AGL.
--
-- Workflow:
--   1. Scheduled scanner job runs daily → inserts rows here
--   2. A separate trigger or job reads unactioned rows (actioned = 0)
--      → updates agl_structured.property_listing_status
--      → fires the Durable Functions pipeline proactively (no customer note required)
--   3. actioned is set to 1 once a lead card has been generated
-- -----------------------------------------------------------------------------
CREATE TABLE [dbo].[agl_property_market_signals] (
    [signal_id]       BIGINT        IDENTITY(1, 1) NOT NULL,
    [customer_id]     NVARCHAR(64)                 NOT NULL,   -- Matched from agl_structured
    [account_id]      VARCHAR(50)                  NULL,
    [service_address] NVARCHAR(255)                NOT NULL,   -- Address as stored in agl_structured
    [listing_address] NVARCHAR(255)                NULL,       -- Address as it appeared on the listing (may differ slightly)
    [match_score]     FLOAT                        NULL,       -- Fuzzy match confidence [0, 1]
    [listing_status]  VARCHAR(20)                  NOT NULL,   -- 'FOR_SALE' | 'FOR_RENT'
    [listing_url]     NVARCHAR(512)                NULL,       -- URL of the listing on Domain / REA
    [listing_price]   NVARCHAR(100)                NULL,       -- Price or rent (as string — may be 'Contact Agent')
    [detected_ts]     DATETIME2                    NOT NULL,   -- When the match was detected
    [actioned]        BIT           NOT NULL DEFAULT 0,        -- 0 = pending lead generation, 1 = lead card emitted
    [actioned_ts]     DATETIME2                    NULL,       -- When the lead card was generated
    CONSTRAINT [PK_agl_property_market_signals] PRIMARY KEY CLUSTERED ([signal_id] ASC)
);


-- -----------------------------------------------------------------------------
-- agl_triggers
-- Approved trigger phrases for display in the webapp /api/triggers endpoint.
-- Distinct from agl_rules_library (which holds full YAML rulesets):
-- this table provides a flat list for the triggers panel UI.
-- -----------------------------------------------------------------------------
CREATE TABLE [dbo].[agl_triggers] (
    [trigger_id]   INT           IDENTITY(1, 1) NOT NULL,
    [trigger_text] NVARCHAR(512)                NOT NULL,   -- Human-readable trigger phrase
    [severity]     NVARCHAR(16)                 NOT NULL,   -- 'CORE' (structured) | 'NOTE' (text/LLM)
    [created_ts]   DATETIME2     NOT NULL DEFAULT SYSDATETIME(),
    CONSTRAINT [PK_agl_triggers] PRIMARY KEY CLUSTERED ([trigger_id] ASC)
);


-- =============================================================================
-- Recommended indexes for query performance
-- =============================================================================

CREATE NONCLUSTERED INDEX [IX_agl_structured_customer_id]
    ON [dbo].[agl_structured] ([customer_id]);

CREATE NONCLUSTERED INDEX [IX_agl_structured_property_listing_status]
    ON [dbo].[agl_structured] ([property_listing_status])
    WHERE [property_listing_status] IS NOT NULL;  -- Partial index — only listed properties

CREATE NONCLUSTERED INDEX [IX_agl_lead_cards_customer_id]
    ON [dbo].[agl_lead_cards] ([customer_id], [created_ts] DESC);

CREATE NONCLUSTERED INDEX [IX_agl_notes_customer_id]
    ON [dbo].[agl_notes] ([customer_id], [created_ts] DESC);

CREATE NONCLUSTERED INDEX [IX_agl_property_market_signals_unactioned]
    ON [dbo].[agl_property_market_signals] ([actioned], [detected_ts])
    WHERE [actioned] = 0;  -- Partial index — only pending signals, optimises the scanner job

CREATE NONCLUSTERED INDEX [IX_agl_rules_library_active]
    ON [dbo].[agl_rules_library] ([status], [activated_ts] DESC)
    WHERE [status] = 'ACTIVE';  -- Partial index — optimises the hot-path ruleset load query

CREATE NONCLUSTERED INDEX [IX_agl_discovery_cards_status]
    ON [dbo].[agl_discovery_cards] ([status], [created_ts] DESC);
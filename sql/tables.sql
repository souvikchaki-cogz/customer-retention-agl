-- Snapshot tables
CREATE TABLE customers_snapshot (
	customer_id NVARCHAR(64),
	snapshot_ts DATETIME2,
	rate FLOAT,
	term_months INT,
	origination_date DATETIME2
);

CREATE TABLE [dbo].[Structured] (
    [id]           INT           IDENTITY (1, 1) NOT NULL,
	[account_id]      VARCHAR (50)  NOT NULL,
    [customer_id]      VARCHAR (50)  NOT NULL,
    [product_name]         NVARCHAR(100) NULL,
    [remaining_years]      FLOAT (53)    NOT NULL,
    [is_broker_originated] BIT           NOT NULL,
    [interest_rate]        FLOAT (53)    NOT NULL,
    [is_interest_only]     BIT           NOT NULL DEFAULT 0,
    [interest_only_end_date] DATE        NULL,
    CONSTRAINT [PK_Structured] PRIMARY KEY CLUSTERED ([id] ASC)
);

CREATE TABLE notes ( -- operational stream (for replay)
	note_id NVARCHAR(64) PRIMARY KEY,
	customer_id NVARCHAR(64),
	created_ts DATETIME2,
	note_text NVARCHAR(MAX)
);

CREATE TABLE notes_snapshot AS SELECT * FROM notes; -- convenience

CREATE TABLE closures (
	customer_id NVARCHAR(64),
	closure_ts DATETIME2
);

CREATE TABLE rules_library (
	version NVARCHAR(32),
	status NVARCHAR(16), -- ACTIVE, DRAFT
	activated_ts DATETIME2,
	ruleset_yaml NVARCHAR(MAX)
);

-- Table to store advertised rates for different product types
CREATE TABLE dbo.product_rates (
    product_name NVARCHAR(100) PRIMARY KEY,
    advertised_rate FLOAT NOT NULL,
    rate_type VARCHAR(20), -- e.g., 'FIXED', 'VARIABLE'
    last_updated DATETIME2 NOT NULL
);

CREATE TABLE lead_cards (
	lead_id BIGINT IDENTITY(1,1) PRIMARY KEY,
	customer_id NVARCHAR(64),
	note_id NVARCHAR(64),
	score FLOAT,
	rule_hits_json NVARCHAR(MAX),
	structured_snapshot_json NVARCHAR(MAX),
	explanation_text NVARCHAR(MAX),
	agent_version NVARCHAR(32),
	ruleset_version NVARCHAR(32),
	created_ts DATETIME2
);

CREATE TABLE discovery_cards (
	discovery_id BIGINT IDENTITY(1,1) PRIMARY KEY,
	phrase NVARCHAR(512),
	support INT,
	lift FLOAT,
	odds_ratio FLOAT,
	fdr FLOAT,
	examples_json NVARCHAR(MAX),
	status NVARCHAR(16), -- CANDIDATE, APPROVED, REJECTED
	created_ts DATETIME2
);
-- Deactivate any existing rulesets to ensure only one is ACTIVE
UPDATE dbo.rules_library
SET status = 'ARCHIVED'
WHERE status = 'ACTIVE';

-- Insert the sample ruleset as the new ACTIVE ruleset
INSERT INTO dbo.rules_library (version, status, activated_ts, ruleset_yaml)
VALUES (
    '0.1.0',
    'ACTIVE',
    GETUTCDATE(),
    'version: "0.1.0"
confidence_floor: 0.6 # AOAI hit must be >= this confidence
evidence_guard:
  min_chars: 4 # ignore 1-3 char "evidence"
weights:
  rate_diff: 0.30
  tenure: 0.10
text_rules:
  T1_REQUEST_STATEMENT:
    id: "T1"
    description: "Requesting a statement on their transaction account (e.g., to check household expenses)."
    weight: 0.20
    phrase_hints:
      - "statement for my transaction account"
      - "bank statement for expenses"
      - "download statement to check spending"
    negations:
      - "monthly e-statement signup"

  T2_REQUEST_PAYOUT_FIGURE:
    id: "T2"
    description: "Requesting a loan payout (payoff) figure."
    weight: 0.35
    phrase_hints:
      - "payout figure"
      - "payoff amount"
      - "how much to close the loan"
    negations: []

  T3_HOW_TO_CLOSE_LOAN:
    id: "T3"
    description: "Asking how to close their loan and who to speak with."
    weight: 0.45
    phrase_hints:
      - "how do I close my loan"
      - "who do I speak to to close"
      - "process to close mortgage"
    negations: []

  T4_BREAKCOSTS_AND_FEES:
    id: "T4"
    description: "Asking about break costs and fees involved with closing their loan."
    weight: 0.40
    phrase_hints:
      - "break cost"
      - "early termination fee"
      - "fee for closing early"
    negations: []

  T5_WHAT_IS_LVR:
    id: "T5"
    description: "Asking what their loan to value ratio (LVR) is."
    weight: 0.20
    phrase_hints:
      - "what is my lvr"
      - "loan to value ratio"
      - "current lvr"
    negations: []

  T6_CHANGE_IN_CIRCUMSTANCES:
    id: "T6"
    description: "Mentioning change in circumstances (divorce, moving, buying a new property)."
    weight: 0.30
    phrase_hints:
      - "change in circumstances"
      - "moving house"
      - "getting divorced"
      - "buying another property"
    negations: []

  T7_RETENTION_OR_SWITCH_UNSUCCESSFUL:
    id: "T7"
    description: "Recent HL retention/switch product attempt was unsuccessful."
    weight: 0.35
    phrase_hints:
      - "retention attempt unsuccessful"
      - "switch product unsuccessful"
      - "couldn''t switch to"
    negations:
      - "successful"

  T8_INTEREST_ONLY_UNSUCCESSFUL:
    id: "T8"
    description: "Recent interest-only product request unsuccessful."
    weight: 0.30
    phrase_hints:
      - "interest only request declined"
      - "interest-only unsuccessful"
    negations: []

  T9_PRODUCT_ENQUIRY_UNSUCCESSFUL:
    id: "T9"
    description: "Recent HL product enquiry unsuccessful."
    weight: 0.30
    phrase_hints:
      - "product enquiry unsuccessful"
      - "application unsuccessful"
      - "request declined"
    negations: []

decay:
  half_life_days: 30
exclusions:
  - "test account"
  - "dummy data"
'
);
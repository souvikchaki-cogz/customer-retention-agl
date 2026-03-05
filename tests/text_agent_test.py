import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from function_app import activity_call_text_agent as call_text_agent

# AGL energy churn test scenarios — run manually with live Azure OpenAI credentials.
# Uncomment the desired scenario before running.

event = {
    "customer_id": "CUST0001",
    "note_id": "note_agl_001",
    "ts": "2026-03-05T10:00:00Z",
    # Scenario A — Move-Out Intent (should trigger T2_MOVE_OUT_REQUEST)
    "text": "Hi, I'm moving house next month and need to know how to transfer or close my AGL account."
    # Scenario B — Bill Shock (should trigger T6_BILL_SHOCK_COMPLAINT)
    # "text": "My bill this quarter is double what it was last time. I'm shocked by the amount."
    # Scenario C — Comparing Retailers (should trigger T7_COMPARING_RETAILERS)
    # "text": "I've been shopping around and found a cheaper plan with another provider. Thinking of switching."
    # Scenario D — Switching Enquiry (should trigger T8_SWITCHING_PROCESS_ENQUIRY)
    # "text": "How do I switch to another energy retailer? How long does the transfer take?"
    # Scenario E — Hardship (should trigger T10_HARDSHIP_SWITCH_RISK, vulnerability guardrail)
    # "text": "I can't afford my bills anymore due to the cost of living. I'm really struggling."
    # Scenario F — Final Meter Read (should trigger T1_FINAL_METER_READ)
    # "text": "I need to organise a final meter read. We have a settlement date of the 15th."
}
result = call_text_agent(event)
print(result)
import sys
import os

# Add the project root to the system path to allow for absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from function_app import activity_call_text_agent as call_text_agent

event = {
    "customer_id": "CUST0003",
    "note_id": "note_456",
    "ts": "2024-10-01T12:00:00Z",
    "text": "Member reported unauthorized transactions, stating 'account was hacked' and 'disputing charges'. Second security incident in six months. Expressed dissatisfaction with fraud resolution process."
    }
result = call_text_agent(event)
print(result)

#"text": "Hi, can you tell me how to close my loan and who to speak with."
#"text": "Hi, I need a loan payout figure."
# "text": "Hi, can you send me a statement for my transaction account."
# Member requested large withdrawal to transfer funds to another bank. Mentioned 'liquidating savings' and 'closing account' for consolidation elsewhere. Amount exceeds $50,000.
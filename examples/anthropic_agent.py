"""
Example using Anthropic client with TARDIS.
Shows that TARDIS works with both OpenAI and Anthropic.
"""

import tardis
from anthropic import Anthropic

# 1. Start recorder
rec = tardis.Recorder().start()

# 2. Wrap Anthropic client - one line
client = tardis.wrap_anthropic(Anthropic())

# 3. Your normal agent loop
try:
    response = client.messages.create(
        model="claude-3-sonnet-20240229",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": "What causes EBUSY error in npm and how to fix on Windows?",
            }
        ],
    )
    print(response.content[0].text[:500])
except Exception as e:
    print("If you have no API key, this will error, but trace is still saved:", e)

# 4. Stop and save
trace = rec.stop()
print(f"\nSaved trace {trace.id} with {len(trace.steps)} steps")
print(f"Total cost: ${trace.total_cost_usd:.4f}")
print(f"Total tokens: {trace.total_tokens}")
print(f"Run: tardis replay {trace.id}")
print(f"Run: tardis autopsy {trace.id}")

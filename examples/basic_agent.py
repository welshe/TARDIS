"""
Minimal example - shows how TARDIS records without changing your agent logic.
"""
import tardis
from openai import OpenAI

# 1. Start recorder
rec = tardis.Recorder().start()

# 2. Wrap client - one line
client = tardis.wrap(OpenAI())

# 3. Your normal agent loop
try:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "What causes EBUSY error in npm and how to fix on Windows?"}],
    )
    print(response.choices[0].message.content[:500])
except Exception as e:
    print("If you have no API key, this will error, but trace is still saved:", e)

# 4. Stop and save
trace = rec.stop()
print(f"\nSaved trace {trace.id} with {len(trace.steps)} steps")
print(f"Run: tardis replay {trace.id}")
print(f"Run: tardis autopsy {trace.id}")

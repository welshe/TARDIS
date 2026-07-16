"""
Example showing tool tracing with TARDIS.
Demonstrates how TARDIS captures tool calls, results, and errors.
"""
import tardis
from tardis.capture.tool_wrapper import tool_traced
from openai import OpenAI
import time

# 1. Start recorder
rec = tardis.Recorder().start()

# 2. Define some tools with tracing
@tool_traced(rec, "file_reader")
def read_file(filename):
    """Simulated file reader that might fail"""
    if filename == "missing.txt":
        raise FileNotFoundError(f"File {filename} not found")
    return f"Content of {filename}: This is simulated file content"

@tool_traced(rec, "api_caller")
def call_api(endpoint):
    """Simulated API call that might fail"""
    if endpoint == "/error":
        raise Exception("API returned 500 Internal Server Error")
    return f"Response from {endpoint}: Success"

@tool_traced(rec, "data_processor")
def process_data(data):
    """Simulated data processing"""
    time.sleep(0.1)  # Simulate work
    return f"Processed: {data.upper()}"

# 3. Wrap LLM client
client = tardis.wrap(OpenAI())

# 4. Run agent with tool usage
try:
    # Successful tool call
    result1 = read_file("example.txt")
    print(f"Tool result 1: {result1}")
    
    # Successful API call
    result2 = call_api("/users")
    print(f"Tool result 2: {result2}")
    
    # Data processing
    result3 = process_data("hello world")
    print(f"Tool result 3: {result3}")
    
    # This will fail and be traced
    try:
        result4 = read_file("missing.txt")
    except Exception as e:
        print(f"Expected error caught: {e}")
    
    # This will also fail
    try:
        result5 = call_api("/error")
    except Exception as e:
        print(f"Expected error caught: {e}")
    
    # LLM call for context
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Summarize what happened in the tool calls"}],
    )
    print(f"LLM response: {response.choices[0].message.content[:200]}")

except Exception as e:
    print(f"Unexpected error: {e}")

# 5. Stop and analyze
trace = rec.stop()
print(f"\n=== TRACE SUMMARY ===")
print(f"Trace ID: {trace.id}")
print(f"Total steps: {len(trace.steps)}")
print(f"Success: {trace.success}")
print(f"Duration: {trace.get_duration_seconds():.2f}s")
print(f"Total cost: ${trace.total_cost_usd:.4f}")
print(f"Total tokens: {trace.total_tokens}")

# Show step breakdown
from collections import Counter
step_types = Counter(s.type.value for s in trace.steps)
print(f"\nStep breakdown:")
for step_type, count in step_types.most_common():
    print(f"  {step_type}: {count}")

print(f"\nRun: tardis autopsy {trace.id}")
print(f"Run: tardis replay {trace.id}")

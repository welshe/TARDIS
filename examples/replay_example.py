from tardis.replay.engine import ReplayEngine
from tardis.causal.graph import CausalGraph
from tardis.store.sqlite_store import Store

# list traces
store = Store()
traces = store.list_traces()
if not traces:
    print("No traces yet, run basic_agent.py first")
    exit()

tid = traces[0]["id"]
print(f"Replaying latest trace {tid}")

engine = ReplayEngine(tid)
engine.replay(from_idx=0)

# show causal graph
trace = store.get_trace(tid)
CausalGraph(trace).render()

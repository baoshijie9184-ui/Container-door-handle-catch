"""Native SDK fixture for the offline Docker rollback drill, never a production entry point."""
import json
import os
from pathlib import Path
import sys
import threading

if os.getenv('DOORHANDLE_ROLLBACK_DRILL') != 'offline-isolated':
    raise RuntimeError('Explicit isolated drill required')
from mem0 import Memory
import mem0.memory.main as sdk
import main
from lifecycle import GovernedVectorStore
from write_receipts import MemoryWriter

sdk.capture_event = lambda *a, **k: None
sdk.lemmatize_for_bm25 = lambda value: value
sdk.extract_entities_batch = lambda values: [[] for _ in values]
directory = Path(os.environ['MEM0_DATA_DIR'])
config = {
    'llm': {'provider': 'openai', 'config': {'api_key': 'offline-fixture', 'model': 'fixture', 'openai_base_url': 'http://127.0.0.1:1/v1'}},
    'embedder': {'provider': 'openai', 'config': {'api_key': 'offline-fixture', 'model': 'fixture', 'embedding_dims': 4, 'openai_base_url': 'http://127.0.0.1:1/v1'}},
    'vector_store': {'provider': 'chroma', 'config': {'path': str(directory / 'chroma'), 'collection_name': 'rollback_drill'}},
    'history_db_path': str(directory / 'history.sqlite3'),
}
memory = Memory.from_config(config)
memory.embedding_model.embed = lambda *a, **k: [.1, .2, .3, .4]
memory.embedding_model.embed_batch = lambda values, *a, **k: [[.1, .2, .3, .4] for _ in values]
main.memory_instance = memory
writer = MemoryWriter(directory / 'bridge_receipts', lambda: memory, threading.Lock())
main.memory_writer = writer
main.memory_write_lock = writer.write_lock
memory.vector_store = GovernedVectorStore(memory.vector_store, writer.lifecycle)
fixture = directory / 'fixture.json'
user, app = 'doorhandlecatch:user:990001', 'doorhandlecatch'
if not fixture.exists():
    ids = {}
    for name in ['active', 'excluded', 'expired']:
        ids[name] = memory.add('Offline rollback fixture ' + name, user_id=user, agent_id=app, run_id='original', infer=False)['results'][0]['id']
    fixture.write_text(json.dumps(ids), encoding='utf8')

# Real MemoryWriter receipt and native Chroma write; this deterministic fixture
# bypasses paid extraction only. Persist invocation evidence to detect replay.
native_add = memory.add
def add(content, **kwargs):
    with (directory / 'native-add-calls.jsonl').open('a') as stream:
        stream.write(json.dumps({'run_id': kwargs.get('run_id')}) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    kwargs['infer'] = False
    return native_add(content, **kwargs)
memory.add = add
if '--lie-about-health' in sys.argv:
    main.BRIDGE_PROTOCOL = 0
try:
    import uvicorn
    uvicorn.run(main.app, host='127.0.0.1', port=8081, lifespan='off', log_level='warning')
finally:
    writer.close()

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


import pytest


@pytest.fixture(autouse=True)
def isolate_memory_receipts(request, monkeypatch, tmp_path):
    if not request.node.path.name.startswith("test_memory_"):
        yield
        return
    import threading
    from memory_service import main
    from memory_service.write_receipts import MemoryWriter
    lock = threading.Lock()
    writer = MemoryWriter(tmp_path / "receipt-store", lambda: main.memory_instance, lock)
    monkeypatch.setattr(main, "memory_write_lock", lock)
    monkeypatch.setattr(main, "memory_writer", writer)
    try:
        yield writer
    finally:
        writer.close()

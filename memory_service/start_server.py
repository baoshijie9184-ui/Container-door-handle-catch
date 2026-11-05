from pathlib import Path
import sys

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from ecs_execution import require_ecs_execution
    require_ecs_execution()
    import uvicorn
    from main import app
    print("Starting ECS memory service on port 8081...")
    uvicorn.run(app, host="127.0.0.1", port=8081)

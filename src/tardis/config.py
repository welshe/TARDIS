import pathlib
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python 3.10 compat
from pydantic import BaseModel

class Config(BaseModel):
    db_path: str = ".tardis/tardis.db"
    blob_path: str = ".tardis/blobs"
    capture_screen: bool = False
    fps: int = 2

def load() -> Config:
    path = pathlib.Path("tardis.toml")
    if not path.exists():
        return Config()
    data = tomllib.loads(path.read_text())
    return Config(**data.get("tardis", {}))

import os
import pathlib

LIB_DIR = pathlib.Path(__file__).parent

if "DISKLAVIER_CACHE_DIR" in os.environ:
    CACHE_DIR = pathlib.Path(os.environ["DISKLAVIER_CACHE_DIR"])
else:
    CACHE_DIR = pathlib.Path.home() / ".cache" / "disklavier"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

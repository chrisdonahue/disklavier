import os
import pathlib
from typing import Iterator

LIB_DIR = pathlib.Path(__file__).parent
REPO_DIR = LIB_DIR.parent

if "DISKLAVIER_CACHE_DIR" in os.environ:
    CACHE_DIR = pathlib.Path(os.environ["DISKLAVIER_CACHE_DIR"])
else:
    CACHE_DIR = pathlib.Path.home() / ".cache" / "disklavier"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

RECORDINGS_DIR = CACHE_DIR / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def iter_midi_recordings() -> Iterator[pathlib.Path]:
    for file in sorted(RECORDINGS_DIR.glob("*.mid")):
        yield file

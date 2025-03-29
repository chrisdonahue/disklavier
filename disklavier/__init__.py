import pathlib

LIB_DIR = pathlib.Path(__file__).parent
RECORDINGS_DIR = pathlib.Path("/mnt/hoard/disklavier/recordings").resolve()
DISKLAVIER_MIDI_IN_NAME = "USB Midi:USB Midi MIDI 1 24:0"
DISKLAVIER_MIDI_OUT_NAME = "USB Midi:USB Midi MIDI 1 24:0"


# NOTE: This changes the test discovery pattern from "test*.py" (default) to "*test.py".
def load_tests(loader, standard_tests, pattern):
    package_tests = loader.discover(start_dir=LIB_DIR, pattern="*test.py")
    standard_tests.addTests(package_tests)
    return standard_tests

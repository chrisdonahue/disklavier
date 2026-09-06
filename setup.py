from setuptools import setup, find_packages

setup(
    name="disklavier",
    packages=find_packages(),
    install_requires=[
        "python-rtmidi",
        "mido",
    ],
    entry_points={
        "console_scripts": [
            "disklavier=disklavier.main:main",
            "disklavier-monitor=disklavier.disklavier:main",
            "disklavier-record=disklavier.modes.surveil.record:main",
            "disklavier-web=disklavier.web.serve:main",
            "disklavier-activity=disklavier.web.activity:main",
        ],
    },
)

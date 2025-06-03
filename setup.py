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
            "disklavier-record=disklavier.record:main",
            "disklavier-activity=disklavier.activity:main",
            "disklavier=disklavier.disklavier:main",
        ],
    },
)

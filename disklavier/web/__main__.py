"""
Entry point for running the Disklavier web server as a module.
Usage: python -m disklavier.web
"""

from .serve import main

if __name__ == "__main__":
    main()

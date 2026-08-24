"""Entry point for ``python -m einvoice``."""
import sys

from .cli import main

sys.exit(main())

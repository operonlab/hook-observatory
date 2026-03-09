"""Browser Bridge CLI package.

Entry point: bridge (registered in pyproject.toml)

    from browser_bridge.cli import main
    main()
"""

from .main import main

__all__ = ["main"]

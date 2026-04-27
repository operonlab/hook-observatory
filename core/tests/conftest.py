"""Shared test fixtures for core module tests.

pythonpath is configured in pyproject.toml ([tool.pytest.ini_options]).
Inserting core/ here used to expose `memvault` via two roots
(src/modules/memvault and src.modules.memvault), causing SQLAlchemy
`Table 'memvault.blocks' is already defined` collisions.
"""

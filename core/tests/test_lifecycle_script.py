"""Verification tests for lifecycle script and migration chain.

Part 1: archive_cold_data.py syntax/import checks
Part 2: Alembic migration chain j -> k -> l integrity
"""

import ast
import subprocess
from pathlib import Path

WORKSHOP_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = WORKSHOP_ROOT / "scripts"
MIGRATIONS_DIR = WORKSHOP_ROOT / "core" / "migrations" / "versions"
PYTHON = str(WORKSHOP_ROOT / ".venv" / "bin" / "python")


# ---------------------------------------------------------------------------
# Part 1: archive_cold_data.py syntax / import verification
# ---------------------------------------------------------------------------


class TestArchiveColdDataScript:
    """Verify the lifecycle script is syntactically valid and has the correct CLI."""

    SCRIPT_PATH = SCRIPTS_DIR / "archive_cold_data.py"

    def test_script_exists(self):
        """The script file must exist."""
        assert self.SCRIPT_PATH.exists(), f"archive_cold_data.py not found at {self.SCRIPT_PATH}"

    def test_syntax_valid(self):
        """The script can be parsed without syntax errors (ast.parse)."""
        source = self.SCRIPT_PATH.read_text(encoding="utf-8")
        # ast.parse raises SyntaxError on failure
        tree = ast.parse(source, filename=str(self.SCRIPT_PATH))
        assert isinstance(tree, ast.Module)

    def test_help_shows_expected_args(self):
        """Running --help succeeds and shows --execute, --phase, --module, --db-url."""
        result = subprocess.run(  # noqa: S603
            [PYTHON, str(self.SCRIPT_PATH), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"--help exited with code {result.returncode}: {result.stderr}"
        )
        help_text = result.stdout

        expected_args = ["--execute", "--phase", "--module", "--db-url"]
        for arg in expected_args:
            assert arg in help_text, f"Expected CLI argument '{arg}' not found in --help output"

    def test_no_age_days_arg(self):
        """--age-days was removed (replaced by tier-config thresholds); must not appear."""
        result = subprocess.run(  # noqa: S603
            [PYTHON, str(self.SCRIPT_PATH), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        help_text = result.stdout + result.stderr
        assert "--age-days" not in help_text, (
            "--age-days should have been removed in favour of tier-config thresholds"
        )

    def test_phase_choices_include_all(self):
        """--phase should accept '1', '2', '3', and 'all'."""
        result = subprocess.run(  # noqa: S603
            [PYTHON, str(self.SCRIPT_PATH), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        help_text = result.stdout
        # argparse renders choices like {1,2,3,all}
        assert "all" in help_text, "--phase should include 'all' as a valid choice"
        for phase_num in ["1", "2", "3"]:
            assert phase_num in help_text, f"--phase should include '{phase_num}' as a valid choice"


# ---------------------------------------------------------------------------
# Part 2: Migration chain verification (j -> k -> l)
# ---------------------------------------------------------------------------


def _extract_revision_fields(filepath: Path) -> dict[str, str | None]:
    """Parse an Alembic migration file and extract revision / down_revision.

    Handles both plain assignment (``revision = "abc"``) and annotated
    assignment (``revision: str = "abc"`` or ``revision: str | None = "abc"``).
    """
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source)

    target_names = {"revision", "down_revision"}
    fields: dict[str, str | None] = {}

    for node in ast.walk(tree):
        # Plain assignment: revision = "abc"
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in target_names:
                    if isinstance(node.value, ast.Constant):
                        fields[target.id] = node.value.value

        # Annotated assignment: revision: str = "abc"
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id in target_names
                and node.value is not None
                and isinstance(node.value, ast.Constant)
            ):
                fields[node.target.id] = node.value.value

    return fields


class TestMigrationChain:
    """Verify the j -> k -> l migration chain is intact."""

    MIGRATION_J = MIGRATIONS_DIR / "j1b2c3d4e5f6_adjust_hnsw_hot_windows.py"
    MIGRATION_K = MIGRATIONS_DIR / "k2c3d4e5f6g7_create_frozen_tables.py"
    MIGRATION_L = MIGRATIONS_DIR / "l3d4e5f6g7h8_create_remaining_frozen_tables.py"

    def test_migration_files_exist(self):
        """All three migration files must exist."""
        for path in [self.MIGRATION_J, self.MIGRATION_K, self.MIGRATION_L]:
            assert path.exists(), f"Migration file not found: {path.name}"

    def test_migration_j_revision(self):
        """Migration j has correct revision and down_revision."""
        fields = _extract_revision_fields(self.MIGRATION_J)
        assert fields["revision"] == "j1b2c3d4e5f6"
        assert fields["down_revision"] == "h9a0b1c2d3e4"

    def test_migration_k_revision(self):
        """Migration k has correct revision and points back to j."""
        fields = _extract_revision_fields(self.MIGRATION_K)
        assert fields["revision"] == "k2c3d4e5f6g7"
        assert fields["down_revision"] == "j1b2c3d4e5f6"

    def test_migration_l_revision(self):
        """Migration l has correct revision and points back to k."""
        fields = _extract_revision_fields(self.MIGRATION_L)
        assert fields["revision"] == "l3d4e5f6g7h8"
        assert fields["down_revision"] == "k2c3d4e5f6g7"

    def test_chain_integrity(self):
        """The full chain j->k->l is connected: down_revision matches prior."""
        fields_j = _extract_revision_fields(self.MIGRATION_J)
        fields_k = _extract_revision_fields(self.MIGRATION_K)
        fields_l = _extract_revision_fields(self.MIGRATION_L)

        assert fields_k["down_revision"] == fields_j["revision"], (
            f"k.down_revision ({fields_k['down_revision']}) != j.revision ({fields_j['revision']})"
        )
        assert fields_l["down_revision"] == fields_k["revision"], (
            f"l.down_revision ({fields_l['down_revision']}) != k.revision ({fields_k['revision']})"
        )

    def test_migration_j_has_upgrade_downgrade(self):
        """Migration j defines both upgrade() and downgrade()."""
        source = self.MIGRATION_J.read_text()
        assert "def upgrade()" in source
        assert "def downgrade()" in source

    def test_migration_k_has_upgrade_downgrade(self):
        """Migration k defines both upgrade() and downgrade()."""
        source = self.MIGRATION_K.read_text()
        assert "def upgrade()" in source
        assert "def downgrade()" in source

    def test_migration_l_has_upgrade_downgrade(self):
        """Migration l defines both upgrade() and downgrade()."""
        source = self.MIGRATION_L.read_text()
        assert "def upgrade()" in source
        assert "def downgrade()" in source

    def test_migration_k_creates_frozen_tables(self):
        """Migration k should create blocks_frozen, reports_frozen, briefings_frozen."""
        source = self.MIGRATION_K.read_text()
        for table in ["blocks_frozen", "reports_frozen", "briefings_frozen"]:
            assert table in source, f"Migration k should create '{table}' but it was not found"

    def test_migration_l_creates_remaining_frozen_tables(self):
        """Migration l should create transactions_frozen, tasks_frozen, sparks_frozen."""
        source = self.MIGRATION_L.read_text()
        for table in ["transactions_frozen", "tasks_frozen", "sparks_frozen"]:
            assert table in source, f"Migration l should create '{table}' but it was not found"

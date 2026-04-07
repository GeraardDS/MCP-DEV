"""Tests for InputValidator — injection prevention and path safety.

Covers:
- validate_table_name: normal, injection attempts, edge cases
- validate_dax_query: dangerous patterns, null bytes, length
- validate_export_path: path traversal, extensions, base_dir confinement
"""

import pytest
from core.validation.input_validator import InputValidator


# ---------------------------------------------------------------------------
# validate_table_name
# ---------------------------------------------------------------------------

class TestValidateTableName:

    def test_normal_name_valid(self):
        valid, err = InputValidator.validate_table_name("Sales")
        assert valid is True
        assert err is None

    def test_name_with_spaces_valid(self):
        valid, err = InputValidator.validate_table_name("Fact Sales Data")
        assert valid is True

    def test_name_with_single_quotes_valid(self):
        """Power BI tables can have single-quoted names like 'f Valtrans'."""
        valid, err = InputValidator.validate_table_name("'f Valtrans'")
        assert valid is True

    def test_empty_string_invalid(self):
        valid, err = InputValidator.validate_table_name("")
        assert valid is False
        assert "non-empty" in err.lower()

    def test_none_invalid(self):
        valid, err = InputValidator.validate_table_name(None)
        assert valid is False

    def test_null_byte_rejected(self):
        valid, err = InputValidator.validate_table_name("Sales\x00Injected")
        assert valid is False
        assert "null" in err.lower()

    def test_control_characters_rejected(self):
        valid, err = InputValidator.validate_table_name("Sales\x01Data")
        assert valid is False
        assert "control" in err.lower()

    def test_very_long_name_rejected(self):
        long_name = "A" * 200
        valid, err = InputValidator.validate_table_name(long_name)
        assert valid is False
        assert "128" in err or "exceeds" in err.lower()

    def test_exactly_max_length_valid(self):
        name = "A" * 128
        valid, err = InputValidator.validate_table_name(name)
        assert valid is True

    def test_injection_pattern_drop_still_valid_but_logged(self):
        """DROP in a name is suspicious but allowed (warning only)."""
        valid, err = InputValidator.validate_table_name("DROP TABLE test")
        assert valid is True  # Allowed with warning

    def test_whitespace_stripped(self):
        valid, err = InputValidator.validate_table_name("  Sales  ")
        assert valid is True


# ---------------------------------------------------------------------------
# validate_dax_query
# ---------------------------------------------------------------------------

class TestValidateDaxQuery:

    def test_normal_query_valid(self):
        query = "EVALUATE SUMMARIZECOLUMNS('Table'[Column], \"Total\", SUM('Table'[Amount]))"
        valid, err = InputValidator.validate_dax_query(query)
        assert valid is True

    def test_empty_query_invalid(self):
        valid, err = InputValidator.validate_dax_query("")
        assert valid is False

    def test_none_query_invalid(self):
        valid, err = InputValidator.validate_dax_query(None)
        assert valid is False

    def test_null_byte_rejected(self):
        valid, err = InputValidator.validate_dax_query("EVALUATE\x00 INJECTED")
        assert valid is False

    def test_drop_table_rejected(self):
        valid, err = InputValidator.validate_dax_query("EVALUATE x; DROP TABLE Sales")
        assert valid is False
        assert "dangerous" in err.lower()

    def test_xp_cmdshell_rejected(self):
        valid, err = InputValidator.validate_dax_query("EVALUATE xp_cmdshell('whoami')")
        assert valid is False

    def test_openrowset_rejected(self):
        valid, err = InputValidator.validate_dax_query("EVALUATE OPENROWSET('provider', 'conn', 'q')")
        assert valid is False

    def test_very_long_query_rejected(self):
        query = "A" * 600_000
        valid, err = InputValidator.validate_dax_query(query)
        assert valid is False
        assert "exceeds" in err.lower()

    def test_normal_calculate_valid(self):
        query = "EVALUATE {CALCULATE([Sales], 'Date'[Year] = 2024)}"
        valid, err = InputValidator.validate_dax_query(query)
        assert valid is True


# ---------------------------------------------------------------------------
# validate_export_path
# ---------------------------------------------------------------------------

class TestValidateExportPath:

    def test_normal_path_valid(self):
        valid, err = InputValidator.validate_export_path("C:/exports/report.json")
        assert valid is True

    def test_empty_path_invalid(self):
        valid, err = InputValidator.validate_export_path("")
        assert valid is False

    def test_none_path_invalid(self):
        valid, err = InputValidator.validate_export_path(None)
        assert valid is False

    def test_null_byte_rejected(self):
        valid, err = InputValidator.validate_export_path("C:/exports/file\x00.json")
        assert valid is False

    def test_path_traversal_rejected(self):
        valid, err = InputValidator.validate_export_path("C:/exports/../../etc/passwd")
        assert valid is False
        assert "traversal" in err.lower()

    def test_disallowed_extension_rejected(self):
        valid, err = InputValidator.validate_export_path("C:/exports/evil.exe")
        assert valid is False
        assert "extension" in err.lower()

    def test_allowed_extensions(self):
        for ext in [".json", ".csv", ".txt", ".xlsx", ".xml", ".graphml", ".yaml", ".yml"]:
            valid, err = InputValidator.validate_export_path(f"C:/exports/file{ext}")
            assert valid is True, f"Extension {ext} should be allowed"

    def test_very_long_path_rejected(self):
        long_path = "C:/" + "a" * 300 + ".json"
        valid, err = InputValidator.validate_export_path(long_path)
        assert valid is False
        assert "260" in err or "exceeds" in err.lower()

    def test_base_dir_confinement(self, tmp_path):
        """Path outside base_dir should be rejected."""
        base = str(tmp_path / "allowed")
        valid, err = InputValidator.validate_export_path(
            "C:/other_dir/file.json", base_dir=base
        )
        assert valid is False
        assert "within" in err.lower()


# ---------------------------------------------------------------------------
# validate_integer_param
# ---------------------------------------------------------------------------

class TestValidateIntegerParam:

    def test_normal_int_valid(self):
        valid, err, val = InputValidator.validate_integer_param(42, min_val=1, max_val=100)
        assert valid is True
        assert val == 42

    def test_string_int_coerced(self):
        valid, err, val = InputValidator.validate_integer_param("10")
        assert valid is True
        assert val == 10

    def test_non_numeric_rejected(self):
        valid, err, val = InputValidator.validate_integer_param("abc")
        assert valid is False
        assert val is None

    def test_below_min_rejected(self):
        valid, err, val = InputValidator.validate_integer_param(0, min_val=1)
        assert valid is False

    def test_above_max_rejected(self):
        valid, err, val = InputValidator.validate_integer_param(200, max_val=100)
        assert valid is False

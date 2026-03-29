import sys
import os
import pytest
from typing import List, Dict, Any

# Mock the imports or add to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.modules.sql.utils.schema_utils import generate_mermaid_erd, _safe_name

def test_safe_name_sanitization():
    """Test that _safe_name handles illegal Mermaid characters."""
    assert _safe_name("Table Name") == "Table_Name"
    assert _safe_name("table-name") == "table_name"
    assert _safe_name("123table") == "_123table" # Should prefix with underscore
    assert _safe_name("Table.Name!") == "Table_Name"
    assert " " not in _safe_name("   padded   ")

def test_generate_mermaid_erd_syntax_no_quotes():
    """Regression test: Ensure NO double quotes are in the output."""
    tables = [
        {
            "table": "Album",
            "columns": [
                {"name": "AlbumId", "primary_key": True, "dtype": "INTEGER"},
                {"name": "Title", "primary_key": False, "dtype": "NVARCHAR"}
            ]
        }
    ]
    fks = []
    
    erd = generate_mermaid_erd(tables, fks)
    
    # Check for basic Mermaid structure
    assert "erDiagram" in erd
    assert "Album {" in erd
    assert "AlbumId PK" in erd
    
    # CRITICAL: No quotes
    assert '"' not in erd, "Mermaid ERD must NOT contains double quotes around entity names"

def test_complex_fks_and_naming():
    """Ensure complex names with spaces/dashes are handled correctly in relationships."""
    tables = [
        {
            "table": "Order Items", # Spaced
            "columns": [
                {"name": "Order ID", "primary_key": True, "dtype": "INT"},
                {"name": "Product-ID", "primary_key": False, "dtype": "INT"}
            ]
        },
        {
            "table": "Products",
            "columns": [
                {"name": "Product-ID", "primary_key": True, "dtype": "INT"}
            ]
        }
    ]
    fks = [
        {
            "from_table": "Order Items",
            "from_col": "Product-ID",
            "to_table": "Products",
            "to_col": "Product-ID"
        }
    ]
    
    erd = generate_mermaid_erd(tables, fks)
    
    # Check sanitized names
    assert "Order_Items {" in erd
    assert "Products {" in erd
    assert "Order_Items ||--o{ Products" in erd  # Use ||--o{ as the default for inferred
    assert '"' not in erd

def test_multiple_markers_comma():
    """Ensure PK and FK in the same column use a comma separator."""
    tables = [
        {
            "table": "TableA",
            "columns": [
                {"name": "Col1", "primary_key": True, "dtype": "INT"}
            ]
        }
    ]
    # Simulate Col1 being both PK and FK
    fks = [{"from_table": "TableA", "from_col": "Col1", "to_table": "TableB", "to_col": "ID"}]
    
    erd = generate_mermaid_erd(tables, fks)
    assert "Col1 PK,FK" in erd, f"Markers should be comma-separated, found: {erd}"

if __name__ == "__main__":
    # If run as a script
    try:
        test_safe_name_sanitization()
        test_generate_mermaid_erd_syntax_no_quotes()
        test_complex_fks_and_naming()
        test_multiple_markers_comma()
        print("✅ All Mermaid regression tests PASSED!")
    except AssertionError as e:
        print(f"❌ Regression test FAILED: {e}")
        sys.exit(1)

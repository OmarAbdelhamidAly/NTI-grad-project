import os
import re
import pytest

def get_python_files(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                yield os.path.join(root, file)

def test_no_cross_module_leakage():
    """
    Ensure app/modules/csv/ does NOT import from app/modules/sql/ 
    and vice versa.
    """
    base_path = "app/modules"
    
    # Check CSV -> SQL
    csv_files = list(get_python_files(os.path.join(base_path, "csv")))
    for file_path in csv_files:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Look for 'import app.modules.sql' or 'from app.modules.sql'
            assert "app.modules.sql" not in content, f"LEAKAGE found in {file_path}: CSV team is importing from SQL!"

    # Check SQL -> CSV
    sql_files = list(get_python_files(os.path.join(base_path, "sql")))
    for file_path in sql_files:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "app.modules.csv" not in content, f"LEAKAGE found in {file_path}: SQL team is importing from CSV!"

def test_domain_isolation():
    """
    Ensure app/domain/ does NOT import from modules or infrastructure.
    The Domain is the INNER circle and should be independent.
    """
    domain_path = "app/domain"
    domain_files = list(get_python_files(domain_path))
    
    forbidden = ["app.modules", "app.infrastructure", "app.use_cases"]
    
    for file_path in domain_files:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            for pkg in forbidden:
                assert pkg not in content, f"CLEAN ARCHITECTURE VIOLATION: Domain {file_path} imports from {pkg}!"

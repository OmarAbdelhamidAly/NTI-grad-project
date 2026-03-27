"""SQL Schema Utilities.

Shared logic for generating ERDs and inferring relationships from SQL metadata.
"""

from typing import Any, Dict, List, Set

def generate_mermaid_erd(tables: List[Dict[str, Any]], foreign_keys: List[Dict[str, Any]]) -> str:
    """Generate a Mermaid ERD string from tables and foreign keys."""
    erd_lines = ["erDiagram"]
    
    # Shorten types for Mermaid readability
    def _get_mermaid_type(sql_type: str) -> str:
        sql_type = str(sql_type).lower()
        if any(t in sql_type for t in ("int", "serial", "numeric", "decimal", "float", "double")):
            return "number"
        if any(t in sql_type for t in ("date", "time")):
            return "datetime"
        if "bool" in sql_type:
            return "boolean"
        return "string"

    for table in tables:
        t_name = table["table"]
        erd_lines.append(f'    "{t_name}" {{')
        for col in table.get("columns", []):
            col_name = col["name"]
            m_type = _get_mermaid_type(col["dtype"])
            pk_marker = "PK" if col.get("primary_key") else ""
            
            # Check if this column is a foreign key
            is_fk = any(
                fk["from_table"] == t_name and fk["from_col"] == col_name 
                for fk in foreign_keys
            )
            fk_marker = "FK" if is_fk else ""
            
            # Formatting line with markers
            line = f'        {m_type} {col_name}'
            if pk_marker or fk_marker:
                line += f' {pk_marker}{" " if pk_marker and fk_marker else ""}{fk_marker}'
            erd_lines.append(line)
        erd_lines.append('    }')
    
    # Relationships
    fk_set = set()
    for fk in foreign_keys:
        # Mermaid relationship string
        # using ||--o{ for one-to-many as a standard heuristic
        fk_str = f'    "{fk["from_table"]}" ||--o{{ "{fk["to_table"]}" : "{fk["from_col"]}->{fk["to_col"]}"'
        if fk_str not in fk_set:
            erd_lines.append(fk_str)
            fk_set.add(fk_str)
            
    return "\n".join(erd_lines)

def infer_foreign_keys(tables: List[Dict[str, Any]], existing_fks: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Heuristic logic to infer relationships in databases without formal FK constraints."""
    foreign_keys = list(existing_fks) if existing_fks else []
    
    if len(tables) <= 1:
        return foreign_keys

    # Map for quick lookup
    existing_map = set((fk["from_table"].lower(), fk["from_col"].lower(), fk["to_table"].lower()) for fk in foreign_keys)

    for t1 in tables:
        t1_name = t1["table"].lower()
        for c1 in t1["columns"]:
            col_name = c1["name"].lower()
            
            # Heuristic 1: ID-based linking (customer_id -> customers.id)
            target_base = None
            if col_name.endswith("_id") and col_name != "id":
                target_base = col_name[:-3]
            elif col_name.endswith("_zip_code_prefix"):
                target_base = col_name.replace("_zip_code_prefix", "")
            elif col_name.endswith("id") and len(col_name) > 2:
                target_base = col_name[:-2].rstrip("_")
            
            if target_base:
                for t2 in tables:
                    t2_name = t2["table"].lower()
                    if t1_name == t2_name: continue
                    
                    clean_t2 = t2_name.replace("olist_", "").replace("_dataset", "").replace("tbl_", "")
                    
                    is_match = (
                        t2_name == target_base or 
                        t2_name == target_base + "s" or 
                        t2_name == target_base + "es" or
                        clean_t2 == target_base or
                        clean_t2 == target_base + "s" or
                        (target_base.endswith("y") and t2_name == target_base[:-1] + "ies") or
                        f"_{target_base}" in t2_name or
                        (target_base in t2_name and "_dataset" in t2_name)
                    )
                    
                    if is_match:
                        # Find potential PK in target table
                        t2_cols = [c["name"] for c in t2["columns"]]
                        t2_cols_lower = [c.lower() for c in t2_cols]
                        
                        pk_col = None
                        if col_name in t2_cols_lower:
                            pk_col = t2_cols[t2_cols_lower.index(col_name)]
                        elif "id" in t2_cols_lower:
                            pk_col = t2_cols[t2_cols_lower.index("id")]
                        
                        if pk_col:
                            if (t1["table"].lower(), c1["name"].lower(), t2["table"].lower()) not in existing_map:
                                foreign_keys.append({
                                    "from_table": t1["table"],
                                    "from_col": c1["name"],
                                    "to_table": t2["table"],
                                    "to_col": pk_col
                                })
                                existing_map.add((t1["table"].lower(), c1["name"].lower(), t2["table"].lower()))
                                break

            # Heuristic 2: Unusual Shared Column Names (length > 8)
            if len(col_name) > 8 and not col_name.endswith("id"):
                if col_name in ("created_at", "updated_at", "status", "description", "timestamp", "last_updated"):
                    continue
                    
                for t2 in tables:
                    t2_name = t2["table"].lower()
                    if t1_name == t2_name: continue
                    
                    t2_cols = [c["name"] for c in t2["columns"]]
                    t2_cols_lower = [c.lower() for c in t2_cols]
                    
                    if col_name in t2_cols_lower:
                        if (t1["table"].lower(), c1["name"].lower(), t2["table"].lower()) not in existing_map:
                            foreign_keys.append({
                                "from_table": t1["table"],
                                "from_col": c1["name"],
                                "to_table": t2["table"],
                                "to_col": t2_cols[t2_cols_lower.index(col_name)]
                            })
                            existing_map.add((t1["table"].lower(), c1["name"].lower(), t2["table"].lower()))

    return foreign_keys

def _profile_sqlite(file_path: str) -> Dict[str, Any]:
    """Build a schema profile from an uploaded SQLite file."""
    from sqlalchemy import create_engine, inspect, text
    import os

    conn_str = f"sqlite:///{file_path}"
    engine = create_engine(conn_str)
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        result_tables = []
        all_fks = []

        for table_name in tables:
            columns = inspector.get_columns(table_name)
            pk_cols = inspector.get_pk_constraint(table_name).get("constrained_columns", [])
            
            # Extract literal FKs
            fks = inspector.get_foreign_keys(table_name)
            for fk in fks:
                for idx, from_col in enumerate(fk["constrained_columns"]):
                    all_fks.append({
                        "from_table": table_name,
                        "from_col": from_col,
                        "to_table": fk["referred_table"],
                        "to_col": fk["referred_columns"][idx]
                    })

            col_infos = []
            for col in columns:
                col_info = {
                    "name": col["name"],
                    "dtype": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "primary_key": col["name"] in pk_cols,
                }
                # Sample values logic
                try:
                    with engine.connect() as conn:
                        rows = conn.execute(
                            text(f'SELECT "{col["name"]}" FROM "{table_name}" WHERE "{col["name"]}" IS NOT NULL LIMIT 3')
                        ).fetchall()
                    col_info["sample_values"] = [str(r[0]) for r in rows]
                except Exception:
                    col_info["sample_values"] = []
                col_infos.append(col_info)

            # Row count
            try:
                with engine.connect() as conn:
                    row_count = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
            except Exception:
                row_count = None

            result_tables.append({
                "table": table_name,
                "columns": col_infos,
                "column_count": len(col_infos),
                "row_count": row_count,
            })

        # Infer additional relationships
        final_fks = infer_foreign_keys(result_tables, all_fks)
        mermaid_erd = generate_mermaid_erd(result_tables, final_fks)

        return {
            "source_type": "sqlite",
            "dialect": "sqlite",
            "table_count": len(tables),
            "row_count": sum(t["row_count"] for t in result_tables if t["row_count"]),
            "column_count": sum(t["column_count"] for t in result_tables),
            "tables": result_tables,
            "foreign_keys": final_fks,
            "mermaid_erd": mermaid_erd,
            "all_column_names": [
                f"{t['table']}.{c['name']}"
                for t in result_tables
                for c in t["columns"]
            ],
            "columns": [
                {
                    "name": f"{t['table']}.{c['name']}",
                    "dtype": c["dtype"],
                    "null_count": 0,
                    "unique_count": 0,
                    "sample_values": c.get("sample_values", [])
                }
                for t in result_tables
                for c in t["columns"]
            ]
        }
    finally:
        engine.dispose()

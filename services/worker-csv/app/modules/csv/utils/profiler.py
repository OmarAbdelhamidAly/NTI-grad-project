import pandas as pd

def _profile_dataframe(df: pd.DataFrame) -> dict:
    """Build a lightweight schema profile from a DataFrame."""
    return {
        "columns": [
            {
                "name": col,
                "dtype": str(df[col].dtype),
                "null_count": int(df[col].isnull().sum()),
                "unique_count": int(df[col].nunique()),
                "sample_values": df[col].dropna().head(5).tolist(),
            }
            for col in df.columns
        ],
        "row_count": len(df),
        "column_count": len(df.columns),
    }

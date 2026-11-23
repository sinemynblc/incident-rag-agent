import pandas as pd

try:
    df = pd.read_csv("data/rca_dataset.csv")
    df.to_parquet("data/rca_dataset.parquet", index=False, engine="pyarrow")
    print(f"{len(df)} kayıt Parquet'e çevrildi.")
except FileNotFoundError:
    print("CSV dosyası bulunamadı: 'data/rca_dataset.csv'")
except Exception as e:
    print(f"Dönüşüm sırasında hata oluştu: {e}")

'''convert csv to parquet with pyarrow engine.
parquet is more efficient for large datasets and allows for batch processing.'''
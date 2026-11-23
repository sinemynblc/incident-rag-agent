import os
import pandas as pd
import pyarrow.parquet as pq
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from sentence_transformers import SentenceTransformer

client = QdrantClient(url=os.environ.get("QDRANT_URL", "http://localhost:6333"))
model = SentenceTransformer("all-MiniLM-L6-v2")


def parquet_batch_generator(parquet_path, batch_size=64):
    try:
        parquet_file = pq.ParquetFile(parquet_path)
        for batch in parquet_file.iter_batches(batch_size=batch_size):
            yield batch.to_pandas()
    except FileNotFoundError:
        print(f"Parquet dosyası bulunamadı: {parquet_path}")
    except Exception as e:
        print(f"Parquet dosyası okunurken hata oluştu: {e}")


total_upserted = 0

for batch_df in parquet_batch_generator("data/rca_dataset.parquet", batch_size=64):
    try:
        # Bu grup için embed edilecek metinleri oluştur
        texts = []
        for _, row in batch_df.iterrows():
            column_values = []
            for col in batch_df.columns:
                column_values.append(f"{col}: {row[col]}")
            row_text = " ".join(column_values)
            texts.append(row_text)

        # Metinleri embed et
        vectors = model.encode(texts, batch_size=64)

        # PointStruct'ları oluştur
        points = []
        for i, (_, row) in enumerate(batch_df.iterrows()):
            points.append(
                PointStruct(
                    id=total_upserted + i,
                    vector=vectors[i].tolist(),
                    payload=row.to_dict(),
                )
            )

        # Bu grubu Qdrant'a yaz
        client.upsert(collection_name="data_collection", points=points)
        total_upserted += len(points)
        print(f"Bu grupta {len(points)} kayıt upsert edildi. Toplam: {total_upserted}")

    except Exception as e:
        print(f"Bu grup işlenirken hata oluştu (toplam upsert edilen: {total_upserted}): {e}")
        continue  # bu grubu atla, bir sonraki grupla devam et

print(f"\nTamamlandı! Toplam {total_upserted} kayıt upsert edildi.")
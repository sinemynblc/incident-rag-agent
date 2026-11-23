import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

try:
    client = QdrantClient(url=os.environ.get("QDRANT_URL", "http://localhost:6333"))
except Exception as e:
    print(f"Qdrant'a bağlanılamadı: {e}")
    print("Docker'da Qdrant'ın çalıştığından emin olun.")
    exit(1)

collection_name = "data_collection"

try:
    if client.collection_exists(collection_name):
        client.delete_collection(collection_name)
        print(f"Var olan koleksiyon silindi: {collection_name}")

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )
    print(f"Koleksiyon oluşturuldu: {collection_name}")
except Exception as e:
    print(f"Koleksiyon oluşturulurken hata oluştu: {e}")
    exit(1)
    
# 1) Taban imaj: Python 3.11 kurulu, hafif bir Linux
FROM python:3.11-slim

# 2) Konteyner içindeki çalışma klasörü (bundan sonrası hep burada olur)
WORKDIR /app

# 3) ÖNCE sadece requirements.txt'yi kopyala
#    (kod değişince pip install'ı tekrar çalıştırmamak için — katman önbelleği)
COPY requirements.txt .

# 4) Bağımlılıkları kur (Sadece CPU sürümünü indirerek indirmeyi çok daha hızlı hale getiriyoruz)
RUN pip install --no-cache-dir --default-timeout=1000 --retries 5 --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

RUN pip install --no-cache-dir python-dotenv

RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# 5) SONRA tüm proje kodunu kopyala
COPY . .


# 6) Uygulamanın dinleyeceği portu belge amaçlı bildir
EXPOSE 8000

# 7) Konteyner başlayınca çalışacak komut: API'yi başlat
#    host 0.0.0.0 = konteyner dışından erişilebilsin diye (localhost DEĞİL)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
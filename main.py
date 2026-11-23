"""
FastAPI katmanı — agent'lı RAG asistanını HTTP servisi olarak açar.

  - input() ile boş soru kontrolü  -> gelen 'question' boşsa HTTP 400
  - input() ile severity dogrulama  -> gelen 'severity' gecersizse HTTP 400
  - ask_agent + save_to_memory      -> aynı fonksiyonlar, aynen kullanılıyor
  - "/" adresinde static/index.html servis edilir (web arayüzü)
  - session_id: her sohbet (tarayıcıda localStorage'da tutulan bir kimlik)
    kendi izole hafızasını görür; tarayıcı kapanıp açılsa bile (yeni sohbet
    başlatılmadığı sürece) aynı session_id kalıcı olduğu için hafıza kaybolmaz.
  - "/history/{session_id}" ile bir sohbetin geçmişi (sidebar için) çekilebilir.

Calıştırma (lokal):
    uvicorn main:app --reload
Web arayüzü:
    http://localhost:8000/
Test arayüzü (Swagger):
    http://localhost:8000/docs
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

# Mevcut çekirdek mantık — dokunulmadan import ediliyor.
from agent import ask_agent
from rag import save_to_memory, get_session_history, delete_session, DEFAULT_SESSION_ID

# Terminaldeki doğrulamayla aynı geçerli değerler
VALID_SEVERITIES = {"low", "medium", "high", "critical"}

app = FastAPI(title="Incident/RCA RAG Asistanı")

# static/ klasöründeki dosyaları /static altında servis eder.
app.mount("/static", StaticFiles(directory="static"), name="static")


class AskRequest(BaseModel):
    question: str
    service: Optional[str] = None
    severity: Optional[str] = None
    session_id: Optional[str] = None  # verilmezse DEFAULT_SESSION_ID kullanılır


class AskResponse(BaseModel):
    answer: str
    used_tool: bool


class HistoryItem(BaseModel):
    timestamp: str
    question: str
    answer: str
    service: Optional[str] = None
    severity: Optional[str] = None


class HistoryResponse(BaseModel):
    session_id: str
    items: list[HistoryItem]


class DeleteResponse(BaseModel):
    session_id: str
    deleted_count: int


@app.get("/")
def serve_ui():
    """Web arayüzünü (chat ekranı) döndürür — /docs yerine kullanıcı dostu ekran."""
    return FileResponse("static/index.html")


@app.get("/history/{session_id}", response_model=HistoryResponse)
def history(session_id: str):
    """
    Sidebar için: verilen session_id'ye ait TÜM soru-cevap geçmişini döner.
    Sadece JSONL (kronolojik) kayıtlarını kullanır -- mem0'a gitmez, çünkü
    amaç geçmişi ekranda yeniden GÖSTERMEK, semantik arama yapmak değil.
    """
    records = get_session_history(session_id)
    items = [
        HistoryItem(
            timestamp=r.get("timestamp", ""),
            question=r.get("question", ""),
            answer=r.get("answer", ""),
            service=r.get("service"),
            severity=r.get("severity"),
        )
        for r in records
    ]
    return HistoryResponse(session_id=session_id, items=items)


@app.delete("/history/{session_id}", response_model=DeleteResponse)
def delete_history(session_id: str):
    """
    Bir oturumu GERÇEKTEN siler (soft-delete değil) -- hem JSONL'den hem
    mem0'dan. Sidebar'daki silme butonu bu endpoint'i çağırır.
    """
    try:
        deleted_count = delete_session(session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Silme sırasında hata oluştu: {e}")
    return DeleteResponse(session_id=session_id, deleted_count=deleted_count)


"""POST: veri oluşturmak için, GET: veri okumak için."""
@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    # 1) Boş soru kontrolü (terminaldeki 'Lütfen bir soru girin' karşılığı)
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Soru boş olamaz.")

    # 2) Filtre normalizasyonu + severity doğrulama
    service = req.service.strip().lower() if req.service and req.service.strip() else None

    severity = None
    if req.severity and req.severity.strip():
        severity = req.severity.strip().lower()
        if severity not in VALID_SEVERITIES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Geçersiz severity: '{severity}'. "
                    f"Geçerli değerler: {', '.join(sorted(VALID_SEVERITIES))} — ya da boş bırakın."
                ),
            )

    # 3) session_id: istemci göndermediyse varsayılan oturumu kullan
    session_id = req.session_id.strip() if req.session_id and req.session_id.strip() else DEFAULT_SESSION_ID

    # 4) Çekirdek mantık — terminalle birebir aynı, artık session_id ile
    try:
        answer, used_tool = ask_agent(
            question, forced_service=service, forced_severity=severity, session_id=session_id
        )
    except Exception as e:
        # ask_agent beklenmedik şekilde çökerse (ör. Groq API'ye hiç
        # ulaşılamıyor), kullanıcıya anlaşılır bir hata dönüyoruz —
        # ham traceback yerine.
        raise HTTPException(
            status_code=502,
            detail=f"Asistana ulaşılamadı, lütfen daha sonra tekrar deneyin. ({e})",
        )

    # 5) Sadece tool çağrıldıysa hafızaya kaydet (sohbet mesajları kaydedilmez)
    if used_tool:
        try:
            save_to_memory(session_id, question, answer, service=service, severity=severity)
        except Exception as e:
            # Hafızaya kayıt başarısız olsa bile, kullanıcı doğru üretilmiş
            # cevabı kaybetmemeli — sadece logluyoruz, isteği düşürmüyoruz.
            print(f"[main] save_to_memory başarısız oldu, cevap yine de dönülüyor: {e}")

    return AskResponse(answer=answer, used_tool=used_tool)
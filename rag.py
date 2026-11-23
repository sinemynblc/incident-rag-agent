import os
import json
import datetime
from dotenv import load_dotenv

# .env dosyasındaki GROQ_API_KEY, MEM0_API_KEY vb. değişkenleri otomatik yükler
load_dotenv()

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from sentence_transformers import SentenceTransformer
from groq import Groq
from mem0 import MemoryClient

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
client = QdrantClient(url=QDRANT_URL)
model = SentenceTransformer("all-MiniLM-L6-v2")

# mem0 — semantik hafiza icin
mem0_client = MemoryClient(api_key=os.environ.get("MEM0_API_KEY"))
MEM0_USER_ID = "rag"

MEMORY_PATH = "data/memory.jsonl"

# session_id verilmezse (ör. terminalden çalıştırılırken) kullanılan varsayılan oturum.
# Aynı tarayıcı sekmesi kapanıp yeniden açıldığında da (yeni sohbet başlatılmadığı
# sürece) session_id localStorage'da kalıcı olduğu için, hafıza kaybolmaz — ödevin
# "programı kapat, yeniden aç, hatırlıyor mu" testi bu şekilde karşılanır.
DEFAULT_SESSION_ID = "default"

try:
    groq_api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    groq_client = Groq(api_key=groq_api_key)
except Exception as e:
    print(f"Groq client olusturulamadi: {e}")
    print("GROQ_API_KEY ortam degiskenini ayarladiginizdan emin olun.")
    exit(1)


def retrieve(query, limit=3, service=None, severity=None):
    """Qdrant incident koleksiyonunda semantik arama + opsiyonel filtre."""
    try:
        query_vector = model.encode(query).tolist()

        conditions = []
        if service:
            conditions.append(FieldCondition(key="service", match=MatchValue(value=service)))
        if severity:
            conditions.append(FieldCondition(key="severity", match=MatchValue(value=severity)))

        query_filter = Filter(must=conditions) if conditions else None

        results = client.query_points(
            collection_name="data_collection",
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
        )
        return results.points
    except Exception as e:
        print(f"Qdrant aramasi sirasinda hata olustu: {e}")
        return []


def build_context(points):
    """Bulunan incident kayitlarini LLM context formatina cevirir."""
    if not points:
        return "Ilgili kayit bulunamadi."

    context = ""
    for r in points:
        p = r.payload
        context += f"Score: {r.score:.4f}\n"
        context += f"ID: {p.get('id', 'N/A')}\n"
        context += f"Title: {p.get('title', 'N/A')}\n"
        context += f"Service: {p.get('service', 'N/A')}\n"
        context += f"Severity: {p.get('severity', 'N/A')}\n"
        context += f"Date: {p.get('date', 'N/A')}\n"
        context += f"Symptoms: {p.get('symptoms', 'N/A')}\n"
        context += f"Root Cause: {p.get('root_cause', 'N/A')}\n"
        context += f"Resolution: {p.get('resolution', 'N/A')}\n"
        context += "-------------------------\n"
    return context


# ----------------------------------------------------------------------
# HAFIZA: iki kaynak kullanıyoruz, session_id ile ayrıştırılmış
#   1) JSONL'den son 20 kayıt  -> kronolojik "what did i asked before" gibi
#   2) mem0 semantik arama    -> ilgili geçmiş ("bunu konuştuk mu")
# ----------------------------------------------------------------------
def load_recent_memory(session_id=DEFAULT_SESSION_ID, n=20, path=MEMORY_PATH):
    """JSONL'den, VERILEN session_id'ye ait son N konusma kaydi (en yeni sonda), kronolojik."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return ""
    except Exception as e:
        print(f"Hafiza dosyasi okunurken hata: {e}")
        return ""
    if not lines:
        return ""

    # Sadece bu session'a ait kayıtları filtrele. Eski kayıtlarda session_id
    # alanı yoksa (önceki, session'sız veriler), DEFAULT_SESSION_ID'ye ait
    # sayılıyor — geriye dönük uyumluluk için.
    session_lines = [
        rec for rec in lines
        if rec.get("session_id", DEFAULT_SESSION_ID) == session_id
    ]
    if not session_lines:
        return ""

    out = []
    for rec in session_lines[-n:]:
        out.append(
            f"[{rec.get('timestamp', '?')}] "
            f"Q: {rec.get('question', '')} "
            f"(service={rec.get('service')}, severity={rec.get('severity')}) "
            f"A: {rec.get('answer', '')}"
        )
    return "\n".join(out)


def load_semantic_memory(query, session_id=DEFAULT_SESSION_ID, limit=3, service=None, severity=None):
    """mem0'da, VERILEN session_id'ye ait, soruya anlamca en yakin gecmis kayitlari getirir."""
    try:
        filters = {"user_id": MEM0_USER_ID, "session_id": session_id}
        if service:
            filters["service"] = service
        if severity:
            filters["severity"] = severity
        results = mem0_client.search(query, filters=filters, limit=limit)
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        if not results:
            return ""
        return "\n".join(f"- {r['memory']}" for r in results)
    except Exception as e:
        print(f"mem0 aramasi sirasinda hata: {e}")
        return ""


def get_session_history(session_id, path=MEMORY_PATH):
    """
    Sidebar için: VERILEN session_id'ye ait TÜM kayıtları (kırpılmadan),
    kronolojik sırayla, yapılı (dict) liste olarak döner. Bir sohbete geri
    dönüldüğünde ekranı gerçek geçmişle yeniden çizmek için kullanılır.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"Hafiza dosyasi okunurken hata: {e}")
        return []

    return [
        rec for rec in lines
        if rec.get("session_id", DEFAULT_SESSION_ID) == session_id
    ]


def delete_session(session_id, path=MEMORY_PATH):
    """
    Bir oturumu HEM JSONL'den HEM mem0'dan gerçekten siler (soft-delete değil).
    JSONL: o session_id'ye ait olmayan satırları tutup dosyayı yeniden yazar.
    mem0: o session_id'ye ait kayıtları arayıp tek tek siler (mem0 API'sinde
    "filtreye göre toplu sil" garantili olmadığından, best-effort davranır --
    mem0 tarafı başarısız olsa bile JSONL silme işlemi geçerli olur).
    Döner: silinen JSONL kayıt sayısı.
    """
    deleted_count = 0

    # 1) JSONL'den sil
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        lines = []
    except Exception as e:
        print(f"Hafiza dosyasi okunurken hata: {e}")
        lines = []

    remaining = [
        rec for rec in lines
        if rec.get("session_id", DEFAULT_SESSION_ID) != session_id
    ]
    deleted_count = len(lines) - len(remaining)

    if deleted_count > 0:
        try:
            with open(path, "w", encoding="utf-8") as f:
                for rec in remaining:
                    json.dump(rec, f, ensure_ascii=False)
                    f.write("\n")
        except Exception as e:
            print(f"JSONL silme sirasinda hata: {e}")

    # 2) mem0'dan sil (best-effort — mem0 API'si sürüme göre değişebilir)
    try:
        results = mem0_client.get_all(
            user_id=MEM0_USER_ID,
            filters={"session_id": session_id},
        )
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        for r in results or []:
            mem_id = r.get("id")
            if mem_id:
                mem0_client.delete(mem_id)
    except Exception as e:
        print(f"mem0'dan silme sirasinda hata (JSONL silme yine de uygulandi): {e}")

    return deleted_count


def load_memory_jsonl(path=MEMORY_PATH):
    """eval.py bu adı kullanıyor: verilen dosyayı ham okur (tüm session'lar)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""
    except Exception as e:
        print(f"Hafiza dosyasi okunurken hata: {e}")
        return ""


def ask_llm(query, context, recent="", semantic="", service=None, severity=None):
    """Uc kaynagi (incident + kronolojik + semantik) LLM'e verip cevap alir."""
    user_content = f"Records (incident database):\n{context}\n"
    if recent:
        user_content += f"\nRecent conversation (chronological, newest last):\n{recent}\n"
    if semantic:
        user_content += f"\nRelevant past conversation (semantic search):\n{semantic}\n"
    user_content += f"\nQuestion: {query}"
    user_content += f"\nCurrent filters: service={service}, severity={severity}"

    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You have three sources of information:\n"
                        "(1) 'Records' - incident records retrieved fresh for the CURRENT filters.\n"
                        "(2) 'Recent conversation' - the last few exchanges in chronological order.\n"
                        "(3) 'Relevant past conversation' - semantically similar earlier exchanges.\n\n"

                        "CRITICAL RULE FOR SOURCE ATTRIBUTION:\n"
                        "- If the question EXPLICITLY asks about a past conversation or an earlier question "
                        "(e.g., 'asked about earlier', 'we discussed before', 'what was my last question'):\n"
                        "  YOU MUST SET 'Kaynak: Geçmiş konuşma', EVEN IF the technical details or incident IDs "
                        "  (like INC-1003) appear in 'Records'. Do NOT use the incident ID as the source for meta-questions about past chat.\n\n"

                        "Decide which case the question falls into:\n\n"

                        "CASE 1 - The question refers to the immediately preceding exchange "
                        "(e.g. 'what did I just ask', 'what was your last answer'): "
                        "Use 'Recent conversation' and answer with the single most recent entry. "
                        "The user's CURRENT message (the one you are answering right now) is NOT part of "
                        "that history and must NEVER be echoed back as if it were the last question.\n\n"

                        "CASE 2 - The question is about the conversation itself in general "
                        "(e.g. 'have we discussed X before'): "
                        "Use 'Relevant past conversation'.\n\n"

                        "CASE 3 - The question asks for incident information: "
                        "Answer from 'Records'. Filters matter: only reuse a past entry if the "
                        "question is similar AND its service/severity match the current filters. "
                        "If 'Records' is empty for the current filters, say you don't know - do not "
                        "invent an answer from memory.\n\n"

                        "When answering with incident information, ALWAYS include for each incident "
                        "the ID, the title, and a brief root cause summary. Never answer with just IDs.\n\n"

                        "If none of the sources contain the answer, say 'I don't know'.\n"
                        "Answer in English.\n\n"

                        "Format your response EXACTLY like this:\n"
                        "Cevap: <detailed answer, including title and root cause per incident>\n"
                        "Kaynak: <incident ID(s) e.g. INC-1000 | 'Gecmis konusma' if from past "
                        "conversation | empty if unknown>"
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            model="llama-3.3-70b-versatile",
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        print(f"LLM'e ulasilamadi: {e}")
        return "Sorry, I couldn't process your question right now. Please try again."


def save_to_memory(session_id, query, answer, service=None, severity=None):
    """Konusmayi hem JSONL'e (kronolojik) hem mem0'a (semantik) kaydeder -- session_id ile."""
    try:
        os.makedirs("data", exist_ok=True)
        record = {
            "session_id": session_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "question": query,
            "service": service,
            "severity": severity,
            "answer": answer,
        }
        with open(MEMORY_PATH, "a", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        print(f"JSONL kayit hatasi: {e}")

    try:
        mem0_client.add(
            [{"role": "user", "content": query}],
            user_id=MEM0_USER_ID,
            metadata={"service": service, "severity": severity, "session_id": session_id},
        )
    except Exception as e:
        print(f"mem0 kayit hatasi: {e}")


if __name__ == "__main__":
    print("RAG asistanina hos geldiniz. Cikmak icin 'q' yazin.\n")

    # Terminal kullanımında tek, sabit bir oturum kullanılıyor.
    session_id = DEFAULT_SESSION_ID

    while True:
        query = input("Soru sor: ")

        if query.lower() in ["q", "quit", "exit", "cikis", "çıkış"]:
            print("Gorusuruz!")
            break

        service = input("Service filtresi (bos birakabilirsin): ").strip() or None
        severity = input("Severity filtresi (bos birakabilirsin): ").strip() or None

        points = retrieve(query, service=service, severity=severity)
        context = build_context(points)

        recent = load_recent_memory(session_id=session_id, n=20)
        semantic = load_semantic_memory(query, session_id=session_id, service=service, severity=severity)

        answer = ask_llm(query, context, recent, semantic, service=service, severity=severity)
        print(f"\n{answer}\n")

        save_to_memory(session_id, query, answer, service=service, severity=severity)
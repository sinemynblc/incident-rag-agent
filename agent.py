import json
import os
from dotenv import load_dotenv

# .env dosyasındaki ortam değişkenlerini yükler
load_dotenv()

# rag.py'dan import ediyoruz
from rag import (
    groq_client,
    retrieve,
    build_context,
    load_recent_memory,
    load_semantic_memory,
    save_to_memory,
    DEFAULT_SESSION_ID,
)


def search_incidents(query, service=None, severity=None, limit=3):
    """Qdrant'ta incident kayıtlarında semantik arama yapar (rag.py: retrieve + build_context)."""
    points = retrieve(query, limit=limit, service=service, severity=severity)
    return build_context(points)


def search_memory(query=None, service=None, severity=None, session_id=DEFAULT_SESSION_ID):
    """
    Geçmiş konuşmada arama yapar -- SADECE çağıran oturumun (session_id) kayıtlarında.
    - Kronolojik: JSONL'den bu session'ın son N kaydı (load_recent_memory).
    - Semantik: query verilirse mem0 ile bu session'a ait, anlamca yakın kayıtlar.
    """
    recent = load_recent_memory(session_id=session_id, n=20)
    semantic = load_semantic_memory(query, session_id=session_id, service=service, severity=severity) if query else ""

    parts = []
    if recent:
        parts.append("--- Recent Conversation (Chronological JSONL) ---\n" + recent)
    if semantic:
        parts.append("--- Semantically Relevant Memory (mem0) ---\n" + semantic)

    return "\n\n".join(parts) if parts else "İlgili geçmiş konuşma bulunamadı."


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_incidents",
            "description": (
                "Search the incident/root-cause database semantically. "
                "Use this whenever the question is about what happened, why something broke, "
                "root causes, symptoms, or resolutions. "
                "Do NOT try to guess or extract a service/severity filter from the question - "
                "those are applied automatically from the UI if the user set them. Only pass 'query'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "Searches past conversation WITHIN THE CURRENT SESSION ONLY. Returns the most "
                "recent exchanges in chronological order, plus (if a query is given) semantically "
                "similar earlier exchanges from this same session. Use for: "
                "(1) the most recent exchange (e.g. 'what was my last question') - the newest entry "
                "is at the end of the chronological list; "
                "(2) a topic discussed earlier (e.g. 'have we discussed X before') - pass that topic "
                "as 'query' to find semantically related entries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": ["string", "null"],
                        "description": "Optional topic to search semantically in past conversation. "
                                       "Use null or omit for 'what did I just ask' style questions.",
                    },
                },
            },
        },
    },
]

AVAILABLE_FUNCTIONS = {
    "search_incidents": search_incidents,
    "search_memory": search_memory,
}

SYSTEM_PROMPT = (
    "You are an expert root-cause assistant. You have access to two tools:\n"
    "1. 'search_incidents': Searches the Qdrant incident/root-cause database for system issues, symptoms, and resolutions.\n"
    "2. 'search_memory': Searches past conversation history WITHIN THE CURRENT SESSION ONLY. It returns TWO sources:\n"
    "   - Chronological memory (JSONL): The most recent exchanges in this session.\n"
    "   - Semantic memory (mem0): Semantically related past exchanges from this session, when a topic query is provided.\n\n"

    "--- TOOL USAGE RULES ---\n"
    "- Call a tool ONLY if external information is required to answer.\n"
    "- For general chit-chat, math, or greetings, answer directly WITHOUT calling tools.\n"
    "- CRITICAL: Service and severity filters are managed via the UI. Never try to extract or guess filter values from the user's text.\n\n"

    "--- RAG & MEMORY ROUTING ---\n"
    "Categorize the user query into one of the following cases:\n\n"

    "CASE 1 - Query explicitly asks about PAST CONVERSATION (e.g., 'what did I ask before', 'what was your last answer', 'have we discussed X'):\n"
    "- Call 'search_memory'.\n"
    "- For 'what did I just ask' type queries, leave 'query' empty/null to check the end of the Chronological (JSONL) list.\n"
    "- CRITICAL: The user's CURRENT message (the one you are answering right now) is NOT part of the conversation "
    "history. When determining 'the last question', use ONLY the entries returned by the 'Recent Conversation "
    "(Chronological JSONL)' section from the search_memory tool result. NEVER treat the current message itself "
    "as 'the last question' or echo it back verbatim as if it were something asked before.\n"
    "- For 'have we discussed X' type queries, pass X as the 'query' parameter to leverage Semantic (mem0) memory.\n"
    "- Answer using the relevant memory entry, ignoring UI filters.\n"
    "- Set 'Kaynak: Geçmiş konuşma'.\n\n"

    "CASE 2 - Query asks for INCIDENT / ROOT CAUSE information:\n"
    "- Call 'search_incidents'.\n"
    "- Base your response primarily on retrieved incident records.\n"
    "- REUSE RULE: You may only reuse answers from past conversation memory if the query is similar AND its past service/severity filters EXACTLY match current UI filters. If filters differ, ignore memory and use fresh incident records.\n"
    "- ALWAYS include Incident ID, Title, and a brief Root Cause summary for EACH incident. Never return just IDs.\n"
    "- Set 'Kaynak: <INCIDENT_IDs>' (e.g., INC-1000, INC-1002).\n\n"

    "CASE 3 - UNKNOWN / NO DATA:\n"
    "- If no relevant records or memories are found, state 'I don't know'.\n"
    "- Set 'Kaynak:' empty.\n\n"

    "--- OUTPUT FORMATTING ---\n"
    "- Answer content must be in English.\n"
    "- IF A TOOL WAS CALLED, strictly follow this format:\n"
    "Cevap: <Your detailed explanation in English, including ID, Title, and Root Cause per incident>\n"
    "Kaynak: <INC-ID(s) OR 'Geçmiş konuşma' OR leave empty if unknown>\n\n"

    "- IF NO TOOL WAS CALLED, do NOT use the 'Cevap:' / 'Kaynak:' format; respond naturally in English."
)


def ask_agent(user_query, max_turns=3, forced_service=None, forced_severity=None, session_id=DEFAULT_SESSION_ID):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    user_content = user_query
    if forced_service or forced_severity:
        user_content += (
            f"\n\n[Note: the user has already specified filters via the UI: "
            f"service={forced_service or 'none'}, severity={forced_severity or 'none'}. "
            f"You do NOT need to ask for these - use them directly when calling search_incidents.]"
        )
    messages.append({"role": "user", "content": user_content})

    used_tool = False

    for _ in range(max_turns):
        try:
            response = groq_client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0,
            )
        except Exception as e:
            print(f"[agent] Tool call hatası, tool'suz tekrar deneniyor: {e}")
            messages.append({
                "role": "system",
                "content": (
                    "Tool calls failed due to a technical error. You currently have NO access to "
                    "incident data or memory. If you don't already know the answer with certainty, "
                    "say 'I don't know'. Do NOT invent incident IDs, numbers, or configuration values."
                ),
            })
            fallback = groq_client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=messages,
                temperature=0,
            )
            return fallback.choices[0].message.content, used_tool

        msg = response.choices[0].message

        if not msg.tool_calls:
            return msg.content, used_tool

        used_tool = True

        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })

        for tool_call in msg.tool_calls:
            func_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments or "{}")

            # Kullanıcı elle bir filtre verdiyse, LLM'in kararına bakmaksızın zorla uygula.
            if func_name == "search_incidents":
                if forced_service:
                    args["service"] = forced_service
                if forced_severity:
                    args["severity"] = forced_severity

            # search_memory HER ZAMAN çağıran oturumun session_id'sini kullanmalı --
            # bu, LLM'in karar vereceği bir şey değil, sistem tarafından zorlanır.
            if func_name == "search_memory":
                args["session_id"] = session_id

            # null gelen argümanları at ki fonksiyonun varsayılanı (None) devreye girsin
            args = {k: v for k, v in args.items() if v is not None}

            print(f"  [agent] çağrılıyor: {func_name}({args})")

            func = AVAILABLE_FUNCTIONS.get(func_name)
            try:
                result = func(**args) if func else f"Bilinmeyen tool: {func_name}"
            except Exception as e:
                # Tool çalışırken beklenmedik bir hata olursa (ör. Qdrant/mem0
                # bağlantısı koptu), tüm isteği çökertmek yerine LLM'e bu
                # bilgiyi veriyoruz -- o da "I don't know" diyerek toparlanabilir.
                print(f"  [agent] {func_name} çalışırken hata: {e}")
                result = f"Tool execution failed ({func_name}): {e}. No data could be retrieved."

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": func_name,
                "content": result,
            })

    return "Üzgünüm, birden fazla tool denemesine rağmen bir cevaba ulaşamadım.", used_tool


if __name__ == "__main__":
    print("Agent'lı RAG asistanına hoş geldiniz. Çıkmak için 'q' yazın.\n")

    # Terminal kullanımında tek, sabit bir oturum kullanılıyor.
    session_id = DEFAULT_SESSION_ID

    while True:
        query = input("Soru sor: ")
        if query.lower() in ["q", "quit", "exit", "çıkış"]:
            print("Görüşürüz!")
            break

        if not query.strip():
            print("Lütfen bir soru girin.\n")
            continue

        service = input("Service filtresi (boş bırakabilirsin): ").strip() or None
        severity = input("Severity filtresi (boş bırakabilirsin): ").strip() or None

        answer, used_tool = ask_agent(
            query, forced_service=service, forced_severity=severity, session_id=session_id
        )
        print(f"\n{answer}\n")

        if used_tool:
            save_to_memory(session_id, query, answer, service=service, severity=severity)
        else:
            print("[agent] (tool cagrilmadi - sohbet mesaji, kaydedilmedi)")
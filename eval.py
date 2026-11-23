import json
import re
from rag import load_memory_jsonl, retrieve, build_context, ask_llm, groq_client

def load_test_cases(path="data/test_cases.jsonl"):
    test_cases = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    test_cases.append(json.loads(line))
    except FileNotFoundError:
        print(f"Hata: {path} dosyası bulunamadı!")
    return test_cases


def judge_answer(question, expected_answer, actual_answer):
    """LLM'e, gerçek cevabın beklenen cevaba anlamca yakın olup olmadığını sorar."""
    judge_prompt = f"""You are a strict evaluator. Compare the ACTUAL answer to the EXPECTED answer for the given question.
Decide if the ACTUAL answer captures the same core meaning as the EXPECTED answer, even if worded differently.

Question: {question}

Expected answer: {expected_answer}

Actual answer: {actual_answer}

Respond with ONLY one word: MATCH or NO_MATCH."""

    try:
        response = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": judge_prompt}],
            model="llama-3.3-70b-versatile",
        )
        verdict = response.choices[0].message.content.strip().upper()
        return "MATCH" in verdict
    except Exception as e:
        print(f"LLM Judge hatası: {e}")
        return False


def normalize_text(text):
    """Türkçe/İngilizce karakter farkını (ş->s, ç->c vb.) göz ardı etmek için metni düzenler."""
    replacements = {
        'ş': 's', 'Ş': 's', 'ç': 'c', 'Ç': 'c', 
        'ğ': 'g', 'Ğ': 'g', 'ü': 'u', 'Ü': 'u', 
        'ö': 'o', 'Ö': 'o', 'ı': 'i', 'İ': 'i'
    }
    text = text.lower()
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text

def check_source(actual_answer, expected_source):
    """Cevaptaki kaynağın, beklenen kaynakla esnek şekilde eşleşip eşleşmediğini kontrol eder."""
    if "Kaynak:" in actual_answer:
        source_line = actual_answer.split("Kaynak:")[-1].strip()
    else:
        source_line = actual_answer.strip()

    norm_source_line = normalize_text(source_line)
    norm_expected = normalize_text(expected_source)

    # 1. Kaynak beklenmiyorsa (boşsa)
    if not expected_source:
        return not re.search(r"INC-\d+", source_line) and "gecmis konusma" not in norm_source_line

    # 2. Beklenen "Geçmiş konuşma" ise
    if norm_expected == "gecmis konusma":
        return "gecmis konusma" in norm_source_line or "past conversation" in norm_source_line

    # 3. Birden fazla INC-ID bekleniyorsa (örneğin "INC-1000, INC-1044")
    # Virgülle veya başka şekilde ayrılmış tüm ID'lerin kaynak satırında geçtiğini kontrol et
    expected_ids = [idx.strip() for idx in norm_expected.replace("|", ",").split(",") if idx.strip()]
    if expected_ids:
        return all(idx in norm_source_line for idx in expected_ids)

    return norm_expected in norm_source_line


def run_eval():
    test_cases = load_test_cases()
    if not test_cases:
        print("Test edilecek senaryo bulunamadı.")
        return

    passed_answer = 0
    passed_source = 0
    total = len(test_cases)
    
    # Test hafızası dosyasını yüklüyoruz
    test_memory = load_memory_jsonl("data/test_memory.jsonl")

    print("\n--- RAG (ask_llm) EVALUATION BAŞLATILDI ---")

    for i, case in enumerate(test_cases, 1):
        question = case["question"]
        expected_answer = case["expected_answer"]
        expected_source = case.get("expected_source", "")
        service = case.get("service")
        severity = case.get("severity")

        # 1. Qdrant'tan Incident kayıtlarını çek
        points = retrieve(question, service=service, severity=severity)
        context = build_context(points)

        # 2. Doğrudan ask_llm'i çağır
        actual_answer = ask_llm(
            query=question,
            context=context,
            recent=test_memory,  # test_memory.jsonl'deki geçmiş konuşmaları veriyoruz
            service=service,
            severity=severity
        )

        answer_match = judge_answer(question, expected_answer, actual_answer)
        source_match = check_source(actual_answer, expected_source)

        answer_status = "BAŞARILI" if answer_match else "BAŞARISIZ"
        source_status = "BAŞARILI" if source_match else "BAŞARISIZ"

        if answer_match:
            passed_answer += 1
        if source_match:
            passed_source += 1

        print(f"\n[{i}/{total}] Cevap: {answer_status} | Kaynak: {source_status}")
        print(f"Soru: {question}")
        print(f"Beklenen cevap: {expected_answer}")
        print(f"Beklenen kaynak: {expected_source if expected_source else '(yok)'}")
        print(f"Gerçek cevap: {actual_answer}")
        print("-" * 60)

    print(f"\n=== EVAL SONUÇLARI ===")
    print(f"Cevap doğruluğu: {passed_answer}/{total} ({(passed_answer/total)*100:.1f}%)")
    print(f"Kaynak doğruluğu: {passed_source}/{total} ({(passed_source/total)*100:.1f}%)")


if __name__ == "__main__":
    run_eval()
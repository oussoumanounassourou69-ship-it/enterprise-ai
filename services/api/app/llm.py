import json
import httpx
from .config import get_settings

class LLMProvider:
    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 1200) -> str:
        raise NotImplementedError

class MockLLM(LLMProvider):
    async def chat(self, messages, temperature=0.2, max_tokens=1200):
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return f"[MODE MOCK] J’ai reçu votre demande : {user}\n\nPour activer l’intelligence locale, démarrez vLLM et définissez LLM_MODE=vllm."

class VLLMProvider(LLMProvider):
    def __init__(self):
        s = get_settings(); self.base_url=s.llm_base_url.rstrip('/'); self.api_key=s.llm_api_key; self.model=s.model_name
    async def chat(self, messages, temperature=0.2, max_tokens=1200):
        payload={"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        headers={"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=180) as client:
            r=await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

class OllamaProvider(LLMProvider):
    def __init__(self):
        s = get_settings(); self.base_url=s.ollama_base_url.rstrip('/'); self.model=s.ollama_model

    async def chat(self, messages, temperature=0.2, max_tokens=1200):
        settings=get_settings()
        payload={"model": self.model, "messages": messages, "stream": False, "think": False, "keep_alive": "10m", "options": {"temperature": temperature, "num_predict": settings.llm_max_tokens, "num_ctx": 2048, "num_thread": 4}}
        async with httpx.AsyncClient(timeout=180) as client:
            r=await client.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"]

async def classify_intent(message: str, history: list[dict] | None = None) -> str | None:
    settings=get_settings()
    if settings.llm_mode.lower() != "ollama":
        return None
    conversation_context='\n'.join(f"{item.get('role')}: {item.get('content')}" for item in (history or [])[-4:])
    payload={
        "model": settings.ollama_model,
        "messages":[{
            "role":"user",
            "content":("Classify this user request. Return JSON only with one intent: "
                       "document_catalog, knowledge_question, or general. "
                       "Examples: 'Quelles références sont chargées ?' and "
                       "'Qu’est-ce qui est actuellement chargé ?' are document_catalog; "
                       "'Comment fonctionne cette procédure ?' and "
                       "'Quelles sont les conséquences d’une gifle au travail ?' are knowledge_question; "
                       "'J’ai giflé mon chef' is general. "
                       "Use the conversation context to interpret follow-up questions; "
                       "'Quels sont les risques ?' after a workplace incident is knowledge_question. "
                       f"Conversation context:\n{conversation_context}\nRequest: {message}")
        }],
        "stream":False,
        "think":False,
        "format":"json",
        "options":{"temperature":0,"num_predict":16,"num_ctx":512,"num_thread":4},
    }
    try:
        async with httpx.AsyncClient(timeout=min(settings.intent_timeout_seconds, 8.0)) as client:
            response=await client.post(f"{settings.ollama_base_url.rstrip('/')}/api/chat",json=payload)
            response.raise_for_status()
            content=response.json().get("message",{}).get("content","")
            data=json.loads(content)
            intent=data.get("intent") or data.get("classification")
            return intent if intent in {"document_catalog","knowledge_question","general"} else None
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return None

def get_llm() -> LLMProvider:
    mode=get_settings().llm_mode.lower()
    if mode == "vllm": return VLLMProvider()
    if mode == "ollama": return OllamaProvider()
    return MockLLM()

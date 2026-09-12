import os
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from supabase import create_client

# 1. Credenciales de entorno
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ilvssohttgguxdijhuyo.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 2. Inicialización de app y clientes
app = FastAPI(title="API Asistente Tributario SUNAT")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

class ConsultaRequest(BaseModel):
    pregunta: str
    razonamiento: bool = False

# 3. Función con cascada de recuperación para embeddings
def obtener_embedding(texto: str):
    modelos_candidatos = [
        "text-embedding-004",
        "embedding-001",
        "models/text-embedding-004",
        "models/embedding-001"
    ]
    
    for modelo in modelos_candidatos:
        try:
            res = ai_client.models.embed_content(
                model=modelo,
                contents=texto
            )
            # Extraer los valores vectoriales según el atributo devuelto
            if hasattr(res, 'embedding') and res.embedding:
                return list(res.embedding.values)
            elif hasattr(res, 'embeddings') and res.embeddings:
                return list(res.embeddings[0].values)
        except Exception as e:
            print(f"[INFO] Intento fallido con modelo '{modelo}': {e}")
            continue

    # Diagnóstico secundario si fallan los nombres conocidos
    try:
        print("\n[DIAGNÓSTICO] Modelos disponibles en esta API Key:")
        for m in ai_client.models.list():
            print(f" -> {m.name}")
    except Exception as list_err:
        print(f"[DIAGNÓSTICO ERROR] No se pudieron listar los modelos: {list_err}")

    raise ValueError("Ningún modelo de embedding respondió correctamente con la API Key configurada.")

# 4. Endpoint principal
@app.post("/api/chat")
def responder_consulta(consulta: ConsultaRequest):
    try:
        # Generar embedding vectorial
        query_vector = obtener_embedding(consulta.pregunta)

        # Consultar Supabase
        response = supabase.rpc(
            "match_documentos",
            {
                "query_embedding": query_vector,
                "match_threshold": 0.2,
                "match_count": 3,
            }
        ).execute()

        contexto = "\n\n".join([doc["contenido"] for doc in response.data]) if response.data else "No hay contexto relevante disponible."

        prompt_final = f"""
Eres un Asistente IA experto en normativa tributaria peruana (SUNAT).
Responde a la pregunta del usuario únicamente con la información dada en el contexto.

--- CONTEXTO EXTRAÍDO ---
{contexto}
--- FIN CONTEXTO ---

Pregunta del usuario: {consulta.pregunta}
Respuesta clara y precisa:
"""

        # Respuesta final con modelo Flash
        respuesta = ai_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt_final
        )

        return {"respuesta": respuesta.text}

    except Exception as e:
        print("\n=== ERROR DETECTADO EN /api/chat ===")
        traceback.print_exc()
        print("====================================\n")
        raise HTTPException(status_code=500, detail=str(e))
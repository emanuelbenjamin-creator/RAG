import os
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ilvssohttgguxdijhuyo.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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

def obtener_embedding(texto: str):
    modelos_candidatos = [
        "gemini-embedding-001",
        "gemini-embedding-2"
    ]
    
    for modelo in modelos_candidatos:
        try:
            res = ai_client.models.embed_content(
                model=modelo,
                contents=texto,
                config=types.EmbedContentConfig(output_dimensionality=1024)
            )
            
            if hasattr(res, 'embeddings') and res.embeddings:
                return list(res.embeddings[0].values)
            elif hasattr(res, 'embedding') and res.embedding:
                return list(res.embedding.values)
        except Exception as e:
            print(f"[INFO] Intento fallido con modelo '{modelo}': {e}")
            continue

    raise ValueError("No se pudo generar el embedding.")

@app.post("/api/chat")
def responder_consulta(consulta: ConsultaRequest):
    try:
        query_vector = obtener_embedding(consulta.pregunta)

        response = supabase.rpc(
            "match_documentos",
            {
                "query_embedding": query_vector,
                "match_threshold": 0.0,
                "match_count": 6,
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

        respuesta = ai_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt_final
        )

        return {"respuesta": respuesta.text}

    except Exception as e:
        print("\n=== ERROR DETECTADO EN /api/chat ===")
        traceback.print_exc()
        print("====================================\n")
        raise HTTPException(status_code=500, detail=str(e))
import os
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
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

@app.post("/api/chat")
def responder_consulta(consulta: ConsultaRequest):
    try:
        # 1. Generar embedding con Gemini
        embed_response = ai_client.models.embed_content(
            model="text-embedding-004",
            contents=consulta.pregunta
        )
        
        # Extraer vector con respaldo de formato
        if hasattr(embed_response, 'embedding') and embed_response.embedding:
            query_vector = list(embed_response.embedding.values)
        elif hasattr(embed_response, 'embeddings') and embed_response.embeddings:
            query_vector = list(embed_response.embeddings[0].values)
        else:
            raise ValueError("No se pudo extraer el vector de embedding de la respuesta.")

        # 2. Búsqueda vectorial en Supabase
        response = supabase.rpc(
            "match_documentos",
            {
                "query_embedding": query_vector,
                "match_threshold": 0.2,
                "match_count": 3,
            }
        ).execute()

        contexto = "\n\n".join([doc["contenido"] for doc in response.data]) if response.data else "No hay contexto relevante disponible."

        # 3. Prompt RAG
        prompt_final = f"""
Eres un Asistente IA experto en normativa tributaria peruana (SUNAT).
Responde a la pregunta del usuario únicamente con la información dada en el contexto.

--- CONTEXTO EXTRAÍDO ---
{contexto}
--- FIN CONTEXTO ---

Pregunta del usuario: {consulta.pregunta}
Respuesta clara y precisa:
"""

        # 4. Generar respuesta con Gemini
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
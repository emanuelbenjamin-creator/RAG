import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from supabase import create_client

# 1. Configuración de credenciales desde variables de entorno
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ilvssohttgguxdijhuyo.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 2. Inicializar clientes
app = FastAPI(title="API Asistente Tributario SUNAT")

# Configurar CORS para permitir peticiones desde el frontend (Vercel/Local)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# 3. Definir el formato de la petición esperada
class ConsultaRequest(BaseModel):
    pregunta: str

# 4. Crear el Endpoint de consulta
@app.post("/api/chat")
def responder_consulta(consulta: ConsultaRequest):
    try:
        # Generar embedding ligero usando la API de Gemini (0% consumo de RAM)
        embed_response = ai_client.models.embed_content(
            model="text-embedding-004",
            contents=consulta.pregunta
        )
        query_vector = embed_response.embeddings[0].values

        # Recuperar fragmentos desde Supabase
        response = supabase.rpc(
            "match_documentos",
            {
                "query_embedding": query_vector,
                "match_threshold": 0.2,
                "match_count": 3,
            }
        ).execute()

        # Unificar contexto recuperado
        contexto = "\n\n".join([doc["contenido"] for doc in response.data]) if response.data else "No hay contexto relevante disponible."

        # Prompt estructurado RAG
        prompt_final = f"""
Eres un Asistente IA experto en normativa tributaria peruana (SUNAT).
Responde a la pregunta del usuario únicamente con la información dada en el contexto.

--- CONTEXTO EXTRAÍDO ---
{contexto}
--- FIN CONTEXTO ---

Pregunta del usuario: {consulta.pregunta}
Respuesta clara y precisa:
"""

        # Generar respuesta con Gemini
        respuesta = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_final
        )

        return {"respuesta": respuesta.text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
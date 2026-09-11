from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from sentence_transformers import SentenceTransformer
from supabase import create_client

# 1. Configuración de credenciales
SUPABASE_URL = "https://ilvssohttgguxdijhuyo.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlsdnNzb2h0dGdndXhkaWpodXlvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODkwMDkxMDMsImV4cCI6MjEwNDU4NTEwM30.nAj-R9Ij0JXlb0k_78OBil8vZ8TJ0rzt2S24SOiDXB0" 
GEMINI_API_KEY = "AIzaSyBBd36hLaisru5qf22cp-dBH2foaKd1aCE"

# 2. Inicializar clientes y modelos
app = FastAPI(title="API Asistente Tributario SUNAT")

# Configurar CORS para permitir peticiones desde el frontend (React)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # En producción se cambia por la URL de tu frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)
embedding_model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

# 3. Definir el formato de la petición esperada
class ConsultaRequest(BaseModel):
    pregunta: str

# 4. Crear el Endpoint de consulta
@app.post("/api/chat")
async def chat_tributario(request: ConsultaRequest):
    try:
        # Vectorizar la pregunta
        query_vector = embedding_model.encode(request.pregunta).tolist()

        # Recuperar contexto de Supabase
        response = supabase.rpc(
            "match_documentos",
            {
                "query_embedding": query_vector,
                "match_threshold": 0.2,
                "match_count": 3,
            },
        ).execute()

        contexto = "\n\n".join([doc["contenido"] for doc in response.data])

        # Generar respuesta con Gemini
        prompt_final = f"""
        Eres un Asistente IA experto en normativa tributaria peruana (SUNAT).
        Responde a la pregunta del usuario únicamente basándote en la siguiente información de referencia:

        --- CONTEXTO EXTRAÍDO ---
        {contexto}
        --- FIN CONTEXTO ---

        Pregunta del usuario: {request.pregunta}
        Respuesta clara y precisa:
        """

        ia_response = ai_client.models.generate_content(
            model="models/gemini-3.6-flash", contents=prompt_final
        )

        return {"respuesta": ia_response.text, "contexto_usado": len(response.data)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
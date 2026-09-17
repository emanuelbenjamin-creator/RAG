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

# Mismo modelo/dimensión que upload_to_supabase.py — NO cambiar sin reindexar todo
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 1024

# Umbral mínimo de similitud para considerar un chunk "relevante".
# Con match_threshold=0.0 el sistema nunca dice "no lo sé" — ajusta este valor
# probando con preguntas dentro y fuera de tu dominio cargado.
MATCH_THRESHOLD = 0.65
MATCH_COUNT = 8

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
    res = ai_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texto,
        config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM),
    )
    if hasattr(res, "embeddings") and res.embeddings:
        return list(res.embeddings[0].values)
    elif hasattr(res, "embedding") and res.embedding:
        return list(res.embedding.values)
    raise ValueError("No se pudo generar el embedding.")


@app.post("/api/chat")
def responder_consulta(consulta: ConsultaRequest):
    try:
        query_vector = obtener_embedding(consulta.pregunta)

        response = supabase.rpc(
            "match_documentos",
            {
                "query_embedding": query_vector,
                "match_threshold": MATCH_THRESHOLD,
                "match_count": MATCH_COUNT,
            },
        ).execute()

        # Si no hay nada por encima del umbral, no fuerces una respuesta:
        # esto es tu garantía anti-alucinación.
        if not response.data:
            return {
                "respuesta": "No tengo información cargada sobre esa norma o tema todavía. "
                             "Estoy ampliando la base de conocimiento continuamente."
            }

        contexto = "\n\n".join([doc["contenido"] for doc in response.data])
        confianza = max((doc.get("similarity", 0) for doc in response.data), default=0)

        prompt_final = f"""
Eres un asistente que ayuda a contadores peruanos a entender normativa de SUNAT de forma clara y cercana, como lo explicaría un colega con experiencia, no como un documento legal.
Responde a la pregunta del usuario utilizando únicamente la información proporcionada en el contexto.

Toma en cuenta que el texto extraído del PDF puede presentar pequeñas variaciones tipográficas o espaciados irregulares (por ejemplo, "Catálogo No. 14" o "Catálogo N° 14", "e ste", "s e").
Relaciona los códigos de catálogo (como 1001, 1002, 1003) con sus descripciones de montos (operaciones gravadas, exoneradas, inafectas).

Reglas de estilo para tu respuesta:
- Escribe en texto plano, en párrafos normales. NO uses markdown: nada de asteriscos para negrita, nada de numerales #, nada de guiones como viñetas salvo que listar algo lo haga mucho más claro.
- No entrecomilles términos ni definiciones salvo que estés citando el nombre exacto de una norma (ej. Ley N° 30057).
- Ve directo al punto, como si le explicaras a un colega contador, no como si citaras un artículo legal textual.
- Si citas el nombre de una norma o resolución, menciónalo de forma natural dentro de la oración, no como referencia aislada.

--- CONTEXTO EXTRAÍDO ---
{contexto}
--- FIN CONTEXTO ---

Pregunta del usuario: {consulta.pregunta}
Respuesta:
"""

        respuesta = ai_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt_final,
        )

        return {"respuesta": respuesta.text, "confianza": round(confianza, 3)}

    except Exception as e:
        print("\n=== ERROR DETECTADO EN /api/chat ===")
        traceback.print_exc()
        print("====================================\n")
        raise HTTPException(status_code=500, detail=str(e))

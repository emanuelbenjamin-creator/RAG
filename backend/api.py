import os
import time
import random
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
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

        # --- Expansión con chunks vecinos ---
        # Una tabla o una idea puede cortarse justo entre dos chunks (ej. salto de
        # página). Para no perder esa continuación, además de los chunks que
        # matchearon por similitud, traemos también el chunk anterior y el
        # siguiente de CADA UNO dentro del mismo documento.
        chunks_por_id = {d["id"]: d for d in response.data}

        for doc in response.data:
            metadata = doc.get("metadata") or {}
            chunk_id = metadata.get("chunk_id")
            fuente_archivo = metadata.get("fuente_archivo")
            if chunk_id is None or fuente_archivo is None:
                continue
            for vecino_id in (chunk_id - 1, chunk_id + 1):
                try:
                    vecino = (
                        supabase.table("documentos_tributarios")
                        .select("id, contenido, metadata")
                        .eq("metadata->>fuente_archivo", fuente_archivo)
                        .eq("metadata->>chunk_id", str(vecino_id))
                        .execute()
                    )
                    for v in vecino.data:
                        if v["id"] not in chunks_por_id:
                            chunks_por_id[v["id"]] = v
                except Exception:
                    pass  # si falla traer un vecino, seguimos con lo que ya tenemos

        # Ordenamos por chunk_id para que el contexto se lea en el orden original
        # del documento, no en el orden aleatorio de similitud.
        chunks_ordenados = sorted(
            chunks_por_id.values(),
            key=lambda d: (d.get("metadata") or {}).get("chunk_id", 0),
        )

        contexto = "\n\n".join([doc["contenido"] for doc in chunks_ordenados])
        confianza = max((doc.get("similarity", 0) for doc in response.data), default=0)

        prompt_final = f"""
Eres un asistente que ayuda a contadores peruanos a entender normativa de SUNAT de forma clara y cercana, como lo explicaría un colega con experiencia, no como un documento legal.
Responde a la pregunta del usuario utilizando únicamente la información proporcionada en el contexto.

Toma en cuenta que el texto extraído del PDF puede presentar pequeñas variaciones tipográficas o espaciados irregulares (por ejemplo, "Catálogo No. 14" o "Catálogo N° 14", "e ste", "s e").
Relaciona los códigos de catálogo (como 1001, 1002, 1003) con sus descripciones de montos (operaciones gravadas, exoneradas, inafectas).

Reglas de estilo para tu respuesta:
- Escribe en texto plano, en párrafos normales, como una conversación entre colegas. NO uses markdown (nada de asteriscos, numerales #), NI listas numeradas o con viñetas, aunque el contexto original sí sea una tabla o lista — redacta esa información como oración corrida, usando conectores como "además", "también", "por otro lado", "en cuanto a".
- Aun así, sé completo y preciso: no sacrifiques ningún dato relevante del contexto por escribir en prosa. Si hay varios ítems obligatorios que mencionar, inclúyelos todos dentro del párrafo, solo que redactados de forma natural en vez de como lista.
- No entrecomilles términos ni definiciones salvo que estés citando el nombre exacto de una norma (ej. Ley N° 30057).
- Ve directo al punto, sin relleno ni frases de cortesía largas al inicio.
- Si citas el nombre de una norma o resolución, menciónalo de forma natural dentro de la oración, no como referencia aislada.

--- CONTEXTO EXTRAÍDO ---
{contexto}
--- FIN CONTEXTO ---

Pregunta del usuario: {consulta.pregunta}
Respuesta:
"""

        # Cadena de modelos: si el principal está saturado (503), cae al siguiente.
        # La saturación es por modelo específico, así que un modelo distinto
        # suele responder de inmediato aunque el primero esté con alta demanda.
        MODELOS_CHAIN = ["gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.0-flash"]

        respuesta = None
        ultimo_error = None
        for modelo in MODELOS_CHAIN:
            exito = False
            for intento in range(1, 4):
                try:
                    respuesta = ai_client.models.generate_content(
                        model=modelo,
                        contents=prompt_final,
                    )
                    exito = True
                    break
                except genai_errors.ServerError as e:
                    ultimo_error = e
                    es_sobrecarga = "503" in str(e) or "UNAVAILABLE" in str(e)
                    if es_sobrecarga and intento < 3:
                        espera = (2 ** intento) + random.uniform(0, 1)
                        print(f"  [WARN] {modelo} con alta demanda (503). "
                              f"Reintento {intento}/3 en {espera:.1f}s...")
                        time.sleep(espera)
                        continue
                    break  # se acabaron los reintentos para este modelo, prueba el siguiente
            if exito:
                if modelo != MODELOS_CHAIN[0]:
                    print(f"  [INFO] Se usó el modelo de respaldo: {modelo}")
                break

        if respuesta is None:
            # Los 3 modelos fallaron: en vez de un error, devolvemos el contexto
            # crudo que sí logramos recuperar de Supabase. Menos pulido, pero
            # sigue siendo información real y útil para el usuario.
            print(f"  [WARN] Los 3 modelos fallaron. Devolviendo contexto crudo. "
                  f"Último error: {ultimo_error}")
            resumen_crudo = "\n\n".join(
                doc["contenido"] for doc in chunks_ordenados[:3]
            )
            return {
                "respuesta": (
                    "El asistente de redacción está saturado en este momento, pero esto es "
                    "justo lo que encontré en la normativa cargada sobre tu pregunta:\n\n"
                    f"{resumen_crudo}\n\n"
                    "Intenta de nuevo en un par de minutos para una respuesta mejor redactada."
                ),
                "confianza": round(confianza, 3),
                "degradado": True,
            }

        return {"respuesta": respuesta.text, "confianza": round(confianza, 3)}

    except genai_errors.ServerError as e:
        print("\n=== GEMINI SOBRECARGADO (503) TRAS REINTENTOS ===")
        traceback.print_exc()
        print("====================================\n")
        return {
            "respuesta": "En este momento el servicio de IA está saturado. "
                         "Por favor intenta de nuevo en unos segundos.",
            "confianza": 0,
        }

    except Exception as e:
        print("\n=== ERROR DETECTADO EN /api/chat ===")
        traceback.print_exc()
        print("====================================\n")
        raise HTTPException(status_code=500, detail=str(e))

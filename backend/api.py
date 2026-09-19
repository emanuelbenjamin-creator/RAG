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

# DIAGNÓSTICO: confirma en los logs si la key realmente llegó al contenedor,
# sin imprimir la key completa. Bórralo una vez resuelto el problema.
print(f"[DEBUG] GEMINI_API_KEY presente: {bool(GEMINI_API_KEY)}, "
      f"longitud: {len(GEMINI_API_KEY) if GEMINI_API_KEY else 0}, "
      f"empieza con: {GEMINI_API_KEY[:6] if GEMINI_API_KEY else 'N/A'}")
print(f"[DEBUG] SUPABASE_KEY presente: {bool(SUPABASE_KEY)}, "
      f"longitud: {len(SUPABASE_KEY) if SUPABASE_KEY else 0}")

if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY]):
    raise SystemExit(
        "[ERROR] Faltan variables de entorno: SUPABASE_URL, SUPABASE_KEY o GEMINI_API_KEY. "
        "Revisa la configuración de Environment variables en Northflank."
    )

# Mismo modelo/dimensión que upload_to_supabase.py — NO cambiar sin reindexar todo
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 1024

# Umbral mínimo de similitud para considerar un chunk "relevante".
MATCH_THRESHOLD = 0.65
MATCH_COUNT = 8

MATCH_COUNT_COMPUESTA = 14
PALABRAS_UMBRAL_COMPUESTA = 25
SIGNOS_INTERROGACION_UMBRAL_COMPUESTA = 2


def es_pregunta_compuesta(pregunta: str) -> bool:
    n_palabras = len(pregunta.split())
    n_signos = pregunta.count("?") + pregunta.count("¿")
    return n_palabras > PALABRAS_UMBRAL_COMPUESTA or n_signos > SIGNOS_INTERROGACION_UMBRAL_COMPUESTA


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


def descomponer_pregunta(pregunta: str) -> list:
    if not es_pregunta_compuesta(pregunta):
        return [pregunta]

    prompt_descomposicion = f"""Divide la siguiente pregunta en sub-preguntas
independientes y autocontenidas, una por cada tema o dato distinto que se
pide. Si la pregunta ya trata un solo tema, devuélvela tal cual, sin dividir.
Responde SOLO con las sub-preguntas, una por línea, sin numerarlas ni
agregar texto adicional.

Pregunta: {pregunta}

Sub-preguntas:"""

    try:
        resp = ai_client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt_descomposicion,
        )
        sub_preguntas = [
            linea.strip("-•* \t0123456789.) ")
            for linea in resp.text.strip().split("\n")
            if linea.strip("-•* \t0123456789.) ")
        ]
        return sub_preguntas if sub_preguntas else [pregunta]
    except Exception:
        return [pregunta]


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


def traer_seccion_completa_vigente(fuente_archivo: str, section_id: str):
    try:
        res = (
            supabase.table("documentos_tributarios")
            .select("id, contenido, metadata")
            .eq("metadata->>fuente_archivo", fuente_archivo)
            .eq("metadata->>section_id", section_id)
            .or_("metadata->>estado.eq.vigente,metadata->>estado.is.null")
            .execute()
        )
        return res.data
    except Exception:
        return []


@app.post("/api/chat")
def responder_consulta(consulta: ConsultaRequest):
    try:
        sub_preguntas = descomponer_pregunta(consulta.pregunta)

        response_data = []
        ids_vistos = set()

        for sub_pregunta in sub_preguntas:
            query_vector = obtener_embedding(sub_pregunta)

            resp_sub = supabase.rpc(
                "match_documentos",
                {
                    "query_embedding": query_vector,
                    "match_threshold": MATCH_THRESHOLD,
                    "match_count": MATCH_COUNT,
                },
            ).execute()

            for d in (resp_sub.data or []):
                if d["id"] not in ids_vistos:
                    ids_vistos.add(d["id"])
                    response_data.append(d)

        if not response_data:
            return {
                "respuesta": "No tengo información cargada sobre esa norma o tema todavía. "
                             "Estoy ampliando la base de conocimiento continuamente."
            }

        chunks_por_id = {d["id"]: d for d in response_data}

        for doc in response_data:
            metadata = doc.get("metadata") or {}
            chunk_id = metadata.get("chunk_id")
            fuente_archivo = metadata.get("fuente_archivo")
            section_id = metadata.get("section_id")
            estado_doc = metadata.get("estado", "vigente")
            if fuente_archivo is None:
                continue

            if section_id:
                for v in traer_seccion_completa_vigente(fuente_archivo, section_id):
                    if v["id"] not in chunks_por_id:
                        chunks_por_id[v["id"]] = v
            elif chunk_id is not None:
                for vecino_id in (chunk_id - 1, chunk_id + 1):
                    try:
                        vecino = (
                            supabase.table("documentos_tributarios")
                            .select("id, contenido, metadata")
                            .eq("metadata->>fuente_archivo", fuente_archivo)
                            .eq("metadata->>chunk_id", str(vecino_id))
                            .or_(
                                f"metadata->>estado.eq.{estado_doc},"
                                f"metadata->>estado.is.null"
                            )
                            .execute()
                        )
                        for v in vecino.data:
                            if v["id"] not in chunks_por_id:
                                chunks_por_id[v["id"]] = v
                    except Exception:
                        pass

        chunks_ordenados = sorted(
            chunks_por_id.values(),
            key=lambda d: (d.get("metadata") or {}).get("chunk_id", 0),
        )

        contexto = "\n\n".join([doc["contenido"] for doc in chunks_ordenados])
        confianza = max((doc.get("similarity", 0) for doc in response_data), default=0)

        fuentes_vistas = set()
        fuentes = []
        for doc in chunks_ordenados:
            m = doc.get("metadata") or {}
            clave = (m.get("fuente"), m.get("categoria"))
            if clave not in fuentes_vistas and m.get("fuente"):
                fuentes_vistas.add(clave)
                fuentes.append({"fuente": m.get("fuente"), "categoria": m.get("categoria")})

        prompt_final = f"""
Eres un asistente que ayuda a contadores peruanos a entender normativa de SUNAT de forma clara, cercana y directa — como una explicación bien hecha, no como un documento legal frío.
Responde a la pregunta del usuario utilizando únicamente la información proporcionada en el contexto.

Toma en cuenta que el texto extraído del PDF puede presentar pequeñas variaciones tipográficas o espaciados irregulares (por ejemplo, "Catálogo No. 14" o "Catálogo N° 14", "e ste", "s e").
Relaciona los códigos de catálogo (como 1001, 1002, 1003) con sus descripciones de montos (operaciones gravadas, exoneradas, inafectas).

REGLA CRÍTICA SOBRE VIGENCIA:
Si el contexto incluye bloques marcados con la frase "TEXTO ANTERIOR", ese contenido es
normativa DEROGADA (ya no aplica). NUNCA la presentes como vigente ni la mezcles con la
norma actual como si fuera una sola regla. Usa el texto derogado únicamente si el usuario
pide explícitamente conocer el historial de cambios o una versión anterior de la norma.
Si tienes dudas sobre si un fragmento es vigente o derogado, dilo explícitamente en tu
respuesta en vez de asumir.

REGLA CRÍTICA SOBRE PREGUNTAS COMPUESTAS:
Si la pregunta del usuario tiene varias partes, responde cada parte por separado y de
forma completa. Si el contexto no contiene información suficiente para responder alguna
de las partes, dilo explícitamente para esa parte en vez de omitirla en silencio.

Reglas de estilo para tu respuesta:
- Estructura la respuesta en secciones claras usando encabezados con ## (por ejemplo: "## ¿Cuándo aplica?", "## Requisitos obligatorios", "## ¿Dónde se tramita?").
- Usa **negrita** para resaltar términos clave, montos, plazos, nombres de normas y conceptos importantes.
- Cuando el contexto tenga una lista de ítems, preséntalos como lista numerada o con viñetas.
- Mantén el tono cercano y natural, sin sonar como un documento legal frío.
- No entrecomilles términos ni definiciones salvo que estés citando el nombre exacto de una norma.
- Si citas el nombre de una norma o resolución, menciónalo de forma natural dentro de la oración.
- Sé completo: no omitas ítems obligatorios del contexto por acortar la respuesta.

Al final de tu respuesta, en una línea nueva, escribe exactamente "---SUGERENCIAS---" y debajo 3 preguntas cortas relacionadas, una por línea, sin numerarlas ni agregar texto extra.

--- CONTEXTO EXTRAÍDO ---
{contexto}
--- FIN CONTEXTO ---

Pregunta del usuario: {consulta.pregunta}
Respuesta:
"""

        MODELOS_CHAIN = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"]

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
                    break
                except genai_errors.ClientError as e:
                    ultimo_error = e
                    es_cuota = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
                    es_no_disponible = (
                        "404" in str(e)
                        or "NOT_FOUND" in str(e)
                        or "no longer available" in str(e)
                    )
                    es_auth = "401" in str(e) or "UNAUTHENTICATED" in str(e)
                    if es_auth:
                        # Un 401 no se arregla probando otro modelo — es la
                        # key/autenticación. Corta aquí y sube el error real.
                        print(f"  [ERROR] {modelo}: fallo de autenticación (401). "
                              f"Revisa GEMINI_API_KEY en las variables de entorno.")
                        raise
                    if es_cuota or es_no_disponible:
                        motivo = "sin cuota (429)" if es_cuota else "ya no disponible (404)"
                        print(f"  [WARN] {modelo} {motivo}. Probando el siguiente modelo...")
                        break
                    raise
            if exito:
                if modelo != MODELOS_CHAIN[0]:
                    print(f"  [INFO] Se usó el modelo de respaldo: {modelo}")
                break

        if respuesta is None:
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
                "fuentes": fuentes,
                "sugerencias": [],
            }

        texto_completo = respuesta.text
        sugerencias = []
        if "---SUGERENCIAS---" in texto_completo:
            partes = texto_completo.split("---SUGERENCIAS---")
            texto_completo = partes[0].strip()
            sugerencias = [
                linea.strip("-•* \t")
                for linea in partes[1].strip().split("\n")
                if linea.strip("-•* \t")
            ][:3]

        return {
            "respuesta": texto_completo,
            "confianza": round(confianza, 3),
            "fuentes": fuentes,
            "sugerencias": sugerencias,
        }

    except genai_errors.ClientError as e:
        if "401" in str(e) or "UNAUTHENTICATED" in str(e):
            print("\n=== FALLO DE AUTENTICACIÓN CON GEMINI (401) ===")
            traceback.print_exc()
            print("====================================\n")
            raise HTTPException(
                status_code=500,
                detail="Error de autenticación con Gemini. Verifica GEMINI_API_KEY en Northflank.",
            )
        print("\n=== ERROR DETECTADO EN /api/chat ===")
        traceback.print_exc()
        print("====================================\n")
        raise HTTPException(status_code=500, detail=str(e))

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

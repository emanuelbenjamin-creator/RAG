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
SUPABASE_KEY = os.getenv("sb_publishable_L9nLEcA3-9rknBAHlP0GOQ_hCqOH-24")
GEMINI_API_KEY = os.getenv("AQ.Ab8RN6Ij-fM1gP1cjjiFpzAD8PdeXhpFd0Z_DtK-qS2uB1fc4A")

# Mismo modelo/dimensión que upload_to_supabase.py — NO cambiar sin reindexar todo
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 1024

# Umbral mínimo de similitud para considerar un chunk "relevante".
# Con match_threshold=0.0 el sistema nunca dice "no lo sé" — ajusta este valor
# probando con preguntas dentro y fuera de tu dominio cargado.
MATCH_THRESHOLD = 0.65
MATCH_COUNT = 8

# NUEVO ----------------------------------------------------------------------
# Preguntas compuestas (piden 2-3 cosas a la vez, o cruzan varios documentos)
# pierden recall con un top_k fijo de 8: los sub-temas más "centrales" ocupan
# casi todos los espacios y el sub-tema periférico queda fuera del umbral.
# Detectamos preguntas largas/con varias interrogantes y les damos más
# espacio de búsqueda. Es un parche de bajo esfuerzo, no reemplaza una
# descomposición real de consultas, pero mitiga el problema sin rearquitectura.
MATCH_COUNT_COMPUESTA = 14
PALABRAS_UMBRAL_COMPUESTA = 25
SIGNOS_INTERROGACION_UMBRAL_COMPUESTA = 2


def es_pregunta_compuesta(pregunta: str) -> bool:
    n_palabras = len(pregunta.split())
    n_signos = pregunta.count("?") + pregunta.count("¿")
    return n_palabras > PALABRAS_UMBRAL_COMPUESTA or n_signos > SIGNOS_INTERROGACION_UMBRAL_COMPUESTA
# ------------------------------------------------------------------------------
# NUEVO ------------------------------------------------------------------
def descomponer_pregunta(pregunta: str) -> list[str]:
    """
    Si la pregunta tiene más de un sub-tema, la parte en sub-preguntas
    independientes usando el propio Gemini (rápido y barato con un modelo
    flash-lite). Cada sub-pregunta se embebe y busca por separado, así un
    sub-tema "periférico" no compite por espacio en el top-k contra un
    sub-tema "dominante" semánticamente más fuerte.
    Si la pregunta es simple (1 solo tema), devuelve una lista con la
    pregunta original sin cambios, para no gastar una llamada extra.
    """
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
        # Si falla la descomposición, seguimos con la pregunta original
        # completa en vez de romper toda la consulta.
        return [pregunta]
# ----------------------------------------------------------------------------
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


# NUEVO ------------------------------------------------------------------
def traer_seccion_completa_vigente(fuente_archivo: str, section_id: str):
    """
    Trae todos los chunks de una misma sección/tabla, pero SOLO los marcados
    como vigentes (o sin el campo 'estado', por compatibilidad con datos
    reingeridos antes de este cambio). Antes esta función traía TODO lo que
    compartiera section_id sin distinguir vigencia, lo que mezclaba texto
    derogado ("TEXTO ANTERIOR") con el vigente en una misma respuesta.
    """
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
# ----------------------------------------------------------------------------


@app.post("/api/chat")
def responder_consulta(consulta: ConsultaRequest):
    try:
        query_vector = obtener_embedding(consulta.pregunta)

        # MODIFICADO: match_count dinámico según complejidad de la pregunta
        match_count_efectivo = (
            MATCH_COUNT_COMPUESTA if es_pregunta_compuesta(consulta.pregunta) else MATCH_COUNT
        )

        response = supabase.rpc(
            "match_documentos",
            {
                "query_embedding": query_vector,
                "match_threshold": MATCH_THRESHOLD,
                "match_count": match_count_efectivo,
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
            section_id = metadata.get("section_id")
            estado_doc = metadata.get("estado", "vigente")  # NUEVO
            if fuente_archivo is None:
                continue

            if section_id:
                # MODIFICADO: usa la nueva función que filtra por vigencia
                for v in traer_seccion_completa_vigente(fuente_archivo, section_id):
                    if v["id"] not in chunks_por_id:
                        chunks_por_id[v["id"]] = v
            elif chunk_id is not None:
                # Prosa normal: solo trae el vecino inmediato anterior/siguiente,
                # por si una idea se corta justo entre dos chunks.
                #
                # NUEVO: solo si el vecino tiene el MISMO estado (vigente/
                # derogado) que el chunk original, para no coser
                # accidentalmente un párrafo vigente con uno derogado.
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

        # Ordenamos por chunk_id para que el contexto se lea en el orden original
        # del documento, no en el orden aleatorio de similitud.
        chunks_ordenados = sorted(
            chunks_por_id.values(),
            key=lambda d: (d.get("metadata") or {}).get("chunk_id", 0),
        )

        contexto = "\n\n".join([doc["contenido"] for doc in chunks_ordenados])
        confianza = max((doc.get("similarity", 0) for doc in response.data), default=0)

        # Lista de fuentes citadas (deduplicada), para mostrar en el frontend
        # de dónde salió la información.
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

REGLA CRÍTICA SOBRE VIGENCIA (NUEVO):
Si el contexto incluye bloques marcados con la frase "TEXTO ANTERIOR", ese contenido es
normativa DEROGADA (ya no aplica). NUNCA la presentes como vigente ni la mezcles con la
norma actual como si fuera una sola regla. Usa el texto derogado únicamente si el usuario
pide explícitamente conocer el historial de cambios o una versión anterior de la norma.
Si tienes dudas sobre si un fragmento es vigente o derogado, dilo explícitamente en tu
respuesta en vez de asumir.

REGLA CRÍTICA SOBRE PREGUNTAS COMPUESTAS (NUEVO):
Si la pregunta del usuario tiene varias partes (por ejemplo, pide dos o tres cosas
distintas a la vez), responde cada parte por separado y de forma completa. Si el contexto
no contiene información suficiente para responder alguna de las partes, dilo explícitamente
para esa parte en vez de omitirla en silencio o responder una pregunta distinta a la que
se te hizo.

Reglas de estilo para tu respuesta:
- Estructura la respuesta en secciones claras usando encabezados con ## (por ejemplo: "## ¿Cuándo aplica?", "## Requisitos obligatorios", "## ¿Dónde se tramita?"). Divide el tema en las preguntas que un contador se haría naturalmente al leerlo.
- Usa **negrita** para resaltar términos clave, montos, plazos, nombres de normas y conceptos importantes dentro del texto.
- Cuando el contexto tenga una lista de ítems (requisitos, campos, pasos), preséntalos como lista numerada o con viñetas — no los conviertas en un párrafo largo.
- Aun con esta estructura, mantén el tono cercano y natural, sin sonar como un documento legal frío.
- No entrecomilles términos ni definiciones salvo que estés citando el nombre exacto de una norma (ej. Ley N° 30057).
- Si citas el nombre de una norma o resolución, menciónalo de forma natural dentro de la oración.
- Sé completo: no omitas ítems obligatorios del contexto por acortar la respuesta.

Al final de tu respuesta, en una línea nueva, escribe exactamente "---SUGERENCIAS---" y debajo 3 preguntas cortas relacionadas que el usuario podría querer hacer a continuación (basadas en el mismo contexto), una por línea, sin numerarlas ni agregar texto extra.

--- CONTEXTO EXTRAÍDO ---
{contexto}
--- FIN CONTEXTO ---

Pregunta del usuario: {consulta.pregunta}
Respuesta:
"""

        # Cadena de modelos vigentes (septiembre 2026). Si alguno está saturado,
        # sin cuota, o Google lo retira, cae automáticamente al siguiente.
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
                    break  # se acabaron los reintentos para este modelo, prueba el siguiente
                except genai_errors.ClientError as e:
                    ultimo_error = e
                    es_cuota = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
                    es_no_disponible = (
                        "404" in str(e)
                        or "NOT_FOUND" in str(e)
                        or "no longer available" in str(e)
                    )
                    if es_cuota or es_no_disponible:
                        # Cuota agotada o el modelo ya no existe/fue retirado por
                        # Google: no tiene caso reintentar, pasa al siguiente.
                        motivo = "sin cuota (429)" if es_cuota else "ya no disponible (404)"
                        print(f"  [WARN] {modelo} {motivo}. Probando el siguiente modelo...")
                        break
                    raise  # otro tipo de error del cliente, no lo escondas
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

import os
import json
import time
import random
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from supabase import create_client
from typesafe_sdk import TypeSafeClient, Noul

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ilvssohttgguxdijhuyo.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY")

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

# Marcador que separa la respuesta de las sugerencias, igual que antes.
# Streaming necesita saber esta cadena para no filtrarla al usuario mientras
# llega en pedazos (ver _procesar_stream_modelo más abajo).
MARCADOR_SUGERENCIAS = "---SUGERENCIAS---"


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

# TypeSafe (Jev) es OPCIONAL a propósito: si TYPESAFE_API_KEY no está seteada,
# el filtro de alcance simplemente no se aplica y todas las preguntas pasan al
# flujo normal (Supabase + Gemini). No queremos que un problema con este
# servicio auxiliar tumbe el asistente principal.
if TYPESAFE_API_KEY:
    typesafe_client = TypeSafeClient()  # lee TYPESAFE_API_KEY del entorno
    print("[DEBUG] TYPESAFE_API_KEY presente: filtro de alcance con Jev activado.")
else:
    typesafe_client = None
    print("[DEBUG] TYPESAFE_API_KEY no configurada: filtro de alcance con Jev desactivado "
          "(todas las preguntas pasan por Supabase/Gemini como antes).")

# Umbral de probabilidad para considerar una pregunta "en alcance". Noul
# devuelve una probabilidad (0 a 1) de que la respuesta sea "sí", no un
# booleano — hay que compararla contra un umbral, no usarla directo como bool.
UMBRAL_EN_ALCANCE = 0.5

TEMAS_EN_ALCANCE = (
    "comprobantes de pago peruanos (facturas, boletas, notas de crédito/débito, "
    "guías de remisión, recibos por honorarios electrónicos, normativa SUNAT de "
    "emisión y requisitos) o sobre impuesto a la renta peruano (categorías de "
    "renta, gastos deducibles, depreciación, pagos a cuenta, retenciones, TUO de "
    "la Ley del Impuesto a la Renta, Código Tributario)"
)

MENSAJE_FUERA_DE_ALCANCE = (
    "Por ahora solo puedo ayudarte con normativa de comprobantes de pago (SUNAT) "
    "e impuesto a la renta. Esa pregunta está fuera de lo que puedo responder todavía."
)


def es_pregunta_fuera_de_alcance(pregunta: str) -> bool:
    """
    Clasifica la pregunta con Jev (TypeSafe) ANTES de tocar Supabase/Gemini,
    para no gastar un embed_content + generate_content en preguntas que de
    entrada no tienen nada que ver con el asistente.

    Si TypeSafe no está configurado o falla por cualquier motivo, se deja
    pasar la pregunta al flujo normal (falla "abierta": un problema acá
    nunca debe bloquear al usuario).
    """
    if typesafe_client is None:
        return False
    try:
        respuesta = typesafe_client.system_one(
            state={"pregunta": pregunta},
            questions={
                "en_alcance": Noul(
                    instructions=(
                        f"¿Esta pregunta trata sobre {TEMAS_EN_ALCANCE}? "
                        "Responde que sí también para preguntas generales o "
                        "introductorias sobre esos dos temas, no solo para "
                        "preguntas muy específicas."
                    ),
                ),
            },
        )
        probabilidad_en_alcance = respuesta.nouls["en_alcance"].noul
        return probabilidad_en_alcance < UMBRAL_EN_ALCANCE
    except Exception as e:
        print(f"  [WARN] TypeSafe (Jev) falló, se deja pasar la pregunta sin filtrar: {e}")
        return False


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


def _construir_contexto(consulta: ConsultaRequest):
    """
    Toda la parte de recuperación (RAG) que antes vivía dentro del endpoint:
    descompone la pregunta, busca en Supabase, expande secciones/vecinos y
    arma el prompt final. Se extrae a su propia función porque ahora el
    endpoint tiene dos caminos (streaming y no-streaming) que la necesitan
    igual. No toca nada de la lógica original, solo la mueve.
    """
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
        return None

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

Al final de tu respuesta, en una línea nueva, escribe exactamente "{MARCADOR_SUGERENCIAS}" y debajo 3 preguntas cortas relacionadas, una por línea, sin numerarlas ni agregar texto extra.

--- CONTEXTO EXTRAÍDO ---
{contexto}
--- FIN CONTEXTO ---

Pregunta del usuario: {consulta.pregunta}
Respuesta:
"""

    return {
        "prompt_final": prompt_final,
        "confianza": confianza,
        "fuentes": fuentes,
        "chunks_ordenados": chunks_ordenados,
    }


MODELOS_CHAIN = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"]


def _sse(tipo: str, data) -> str:
    """Formatea un evento Server-Sent-Events. El frontend debe parsear cada
    línea 'data: {...}' como JSON con un campo 'tipo'."""
    payload = json.dumps({"tipo": tipo, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def _generar_stream_respuesta(consulta: ConsultaRequest):
    """
    Generador que produce eventos SSE a medida que Gemini va escribiendo la
    respuesta. Reemplaza la llamada bloqueante generate_content() por
    generate_content_stream(), pero mantiene el mismo comportamiento de
    fallback entre modelos (MODELOS_CHAIN) y de separación de las
    sugerencias al final.

    Reglas de fallback en streaming (distinto del modo no-streaming):
    - Si un modelo falla ANTES de emitir el primer fragmento de texto al
      cliente, se prueba el siguiente modelo de la cadena, igual que antes.
    - Si un modelo falla DESPUÉS de haber empezado a transmitir texto, ya no
      se puede "reiniciar" limpiamente del lado del cliente (perdería lo que
      ya se mostró), así que se corta ahí y se manda un evento de error.
    """
    if es_pregunta_fuera_de_alcance(consulta.pregunta):
        yield _sse("texto", MENSAJE_FUERA_DE_ALCANCE)
        yield _sse("fin", {"confianza": 0, "fuentes": [], "sugerencias": [], "fuera_de_alcance": True})
        return

    try:
        contexto_data = _construir_contexto(consulta)
    except Exception as e:
        traceback.print_exc()
        yield _sse("error", {"mensaje": str(e)})
        return

    if contexto_data is None:
        yield _sse("texto", "No tengo información cargada sobre esa norma o tema todavía. "
                             "Estoy ampliando la base de conocimiento continuamente.")
        yield _sse("fin", {"confianza": 0, "fuentes": [], "sugerencias": []})
        return

    prompt_final = contexto_data["prompt_final"]
    confianza = contexto_data["confianza"]
    fuentes = contexto_data["fuentes"]
    chunks_ordenados = contexto_data["chunks_ordenados"]

    started_streaming = False
    ultimo_error = None

    for modelo in MODELOS_CHAIN:
        for intento in range(1, 4):
            try:
                stream = ai_client.models.generate_content_stream(
                    model=modelo,
                    contents=prompt_final,
                )

                buffer = ""
                sugerencias_buffer = ""
                in_sugerencias = False
                margen = len(MARCADOR_SUGERENCIAS) - 1

                for chunk in stream:
                    texto = getattr(chunk, "text", None) or ""
                    if not texto:
                        continue

                    started_streaming = True  # ya salió al menos un chunk del modelo

                    if in_sugerencias:
                        sugerencias_buffer += texto
                        continue

                    buffer += texto
                    if MARCADOR_SUGERENCIAS in buffer:
                        idx = buffer.index(MARCADOR_SUGERENCIAS)
                        pre = buffer[:idx]
                        if pre:
                            yield _sse("texto", pre)
                        in_sugerencias = True
                        sugerencias_buffer = buffer[idx + len(MARCADOR_SUGERENCIAS):]
                        buffer = ""
                    else:
                        # Solo se emite lo "seguro": se retiene al final un
                        # colchón del tamaño del marcador por si está partido
                        # entre dos chunks consecutivos del stream.
                        safe_len = len(buffer) - margen
                        if safe_len > 0:
                            yield _sse("texto", buffer[:safe_len])
                            buffer = buffer[safe_len:]

                if buffer and not in_sugerencias:
                    yield _sse("texto", buffer)

                sugerencias = [
                    linea.strip("-•* \t")
                    for linea in sugerencias_buffer.strip().split("\n")
                    if linea.strip("-•* \t")
                ][:3]

                if modelo != MODELOS_CHAIN[0]:
                    print(f"  [INFO] Se usó el modelo de respaldo: {modelo}")

                yield _sse("fin", {
                    "confianza": round(confianza, 3),
                    "fuentes": fuentes,
                    "sugerencias": sugerencias,
                })
                return

            except genai_errors.ClientError as e:
                ultimo_error = e
                if "401" in str(e) or "UNAUTHENTICATED" in str(e):
                    print(f"  [ERROR] {modelo}: fallo de autenticación (401). "
                          f"Revisa GEMINI_API_KEY en las variables de entorno.")
                    yield _sse("error", {"mensaje": "Error de autenticación con Gemini."})
                    return
                if started_streaming:
                    print(f"  [ERROR] {modelo} falló a mitad del streaming: {e}")
                    yield _sse("error", {"mensaje": "Se interrumpió la generación de la respuesta."})
                    return
                es_cuota = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
                es_no_disponible = (
                    "404" in str(e) or "NOT_FOUND" in str(e) or "no longer available" in str(e)
                )
                if es_cuota or es_no_disponible:
                    motivo = "sin cuota (429)" if es_cuota else "ya no disponible (404)"
                    print(f"  [WARN] {modelo} {motivo}. Probando el siguiente modelo...")
                    break  # siguiente modelo de la cadena
                yield _sse("error", {"mensaje": str(e)})
                return

            except genai_errors.ServerError as e:
                ultimo_error = e
                if started_streaming:
                    print(f"  [ERROR] {modelo} se cayó (503) a mitad del streaming: {e}")
                    yield _sse("error", {"mensaje": "El servicio de IA se saturó a mitad de la respuesta."})
                    return
                es_sobrecarga = "503" in str(e) or "UNAVAILABLE" in str(e)
                if es_sobrecarga and intento < 3:
                    espera = (2 ** intento) + random.uniform(0, 1)
                    print(f"  [WARN] {modelo} con alta demanda (503). "
                          f"Reintento {intento}/3 en {espera:.1f}s...")
                    time.sleep(espera)
                    continue
                print(f"  [WARN] {modelo} agotó reintentos por 503. Probando el siguiente modelo...")
                break  # siguiente modelo de la cadena

    # Todos los modelos fallaron y nunca se llegó a transmitir nada:
    # mismo "modo degradado" que la versión no-streaming, pero como evento.
    print(f"  [WARN] Los 3 modelos fallaron. Devolviendo contexto crudo. Último error: {ultimo_error}")
    resumen_crudo = "\n\n".join(doc["contenido"] for doc in chunks_ordenados[:3])
    yield _sse("texto", (
        "El asistente de redacción está saturado en este momento, pero esto es "
        "justo lo que encontré en la normativa cargada sobre tu pregunta:\n\n"
        f"{resumen_crudo}\n\n"
        "Intenta de nuevo en un par de minutos para una respuesta mejor redactada."
    ))
    yield _sse("fin", {
        "confianza": round(confianza, 3),
        "degradado": True,
        "fuentes": fuentes,
        "sugerencias": [],
    })


@app.post("/api/chat/stream")
def responder_consulta_stream(consulta: ConsultaRequest):
    """
    Versión en streaming de /api/chat. Devuelve texto/event-stream: una
    serie de líneas 'data: {"tipo": ..., "data": ...}' donde tipo es
    "texto" (un fragmento más de la respuesta, ir concatenando en el
    frontend), "fin" (evento final con confianza/fuentes/sugerencias) o
    "error" (algo falló; el campo 'mensaje' trae el detalle).

    Se deja /api/chat (no-streaming) intacto abajo para no romper nada que
    ya dependa de la respuesta en un solo JSON.
    """
    return StreamingResponse(
        _generar_stream_respuesta(consulta),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # evita que un proxy (nginx, etc.) bufferice el stream
        },
    )


@app.post("/api/chat")
def responder_consulta(consulta: ConsultaRequest):
    try:
        if es_pregunta_fuera_de_alcance(consulta.pregunta):
            return {"respuesta": MENSAJE_FUERA_DE_ALCANCE, "fuera_de_alcance": True}

        contexto_data = _construir_contexto(consulta)

        if contexto_data is None:
            return {
                "respuesta": "No tengo información cargada sobre esa norma o tema todavía. "
                             "Estoy ampliando la base de conocimiento continuamente."
            }

        prompt_final = contexto_data["prompt_final"]
        confianza = contexto_data["confianza"]
        fuentes = contexto_data["fuentes"]
        chunks_ordenados = contexto_data["chunks_ordenados"]

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
        if MARCADOR_SUGERENCIAS in texto_completo:
            partes = texto_completo.split(MARCADOR_SUGERENCIAS)
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

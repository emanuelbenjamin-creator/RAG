from google import genai
from sentence_transformers import SentenceTransformer
from supabase import create_client

# 1. Configuración de credenciales
SUPABASE_URL = "https://ilvssohttgguxdijhuyo.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlsdnNzb2h0dGdndXhkaWpodXlvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODkwMDkxMDMsImV4cCI6MjEwNDU4NTEwM30.nAj-R9Ij0JXlb0k_78OBil8vZ8TJ0rzt2S24SOiDXB0"  # Clave que inicia en eyJ...
GEMINI_API_KEY = "AIzaSyBBd36hLaisru5qf22cp-dBH2foaKd1aCE"  # Clave que inicia en AIzaSy...

# Inicializar clientes
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# 2. Cargar modelo de embeddings local
embedding_model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")


def responder_consulta(pregunta_usuario: str):
  print(f"\nConsulta: '{pregunta_usuario}'")
  print("1. Buscando contexto relevante en Supabase...")

  # Vectorizar la pregunta
  query_vector = embedding_model.encode(pregunta_usuario).tolist()

  # Recuperar fragmentos desde Supabase
  response = supabase.rpc(
      "match_documentos",
      {
          "query_embedding": query_vector,
          "match_threshold": 0.2,
          "match_count": 3,
      },
  ).execute()

  # Unificar el contexto recuperado
  contexto = "\n\n".join([doc["contenido"] for doc in response.data])

  # Prompt estructurado RAG
  prompt_final = f"""
    Eres un Asistente IA experto en normativa tributaria peruana (SUNAT).
    Responde a la pregunta del usuario únicamente basándote en la siguiente información de referencia:

    --- CONTEXTO EXTRAÍDO ---
    {contexto}
    --- FIN CONTEXTO ---

    Pregunta del usuario: {pregunta_usuario}
    Respuesta clara y precisa:
    """

  print("2. Generando respuesta con la IA...")
  respuesta = ai_client.models.generate_content(
      model="gemini-3.6-flash", contents=prompt_final # <--- Modelo actualizado aquí
  )

  print("\n================ RESPUESTA DEL ASISTENTE ================")
  print(respuesta.text)


# Prueba del flujo completo
if __name__ == "__main__":
  pregunta = "¿En una guia de elaboración XML que es un estandar UBL?"
  responder_consulta(pregunta)
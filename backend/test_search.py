from sentence_transformers import SentenceTransformer
from supabase import create_client

# Credenciales de Supabase
SUPABASE_URL = "https://ilvssohttgguxdijhuyo.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlsdnNzb2h0dGdndXhkaWpodXlvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODkwMDkxMDMsImV4cCI6MjEwNDU4NTEwM30.nAj-R9Ij0JXlb0k_78OBil8vZ8TJ0rzt2S24SOiDXB0" # Pegar la clave completa que inicia en eyJ...

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Cargar modelo de embeddings (ligero para consultas)
model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

# Pregunta de prueba
pregunta = "¿Qué campos son obligatorios en la estructura de la factura electrónica?"
print(f"Pregunta: {pregunta}\nGenerando embedding de la consulta...")

query_vector = model.encode(pregunta).tolist()

# Búsqueda por similitud en la base de datos
response = supabase.rpc(
    "match_documentos", 
    {
        "query_embedding": query_vector,
        "match_threshold": 0.2,
        "match_count": 3
    }
).execute()

print("\n--- RESULTADOS RELEVANTES ENCONTRADOS ---")
for idx, doc in enumerate(response.data, start=1):
    print(f"\nResultado {idx} (Similitud: {doc['similarity']:.4f}):")
    print(f"Contenido: {doc['contenido']}")
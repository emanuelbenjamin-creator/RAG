from sentence_transformers import SentenceTransformer

print("Cargando el modelo Qwen3-Embedding-0.6B...")

# 1. Descargamos y cargamos el modelo desde Hugging Face
model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

# 2. Definimos una pregunta tributaria de prueba
texto_prueba = "¿Qué datos debe contener una factura electrónica de SUNAT?"

print("\nGenerando el vector (embedding) para el texto...")
# 3. Transformamos el texto en números
embedding = model.encode(texto_prueba)

# 4. Mostramos el resultado en la terminal
print("\n--- ¡ÉXITO! ---")
print(f"Texto original: '{texto_prueba}'")
print(f"Tamaño del vector (dimensiones): {len(embedding)}")
print(f"Primeros 5 números del vector: {embedding[:5]}")
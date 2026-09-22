import os
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

archivos = ["documento_prueba.pdf", "imp (1).pdf", "imp (2).pdf", "imp (3).pdf"]
for archivo in archivos:
    total = supabase.table("documentos_tributarios").select("id", count="exact") \
        .eq("metadata->>fuente_archivo", archivo).execute()
    con_seccion = supabase.table("documentos_tributarios").select("id", count="exact") \
        .eq("metadata->>fuente_archivo", archivo) \
        .not_.is_("metadata->>section_id", "null").execute()
    print(f"{archivo}: {total.count} chunks totales, {con_seccion.count} con section_id")

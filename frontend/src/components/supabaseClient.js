import { createClient } from '@supabase/supabase-js';

// CAMBIO: cliente de Supabase para el FRONTEND. Usa la ANON KEY (pública,
// segura de exponer en el navegador) — NUNCA la SUPABASE_KEY de service-role
// que usa tu backend en api.py, esa jamás debe estar en el frontend.
//
// Reemplaza estos dos valores con los tuyos (Settings -> API en el
// dashboard de Supabase). Si tu proyecto tiene soporte para variables de
// entorno (.env), mejor usa import.meta.env.VITE_SUPABASE_URL (Vite) o
// process.env.REACT_APP_SUPABASE_URL (Create React App) en vez de pegarlos
// directo aquí.
const SUPABASE_URL = 'https://ekjuoqxmrxrezvcwfnwl.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_sGs1rRqRPpLh7-7WrSdZGw_fLCj5_o0';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

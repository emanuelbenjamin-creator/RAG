import React, { useState } from 'react';
import { supabase } from './supabaseClient';

// Pantalla de login / registro. Se muestra cuando no hay sesión activa.
// Reutiliza la misma paleta de colores que ChatTributario para que no se
// sienta como una pantalla aparte.
export default function Auth() {
  const [modo, setModo] = useState('login'); // 'login' | 'registro'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [cargando, setCargando] = useState(false);
  const [mensaje, setMensaje] = useState(null); // { tipo: 'error'|'info', texto }

  const conGoogle = async () => {
    setCargando(true);
    setMensaje(null);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: window.location.origin },
    });
    if (error) {
      setMensaje({ tipo: 'error', texto: error.message });
      setCargando(false);
    }
    // Si no hay error, Supabase redirige a Google automáticamente.
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setCargando(true);
    setMensaje(null);

    if (modo === 'login') {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) setMensaje({ tipo: 'error', texto: error.message });
    } else {
      const { error } = await supabase.auth.signUp({ email, password });
      if (error) {
        setMensaje({ tipo: 'error', texto: error.message });
      } else {
        setMensaje({
          tipo: 'info',
          texto: 'Cuenta creada. Si tu proyecto exige confirmación por correo, revisa tu bandeja de entrada antes de ingresar.',
        });
      }
    }
    setCargando(false);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#EEFBF5] px-4">
      <div className="w-full max-w-sm bg-white rounded-3xl shadow-sm border border-[#E5EFE9] p-6">
        <div className="flex items-center gap-2 mb-6">
          <div className="w-9 h-9 rounded-xl bg-[#2EB37C] flex items-center justify-center text-white font-bold text-sm">
            AT
          </div>
          <span className="font-semibold text-[#0F2A1D]">Asistente Tributario</span>
        </div>

        <h1 className="text-lg font-semibold text-[#0F2A1D] mb-1">
          {modo === 'login' ? 'Inicia sesión' : 'Crea tu cuenta'}
        </h1>
        <p className="text-sm text-[#6B7280] mb-5">
          {modo === 'login'
            ? 'Ingresa para usar el asistente.'
            : 'Regístrate para empezar a usar el asistente.'}
        </p>

        <button
          onClick={conGoogle}
          disabled={cargando}
          className="w-full flex items-center justify-center gap-2 border border-[#E5EFE9] rounded-2xl py-2.5 mb-4 text-sm font-medium text-[#374151] hover:bg-[#F3FAF6] disabled:opacity-50 transition-colors"
        >
          <svg width="18" height="18" viewBox="0 0 48 48">
            <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.9 32.6 29.4 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.2-.1-2.4-.4-3.5z"/>
            <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.5 15.9 18.9 13 24 13c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
            <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.1 35.6 26.7 36.5 24 36.5c-5.3 0-9.8-3.4-11.4-8.1l-6.5 5C9.6 39.6 16.3 44 24 44z"/>
            <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.7 2-2 3.7-3.6 4.9l6.2 5.2C39.9 36.2 44 30.7 44 24c0-1.2-.1-2.4-.4-3.5z"/>
          </svg>
          Continuar con Google
        </button>

        <div className="flex items-center gap-3 mb-4">
          <div className="flex-1 h-px bg-[#E5EFE9]" />
          <span className="text-xs text-[#9CA8A1]">o con tu correo</span>
          <div className="flex-1 h-px bg-[#E5EFE9]" />
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="email"
            required
            placeholder="Correo electrónico"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full border border-[#E5EFE9] rounded-2xl px-4 py-2.5 text-sm outline-none focus:border-[#2EB37C]/60"
          />
          <input
            type="password"
            required
            minLength={6}
            placeholder="Contraseña"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full border border-[#E5EFE9] rounded-2xl px-4 py-2.5 text-sm outline-none focus:border-[#2EB37C]/60"
          />

          {mensaje && (
            <p className={`text-sm ${mensaje.tipo === 'error' ? 'text-[#C0523F]' : 'text-[#2E8F63]'}`}>
              {mensaje.texto}
            </p>
          )}

          <button
            type="submit"
            disabled={cargando}
            className="w-full bg-[#2EB37C] hover:bg-[#29A06F] disabled:opacity-50 text-white font-medium py-2.5 rounded-2xl transition-colors"
          >
            {cargando ? 'Un momento...' : modo === 'login' ? 'Ingresar' : 'Crear cuenta'}
          </button>
        </form>

        <p className="text-sm text-center text-[#6B7280] mt-5">
          {modo === 'login' ? '¿No tienes cuenta? ' : '¿Ya tienes cuenta? '}
          <button
            onClick={() => { setModo(modo === 'login' ? 'registro' : 'login'); setMensaje(null); }}
            className="text-[#2EB37C] font-medium hover:underline"
          >
            {modo === 'login' ? 'Regístrate' : 'Inicia sesión'}
          </button>
        </p>
      </div>
    </div>
  );
}

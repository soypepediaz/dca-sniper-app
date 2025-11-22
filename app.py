import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import datetime
from calendar import monthrange

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Simulador DCA Pro: Target LTV",
    page_icon="🧠",
    layout="wide"
)

st.title("🧠 Simulador DCA Institucional: Target LTV & Gestión de Riesgo")
st.markdown("""
Esta estrategia gestiona el **LTV Global del Portafolio**. No se apalanca por compra, sino que ajusta la deuda total para mantener un % de riesgo objetivo según la caída del mercado.
""")

# ==========================================
# 🎛️ PANEL DE CONTROL (SIDEBAR)
# ==========================================

st.sidebar.header("1. Configuración General")
TICKER = st.sidebar.text_input("Ticker", value="BTC-USD")
FECHA_INICIO = st.sidebar.date_input("Fecha Inicio", value=datetime.date(2021, 10, 1))
INVERSION_INICIAL = st.sidebar.number_input("Inversión Inicial ($)", value=1000)
COSTE_DEUDA_APR = st.sidebar.number_input("Coste Deuda (APR %)", value=5.0) / 100

# --- FRECUENCIA Y APORTACIONES ---
st.sidebar.header("2. Aportaciones Periódicas")
FRECUENCIA = st.sidebar.selectbox("Frecuencia", ["Semanal", "Mensual"])

if FRECUENCIA == "Semanal":
    DIA_SEMANA = st.sidebar.selectbox("Día de la semana", 
                                      ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"], index=0)
    mapa_dias = {"Lunes":0, "Martes":1, "Miércoles":2, "Jueves":3, "Viernes":4, "Sábado":5, "Domingo":6}
    DIA_SEMANA_IDX = mapa_dias[DIA_SEMANA]
else:
    DIA_MES = st.sidebar.slider("Día del mes", 1, 31, 1, help="Si el mes tiene menos días, se usará el último día del mes.")

APORTACION_BASE = st.sidebar.number_input("Aportación Base ($)", value=50)
UMBRAL_INICIO_DCA = st.sidebar.slider("Iniciar DCA tras Drawdown > (%)", 0.05, 0.50, 0.15)

# --- APALANCAMIENTO (TARGET LTV) ---
st.sidebar.header("3. Estrategia de Apalancamiento")
st.sidebar.info("Estos valores definen el % de Deuda sobre el Total del Portafolio.")

TARGET_LTV_BASE = st.sidebar.slider("Target LTV Base (%)", 0.0, 0.50, 0.25)
TARGET_LTV_AGRESIVO = st.sidebar.slider("Target LTV Agresivo (%)", 0.0, 0.60, 0.40)
UMBRAL_DD_AGRESIVO = st.sidebar.slider("Activar Agresivo si DD > (%)", 0.10, 0.50, 0.30)

# --- SEGURIDAD ---
st.sidebar.header("4. Filtros de Seguridad (Safe Mode)")
st.sidebar.markdown("Se usa apalancamiento 0 (compra cash) si:")
UMBRAL_DD_SAFE = st.sidebar.slider("Drawdown es menor a (%)", 0.0, 0.10, 0.05)
UMBRAL_LTV_SAFE = st.sidebar.slider("LTV Actual supera el (%)", 0.10, 0.60, 0.40)

# --- DEFENSA Y LIQUIDACIÓN ---
st.sidebar.header("5. Defensa y Liquidación")
LIQ_THRESHOLD = st.sidebar.number_input("Liquidation Threshold (%)", value=75.0) / 100
PCT_UMBRAL_DEFENSA = st.sidebar.slider("Activar Defensa al % del Liq. Threshold", 0.50, 0.95, 0.80)
# Calculamos el LTV trigger real (ej: 80% de 75% = 60%)
TRIGGER_DEFENSA_LTV = LIQ_THRESHOLD * PCT_UMBRAL_DEFENSA
MULTIPLO_DEFENSA = st.sidebar.number_input("Multiplicador Aportación en Defensa", value=2.0)

# --- EXTRAORDINARIAS ---
st.sidebar.header("6. Aportaciones Extraordinarias")
UMBRAL_DD_EXTRA = st.sidebar.slider("Aportar Extra si DD > (%)", 0.30, 0.90, 0.60)
MONTO_EXTRA = st.sidebar.number_input("Monto Extra ($)", value=100)

# ==========================================
# ⚙️ FUNCIONES AUXILIARES
# ==========================================

@st.cache_data
def descargar_datos(ticker, inicio):
    data = yf.download(ticker, start=inicio, progress=False)['Close']
    if isinstance(data, pd.DataFrame): 
        data = data.squeeze()
    data = data.asfreq('D', method='ffill')
    return data

def es_dia_de_compra(fecha, frecuencia, dia_semana_idx, dia_mes_target):
    """Determina si hoy toca comprar según la configuración compleja de fechas."""
    if frecuencia == "Semanal":
        return fecha.dayofweek == dia_semana_idx
    else:
        # Lógica Mensual Inteligente
        # Obtenemos el último día de este mes en concreto
        _, ultimo_dia_mes = monthrange(fecha.year, fecha.month)
        # El día objetivo es el elegido por el usuario O el último día posible
        target = min(dia_mes_target, ultimo_dia_mes)
        return fecha.day == target

def calcular_deuda_para_target_ltv(colateral_actual, deuda_actual, aportacion_cash, target_ltv):
    """
    Calcula cuánta deuda NUEVA tomar para que el LTV global sea igual al Target.
    Fórmula: (Deuda_Vieja + Deuda_Nueva) / (Colateral_Viejo + Cash + Deuda_Nueva) = TargetLTV
    """
    # Despejando Deuda_Nueva (D_new):
    # Target * (C_old + Cash + D_new) = D_old + D_new
    # Target*C_old + Target*Cash - D_old = D_new * (1 - Target)
    
    numerador = target_ltv * (colateral_actual + aportacion_cash) - deuda_actual
    denominador = 1 - target_ltv
    
    if denominador == 0: return 0
    deuda_necesaria = numerador / denominador
    
    # Si sale negativa, significa que ya estamos por encima del target LTV.
    # En esta estrategia, NO repagamos deuda automáticamente, solo no tomamos nueva.
    return max(0, deuda_necesaria)

# ==========================================
# 🚀 MOTOR DE SIMULACIÓN
# ==========================================

if st.sidebar.button("EJECUTAR SIMULACIÓN", type="primary"):
    
    with st.spinner('Procesando lógica institucional...'):
        # 1. Datos
        data = descargar_datos(TICKER, FECHA_INICIO)
        fechas = data.index
        precios = data.values
        
        # 2. Estado Inicial
        btc_acumulado = 0.0
        deuda_acumulada = 0.0
        dinero_invertido = 0.0
        intereses_pagados = 0.0
        
        estrategia_activa_dca = False # El DCA periódico espera al trigger
        compra_inicial_hecha = False
        pico_precio = 0.0
        
        historia = {
            'Fecha': [], 'Equity': [], 'LTV': [], 'Drawdown': [], 
            'Evento': [], 'Cash_Flow': [], 'Deuda_Flow': []
        }
        registros = []
        liquidado = False
        fecha_liq = None

        for i, fecha in enumerate(fechas):
            precio = precios[i]
            
            # --- A. CÁLCULOS BÁSICOS DIARIOS ---
            
            # 1. Interés Compuesto
            if deuda_acumulada > 0:
                interes = deuda_acumulada * (COSTE_DEUDA_APR / 365.0)
                deuda_acumulada += interes
                intereses_pagados += interes
            
            # 2. Drawdown
            if precio > pico_precio: pico_precio = precio
            dd = 0.0
            if pico_precio > 0: dd = (pico_precio - precio) / pico_precio
            
            # 3. Trigger Activación DCA (Solo la primera vez)
            if not estrategia_activa_dca and dd >= UMBRAL_INICIO_DCA:
                estrategia_activa_dca = True
            
            # 4. Valoración y LTV
            colateral_total = btc_acumulado * precio
            ltv = 0.0
            if colateral_total > 0: ltv = deuda_acumulada / colateral_total
            
            # 5. LIQUIDACIÓN CHECK
            if ltv >= LIQ_THRESHOLD:
                liquidado = True
                fecha_liq = fecha
                historia['Fecha'].append(fecha)
                historia['Equity'].append(0)
                historia['LTV'].append(ltv)
                historia['Drawdown'].append(dd)
                historia['Evento'].append("💀 LIQ")
                historia['Cash_Flow'].append(0)
                historia['Deuda_Flow'].append(0)
                registros.append({'Fecha': fecha, 'Tipo': 'LIQUIDACIÓN', 'LTV': ltv})
                break
            
            # --- B. OPERATIVA DE COMPRA ---
            
            cash_a_invertir = 0.0
            deuda_a_tomar = 0.0
            tipo_evento = None # Para gráfica
            etiqueta_tabla = ""
            
            # CASO 0: COMPRA INICIAL (Día 1, sin filtros)
            if not compra_inicial_hecha:
                cash_a_invertir = INVERSION_INICIAL
                # Asumimos compra inicial SIN deuda para empezar sanos, o usuario podría querer parametrizarlo. 
                # Por seguridad y lógica estándar: Initial = Equity puro.
                deuda_a_tomar = 0 
                compra_inicial_hecha = True
                tipo_evento = "INICIO"
                etiqueta_tabla = "Inversión Inicial"
            
            # CASO X: COMPRAS PERIÓDICAS
            elif estrategia_activa_dca and es_dia_de_compra(fecha, FRECUENCIA, locals().get('DIA_SEMANA_IDX'), locals().get('DIA_MES')):
                
                # 1. Definir Monto Base (Cash)
                cash_base = APORTACION_BASE
                
                # Chequeo Extraordinario (Nivel 2)
                es_extra = False
                if dd > UMBRAL_DD_EXTRA:
                    cash_base += MONTO_EXTRA
                    es_extra = True
                
                # Chequeo Defensa Crítica (Nivel 1) - Prioritario sobre todo
                if ltv > TRIGGER_DEFENSA_LTV:
                    cash_a_invertir = cash_base * MULTIPLO_DEFENSA
                    target_ltv_hoy = 0.0 # No tomar deuda
                    tipo_evento = "DEFENSA"
                    etiqueta_tabla = f"🛡️ Defensa (LTV > {TRIGGER_DEFENSA_LTV*100:.0f}%)"
                
                else:
                    cash_a_invertir = cash_base
                    
                    # Decidir Target LTV según zona
                    if dd < UMBRAL_DD_SAFE or ltv > UMBRAL_LTV_SAFE:
                        target_ltv_hoy = 0.0 # Safe Mode
                        tipo_evento = "SAFE"
                        etiqueta_tabla = "✅ Safe Mode"
                    elif dd > UMBRAL_DD_AGRESIVO:
                        target_ltv_hoy = TARGET_LTV_AGRESIVO # Agresivo
                        tipo_evento = "AGRESIVO"
                        etiqueta_tabla = f"🔥 Agresivo (Target {target_ltv_hoy*100:.0f}%)"
                    else:
                        target_ltv_hoy = TARGET_LTV_BASE # Base
                        tipo_evento = "BASE"
                        etiqueta_tabla = f"⚖️ Base (Target {target_ltv_hoy*100:.0f}%)"
                    
                    if es_extra:
                        tipo_evento += "+EXTRA"
                        etiqueta_tabla += " + 💰 Extra"

                # 2. Calcular Deuda necesaria para alcanzar Target LTV Global
                # Solo pedimos deuda si no estamos en modo defensa/safe (donde target es 0)
                if target_ltv_hoy > 0:
                    deuda_a_tomar = calcular_deuda_para_target_ltv(colateral_total, deuda_acumulada, cash_a_invertir, target_ltv_hoy)
                else:
                    deuda_a_tomar = 0

            # --- C. EJECUCIÓN ---
            
            if cash_a_invertir > 0:
                total_compra = cash_a_invertir + deuda_a_tomar
                btc_comprado = total_compra / precio
                
                btc_acumulado += btc_comprado
                deuda_acumulada += deuda_a_tomar
                dinero_invertido += cash_a_invertir
                
                # Registro Tabla
                val_post = btc_acumulado * precio
                ltv_post = deuda_acumulada / val_post
                
                registros.append({
                    'Fecha': fecha.strftime('%Y-%m-%d'),
                    'Precio': precio,
                    'Tipo': etiqueta_tabla,
                    'Cash ($)': cash_a_invertir,
                    'Deuda Nueva ($)': deuda_a_tomar,
                    'LTV Pre (%)': ltv * 100,
                    'LTV Post (%)': ltv_post * 100,
                    'DD (%)': dd * 100
                })
            
            # --- D. GUARDAR HISTORIA DIARIA ---
            historia['Fecha'].append(fecha)
            historia['Equity'].append((btc_acumulado * precio) - deuda_acumulada)
            historia['LTV'].append(ltv)
            historia['Drawdown'].append(dd)
            historia['Evento'].append(tipo_evento) # Puede ser None
            historia['Cash_Flow'].append(cash_a_invertir)
            historia['Deuda_Flow'].append(deuda_a_tomar)

        # DATAFRAMES
        df = pd.DataFrame(historia).set_index('Fecha')
        df_reg = pd.DataFrame(registros)
        
        # ==========================================
        # 📊 RESULTADOS
        # ==========================================
        
        st.divider()
        
        # MÉTRICAS
        val_final = 0 if liquidado else df['Equity'].iloc[-1]
        roi = -100 if liquidado else ((val_final - dinero_invertido) / dinero_invertido) * 100
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Valor Neto Final", f"${val_final:,.2f}", delta=f"{roi:.2f}% ROI")
        col2.metric("Inversión Bolsillo", f"${dinero_invertido:,.0f}")
        col3.metric("Deuda Total", f"${deuda_acumulada:,.2f}")
        col4.metric("Coste Intereses", f"${intereses_pagados:,.2f}", help="Dinero perdido en intereses")
        
        if liquidado:
            st.error(f"☠️ ESTRATEGIA LIQUIDADA EL {fecha_liq.strftime('%Y-%m-%d')}. El LTV superó el {LIQ_THRESHOLD*100}%")

        # GRÁFICOS
        tab1, tab2 = st.tabs(["Gráficos de Análisis", "Tabla de Operaciones"])
        
        with tab1:
            fig, axes = plt.subplots(3, 1, figsize=(12, 16), sharex=True)
            
            # 1. Equity
            axes[0].set_title("1. Evolución del Valor Neto (Equity)", fontweight='bold')
            axes[0].plot(df.index, df['Equity'], color='#1f77b4', linewidth=1.5, label='Valor Neto')
            axes[0].fill_between(df.index, df['Equity'], 0, alpha=0.1, color='#1f77b4')
            axes[0].legend()
            axes[0].grid(True, alpha=0.3)
            
            # 2. Decisiones (Scatter)
            axes[1].set_title("2. Mapa de Decisiones sobre Drawdown", fontweight='bold')
            axes[1].plot(df.index, df['Drawdown']*-100, color='black', alpha=0.3, label='Drawdown Mercado')
            
            # Filtrar eventos para scatter
            # Inicio
            evt_ini = df[df['Evento'] == "INICIO"]
            axes[1].scatter(evt_ini.index, [-5]*len(evt_ini), marker='*', s=150, color='gold', edgecolors='black', label='Inicio', zorder=10)
            
            # Defensa
            evt_def = df[df['Evento'] == "DEFENSA"]
            axes[1].scatter(evt_def.index, [-25]*len(evt_def), marker='s', s=80, color='red', label='Defensa', zorder=5)
            
            # Agresivo
            evt_agg = df[df['Evento'].str.contains("AGRESIVO", na=False)]
            axes[1].scatter(evt_agg.index, [-15]*len(evt_agg), marker='^', s=60, color='purple', label='Agresivo', zorder=4)
            
            # Base
            evt_base = df[df['Evento'].str.contains("BASE", na=False)]
            axes[1].scatter(evt_base.index, [-10]*len(evt_base), marker='o', s=30, color='cyan', label='Base', zorder=3)
            
            # Safe
            evt_safe = df[df['Evento'].str.contains("SAFE", na=False)]
            axes[1].scatter(evt_safe.index, [-2]*len(evt_safe), marker='.', s=50, color='green', label='Safe', zorder=3)

            axes[1].set_ylabel("Drawdown (%)")
            axes[1].legend(loc='lower left', ncol=3)
            axes[1].grid(True, alpha=0.3)
            
            # 3. LTV
            axes[2].set_title("3. Gestión del LTV", fontweight='bold')
            axes[2].plot(df.index, df['LTV']*100, color='orange', label='LTV Real')
            axes[2].axhline(LIQ_THRESHOLD*100, color='red', linestyle='--', label='Liquidación')
            axes[2].axhline(TRIGGER_DEFENSA_LTV*100, color='brown', linestyle=':', label='Trigger Defensa')
            axes[2].axhline(UMBRAL_LTV_SAFE*100, color='green', linestyle=':', label='Límite Safe')
            axes[2].set_ylabel("LTV (%)")
            axes[2].set_ylim(0, 100)
            axes[2].legend(loc='upper left')
            axes[2].grid(True, alpha=0.3)
            
            st.pyplot(fig)
            
        with tab2:
            st.dataframe(df_reg)
            csv = df_reg.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Descargar CSV", data=csv, file_name='simulacion_ltv_target.csv', mime='text/csv')

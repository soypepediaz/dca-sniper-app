import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import datetime
from calendar import monthrange

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Simulador DCA Pro: Strategy vs Benchmark",
    page_icon="⚖️",
    layout="wide"
)

st.title("⚖️ Simulador: Target LTV Strategy vs DCA Benchmark")
st.markdown("""
Comparativa directa entre una **Estrategia de Gestión Activa (Target LTV)** y un **DCA Estándar (Pasivo)**.
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
    DIA_MES = st.sidebar.slider("Día del mes", 1, 31, 1)

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
    if frecuencia == "Semanal":
        return fecha.dayofweek == dia_semana_idx
    else:
        _, ultimo_dia_mes = monthrange(fecha.year, fecha.month)
        target = min(dia_mes_target, ultimo_dia_mes)
        return fecha.day == target

def calcular_deuda_para_target_ltv(colateral_actual, deuda_actual, aportacion_cash, target_ltv):
    numerador = target_ltv * (colateral_actual + aportacion_cash) - deuda_actual
    denominador = 1 - target_ltv
    if denominador == 0: return 0
    deuda_necesaria = numerador / denominador
    return max(0, deuda_necesaria)

def calcular_cagr(valor_final, valor_inicial, dias):
    if valor_inicial == 0 or valor_final <= 0 or dias <= 0: return 0.0
    anyos = dias / 365.25
    return (valor_final / valor_inicial) ** (1 / anyos) - 1

# ==========================================
# 🚀 MOTOR DE SIMULACIÓN
# ==========================================

if st.sidebar.button("EJECUTAR SIMULACIÓN", type="primary"):
    
    with st.spinner('Simulando Estrategia vs Benchmark...'):
        # 1. Datos
        data = descargar_datos(TICKER, FECHA_INICIO)
        fechas = data.index
        precios = data.values
        
        # --- ESTADO ESTRATEGIA (ACTIVA) ---
        btc_acumulado = 0.0
        deuda_acumulada = 0.0
        dinero_invertido = 0.0
        intereses_pagados = 0.0
        estrategia_activa_dca = False 
        compra_inicial_hecha = False
        
        # --- ESTADO BENCHMARK (PASIVA) ---
        bench_btc = 0.0
        bench_invertido = 0.0
        bench_compra_inicial_hecha = False
        
        # --- GENERAL ---
        pico_precio = 0.0
        historia = {
            'Fecha': [], 
            'Equity_Strat': [], 'LTV': [], 'Drawdown': [], 'Evento': [],
            'Equity_Bench': []
        }
        registros = []
        liquidado = False
        fecha_liq = None

        for i, fecha in enumerate(fechas):
            precio = precios[i]
            
            # --- 1. ACTUALIZACIONES DIARIAS ---
            
            # Interés Compuesto (Solo Estrategia)
            if deuda_acumulada > 0:
                interes = deuda_acumulada * (COSTE_DEUDA_APR / 365.0)
                deuda_acumulada += interes
                intereses_pagados += interes
            
            # Drawdown
            if precio > pico_precio: pico_precio = precio
            dd = 0.0
            if pico_precio > 0: dd = (pico_precio - precio) / pico_precio
            
            # Trigger Activación DCA Estrategia
            if not estrategia_activa_dca and dd >= UMBRAL_INICIO_DCA:
                estrategia_activa_dca = True
            
            # Valoración y LTV Estrategia
            colateral_total = btc_acumulado * precio
            ltv = 0.0
            if colateral_total > 0: ltv = deuda_acumulada / colateral_total
            
            # Liquidación Check
            if ltv >= LIQ_THRESHOLD:
                liquidado = True
                fecha_liq = fecha
                historia['Fecha'].append(fecha)
                historia['Equity_Strat'].append(0)
                historia['Equity_Bench'].append(bench_btc * precio) # El bench sigue vivo
                historia['LTV'].append(ltv)
                historia['Drawdown'].append(dd)
                historia['Evento'].append("💀 LIQ")
                registros.append({'Fecha': fecha, 'Tipo': 'LIQUIDACIÓN', 'LTV': ltv})
                break
            
            # --- 2. OPERATIVA DE COMPRA ---
            
            # A) INICIO (Día 1)
            # Para que la comparación sea justa, ambos invierten el capital inicial el mismo día
            if i == 0: 
                # Estrategia
                btc_acumulado += INVERSION_INICIAL / precio
                dinero_invertido += INVERSION_INICIAL
                compra_inicial_hecha = True
                
                # Benchmark (Compra Inicial)
                bench_btc += INVERSION_INICIAL / precio
                bench_invertido += INVERSION_INICIAL
                bench_compra_inicial_hecha = True
                
                tipo_evento = "INICIO"
                etiqueta_tabla = "Inversión Inicial"
                
                registros.append({
                    'Fecha': fecha.strftime('%Y-%m-%d'),
                    'Precio': precio,
                    'Tipo': "INICIO",
                    'Cash ($)': INVERSION_INICIAL,
                    'Deuda Nueva ($)': 0,
                    'LTV Post (%)': 0,
                    'DD (%)': dd * 100
                })
            
            # B) COMPRAS PERIÓDICAS
            elif es_dia_de_compra(fecha, FRECUENCIA, locals().get('DIA_SEMANA_IDX'), locals().get('DIA_MES')):
                
                # --- BENCHMARK (Siempre compra Base) ---
                bench_btc += APORTACION_BASE / precio
                bench_invertido += APORTACION_BASE
                
                # --- ESTRATEGIA (Solo si activada) ---
                if estrategia_activa_dca:
                    
                    cash_base = APORTACION_BASE
                    cash_a_invertir = 0.0
                    deuda_a_tomar = 0.0
                    
                    # Chequeo Extra
                    es_extra = False
                    if dd > UMBRAL_DD_EXTRA:
                        cash_base += MONTO_EXTRA
                        es_extra = True
                    
                    # Chequeo Defensa
                    if ltv > TRIGGER_DEFENSA_LTV:
                        cash_a_invertir = cash_base * MULTIPLO_DEFENSA
                        target_ltv_hoy = 0.0 
                        tipo_evento = "DEFENSA"
                        etiqueta_tabla = f"🛡️ Defensa"
                    else:
                        cash_a_invertir = cash_base
                        # Target LTV
                        if dd < UMBRAL_DD_SAFE or ltv > UMBRAL_LTV_SAFE:
                            target_ltv_hoy = 0.0 
                            tipo_evento = "SAFE"
                            etiqueta_tabla = "✅ Safe"
                        elif dd > UMBRAL_DD_AGRESIVO:
                            target_ltv_hoy = TARGET_LTV_AGRESIVO
                            tipo_evento = "AGRESIVO"
                            etiqueta_tabla = f"🔥 Agresivo"
                        else:
                            target_ltv_hoy = TARGET_LTV_BASE
                            tipo_evento = "BASE"
                            etiqueta_tabla = f"⚖️ Base"
                        
                        if es_extra:
                            tipo_evento += "+EXTRA"
                            etiqueta_tabla += " + Extra"

                    # Calcular Deuda
                    if target_ltv_hoy > 0:
                        deuda_a_tomar = calcular_deuda_para_target_ltv(colateral_total, deuda_acumulada, cash_a_invertir, target_ltv_hoy)
                    else:
                        deuda_a_tomar = 0
                    
                    # Ejecutar Estrategia
                    total_compra = cash_a_invertir + deuda_a_tomar
                    btc_acumulado += total_compra / precio
                    deuda_acumulada += deuda_a_tomar
                    dinero_invertido += cash_a_invertir
                    
                    # Registro
                    val_post = btc_acumulado * precio
                    ltv_post = deuda_acumulada / val_post
                    
                    registros.append({
                        'Fecha': fecha.strftime('%Y-%m-%d'),
                        'Precio': precio,
                        'Tipo': etiqueta_tabla,
                        'Cash ($)': cash_a_invertir,
                        'Deuda Nueva ($)': deuda_a_tomar,
                        'LTV Post (%)

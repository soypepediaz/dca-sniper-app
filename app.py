import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import datetime

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Simulador DCA Sniper Pro",
    page_icon="🚀",
    layout="wide"
)

# --- TÍTULO Y DESCRIPCIÓN ---
st.title("💰 Simulador Estratégico: DCA Sniper + Defensa LTV")
st.markdown("""
Esta aplicación simula una estrategia de acumulación de Bitcoin que utiliza **apalancamiento dinámico** según el drawdown del mercado y un **sistema de defensa** basado en el LTV para evitar liquidaciones.
""")

# ==========================================
# 🎛️ BARRA LATERAL (CONFIGURACIÓN)
# ==========================================
st.sidebar.header("1. Configuración General")

TICKER = st.sidebar.text_input("Ticker (Yahoo Finance)", value="BTC-USD")
FECHA_INICIO = st.sidebar.date_input("Fecha de Inicio", value=datetime.date(2021, 11, 1))
COSTE_DEUDA_APR = st.sidebar.number_input("Coste Deuda (APR %)", value=5.0, step=0.5) / 100

st.sidebar.header("2. Capital Semanal")
MONTO_SEMANAL_BASE = st.sidebar.number_input("Inversión Base ($)", value=25)
MONTO_DEFENSA = st.sidebar.number_input("Inversión Defensa ($)", value=50)

st.sidebar.header("3. Niveles de Apalancamiento (x)")
LEV_SAFE = st.sidebar.slider("Safe (Máximos)", 1.0, 1.5, 1.0, step=0.05)
LEV_MANTENIMIENTO = st.sidebar.slider("Medio (Caída leve)", 1.0, 2.0, 1.25, step=0.05)
LEV_AGRESIVO = st.sidebar.slider("Agresivo (Caída fuerte)", 1.0, 3.0, 1.75, step=0.05)
LEV_DEFENSA = 1.0 # Fijo por seguridad

st.sidebar.header("4. Umbrales (%)")
UMBRAL_ACTIVACION = st.sidebar.slider("Esperar caída inicial del...", 0.0, 0.5, 0.20)
UMBRAL_SAFE = st.sidebar.slider("Límite Zona Segura (DD < x)", 0.0, 0.10, 0.05)
UMBRAL_AGRESIVO = st.sidebar.slider("Límite Zona Agresiva (DD > x)", 0.10, 0.50, 0.20)
UMBRAL_LTV_DEFENSA = st.sidebar.slider("🚨 Trigger DEFENSA (LTV > x)", 0.30, 0.60, 0.40)
LTV_LIQUIDACION = 0.75

# ==========================================
# ⚙️ LÓGICA DE SIMULACIÓN
# ==========================================

# Función para descargar datos (con caché para que sea rápido)
@st.cache_data
def descargar_datos(ticker, inicio):
    data = yf.download(ticker, start=inicio, progress=False)['Close']
    if isinstance(data, pd.DataFrame): 
        data = data.squeeze()
    data = data.asfreq('D', method='ffill')
    return data

# Botón de Ejecución
if st.sidebar.button("🚀 EJECUTAR SIMULACIÓN", type="primary"):
    
    with st.spinner('Descargando datos y procesando estrategia...'):
        # Descarga
        try:
            data = descargar_datos(TICKER, FECHA_INICIO)
        except Exception as e:
            st.error(f"Error descargando datos: {e}")
            st.stop()

        # Variables Iniciales
        fechas = data.index
        precios = data.values
        
        btc_acumulado = 0.0
        deuda_acumulada = 0.0
        intereses_pagados = 0.0
        dinero_invertido_tuyo = 0.0
        estrategia_activa = False
        pico_precio_mercado = 0.0
        
        historia = {'Fecha': [], 'Equity_Neto': [], 'LTV': [], 'Evento_Compra': [], 'Drawdown_Mercado': []}
        registros_tabla = []
        liquidado = False
        fecha_muerte = None

        # Bucle de Simulación
        for i, fecha in enumerate(fechas):
            precio_hoy = precios[i]
            
            # 1. Intereses Diarios
            if deuda_acumulada > 0:
                interes_diario = deuda_acumulada * (COSTE_DEUDA_APR / 365.0)
                deuda_acumulada += interes_diario
                intereses_pagados += interes_diario
            
            # 2. Drawdown Mercado
            if precio_hoy > pico_precio_mercado: pico_precio_mercado = precio_hoy
            dd_mercado = 0.0
            if pico_precio_mercado > 0:
                dd_mercado = (pico_precio_mercado - precio_hoy) / pico_precio_mercado
            
            # 3. Activar Estrategia
            if not estrategia_activa and dd_mercado >= UMBRAL_ACTIVACION:
                estrategia_activa = True
            
            # 4. LTV y Liquidación
            valor_colateral = btc_acumulado * precio_hoy
            ltv_actual = 0.0
            if valor_colateral > 0: ltv_actual = deuda_acumulada / valor_colateral
            
            if ltv_actual >= LTV_LIQUIDACION:
                liquidado = True
                fecha_muerte = fecha
                historia['Fecha'].append(fecha)
                historia['Equity_Neto'].append(0)
                historia['LTV'].append(ltv_actual)
                historia['Evento_Compra'].append(0)
                historia['Drawdown_Mercado'].append(dd_mercado)
                registros_tabla.append({'Fecha': fecha, 'Evento': 'LIQUIDACIÓN', 'LTV (%)': ltv_actual*100})
                break

            # 5. Compra Semanal (Lunes)
            tipo_evento_grafico = 0 
            
            if fecha.dayofweek == 0: 
                if estrategia_activa:
                    
                    # Lógica de Decisión
                    if ltv_actual > UMBRAL_LTV_DEFENSA:
                        monto_bolsillo = MONTO_DEFENSA
                        lev_factor = LEV_DEFENSA
                        tipo_evento_grafico = 3.0
                        etiqueta = "🛡️ DEFENSA"
                    else:
                        monto_bolsillo = MONTO_SEMANAL_BASE
                        if dd_mercado > UMBRAL_AGRESIVO:
                            lev_factor = LEV_AGRESIVO
                            tipo_evento_grafico = LEV_AGRESIVO
                            etiqueta = f"🔥 Agresivo {LEV_AGRESIVO}x"
                        elif dd_mercado > UMBRAL_SAFE:
                            lev_factor = LEV_MANTENIMIENTO
                            tipo_evento_grafico = LEV_MANTENIMIENTO
                            etiqueta = f"⚖️ Medio {LEV_MANTENIMIENTO}x"
                        else:
                            lev_factor = LEV_SAFE
                            tipo_evento_grafico = LEV_SAFE
                            etiqueta = f"✅ Safe {LEV_SAFE}x"
                    
                    # Ejecución
                    total_compra = monto_bolsillo * lev_factor
                    deuda_nueva = total_compra - monto_bolsillo
                    
                    btc_comprado = total_compra / precio_hoy
                    btc_acumulado += btc_comprado
                    deuda_acumulada += deuda_nueva
                    dinero_invertido_tuyo += monto_bolsillo
                    
                    # Registro
                    ltv_post = deuda_acumulada / (btc_acumulado * precio_hoy)
                    registros_tabla.append({
                        'Fecha': fecha.date(),
                        'Precio': precio_hoy,
                        'Tipo': etiqueta,
                        'Cash Puesto': monto_bolsillo,
                        'Deuda Nueva': deuda_nueva,
                        'LTV Pre (%)': ltv_actual * 100,
                        'LTV Post (%)': ltv_post * 100,
                        'DD Mercado (%)': dd_mercado * 100
                    })
                else:
                     registros_tabla.append({
                        'Fecha': fecha.date(), 'Precio': precio_hoy, 'Tipo': '⏳ Espera', 
                        'Cash Puesto': 0, 'Deuda Nueva': 0, 'LTV Pre (%)': 0, 'LTV Post (%)': 0, 'DD Mercado (%)': dd_mercado * 100
                    })

            historia['Fecha'].append(fecha)
            historia['Equity_Neto'].append(valor_colateral - deuda_acumulada)
            historia['LTV'].append(ltv_actual)
            historia['Evento_Compra'].append(tipo_evento_grafico)
            historia['Drawdown_Mercado'].append(dd_mercado)

        # DataFrames Finales
        df_hist = pd.DataFrame(historia).set_index('Fecha')
        df_registros = pd.DataFrame(registros_tabla)

        # Benchmark (DCA Normal 1x)
        df_bench = pd.DataFrame(data)
        df_bench.columns = ['Precio']
        df_bench['Es_Compra'] = np.where(df_bench.index.dayofweek == 0, 1, 0)
        df_bench['Inv_Acum'] = df_bench['Es_Compra'].cumsum() * MONTO_SEMANAL_BASE
        df_bench['Valor_Benchmark'] = (df_bench['Es_Compra'] * (MONTO_SEMANAL_BASE / df_bench['Precio'])).cumsum() * df_bench['Precio']

        # ==========================================
        # 📊 VISUALIZACIÓN DE RESULTADOS
        # ==========================================
        
        # 1. METRICAS PRINCIPALES (KPIs)
        st.divider()
        
        dias_totales = (df_hist.index[-1] - df_hist.index[0]).days
        anyos = dias_totales / 365.25
        
        # Cálculo Benchmark
        bench_inv = df_bench['Inv_Acum'].iloc[-1]
        bench_val = df_bench['Valor_Benchmark'].iloc[-1]
        bench_roi = ((bench_val - bench_inv)/bench_inv)*100
        bench_cagr = ((bench_val / bench_inv) ** (1/anyos)) - 1
        
        # Cálculo Estrategia
        strat_inv = dinero_invertido_tuyo
        strat_val = 0 if liquidado else df_hist['Equity_Neto'].iloc[-1]
        strat_roi = -100 if liquidado else ((strat_val - strat_inv)/strat_inv)*100
        strat_cagr = -1.0 if (liquidado or strat_val<=0) else ((strat_val / strat_inv) ** (1/anyos)) - 1

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Valor Neto Final", f"${strat_val:,.2f}", delta=f"{strat_roi:.2f}% ROI")
        col2.metric("CAGR (Anualizado)", f"{strat_cagr*100:.2f}%", delta=f"vs {bench_cagr*100:.2f}% Bench")
        col3.metric("Inversión Bolsillo", f"${strat_inv:,.0f}", help="Dinero real aportado")
        col4.metric("Coste Deuda", f"${intereses_pagados:,.2f}", help="Intereses pagados al 5%")

        if liquidado:
            st.error(f"☠️ ESTRATEGIA LIQUIDADA EL {fecha_muerte.date()}")

        # 2. GRÁFICOS
        st.subheader("Análisis Visual")
        
        fig, axes = plt.subplots(3, 1, figsize=(12, 16), sharex=True)
        
        # Equity
        ax1 = axes[0]
        ax1.set_title("1. Evolución del Patrimonio (Equity)", fontweight='bold')
        ax1.plot(df_hist.index, df_hist['Equity_Neto'], label='Tu Estrategia (Neto)', color='blue')
        ax1.plot(df_bench.index, df_bench['Valor_Benchmark'], label='Benchmark (DCA 1x)', color='gray', linestyle='--')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Decisiones
        ax2 = axes[1]
        ax2.set_title("2. Mapa de Decisiones", fontweight='bold')
        ax2.plot(df_hist.index, df_hist['Drawdown_Mercado']*-100, color='black', label='Mercado', alpha=0.5)
        
        defensa = df_hist[df_hist['Evento_Compra'] == 3.0]
        agresivo = df_hist[df_hist['Evento_Compra'] == LEV_AGRESIVO]
        medio = df_hist[df_hist['Evento_Compra'] == LEV_MANTENIMIENTO]
        safe = df_hist[df_hist['Evento_Compra'] == LEV_SAFE]
        
        ax2.scatter(defensa.index, [-25]*len(defensa), marker='s', color='gold', s=80, label='DEFENSA', edgecolors='black', zorder=5)
        ax2.scatter(agresivo.index, [-15]*len(agresivo), marker='^', color='purple', s=60, label='Agresivo', zorder=4)
        ax2.scatter(medio.index, [-10]*len(medio), marker='o', color='cyan', s=30, label='Medio', zorder=3)
        ax2.scatter(safe.index, [-5]*len(safe), marker='*', color='green', s=60, label='Safe', zorder=3)
        ax2.legend(loc='lower left')
        ax2.grid(True, alpha=0.3)
        
        # LTV
        ax3 = axes[2]
        ax3.set_title("3. Monitor de Riesgo (LTV)", fontweight='bold')
        ax3.plot(df_hist.index, df_hist['LTV']*100, color='orange', label='LTV Real')
        ax3.axhline(UMBRAL_LTV_DEFENSA*100, color='gold', linestyle='--', label='Umbral Defensa')
        ax3.axhline(LTV_LIQUIDACION*100, color='red', linestyle='--', label='Liquidación')
        ax3.set_ylim(0, 100)
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        
        st.pyplot(fig)
        
        # 3. DATOS DETALLADOS
        st.subheader("Registro de Operaciones")
        with st.expander("Ver Tabla Detallada"):
            st.dataframe(df_registros)
            
        # Botón descargar CSV
        csv = df_registros.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Descargar Tabla en CSV",
            data=csv,
            file_name='simulacion_dca_sniper.csv',
            mime='text/csv',
        )
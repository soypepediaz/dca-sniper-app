import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import datetime
import requests
from calendar import monthrange

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Simulador DCA Sniper Pro",
    page_icon="🧠",
    layout="wide"
)

# --- TÍTULO ---
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

st.sidebar.header("3. Estrategia de Apalancamiento")
st.sidebar.info("Estos valores definen el % de Deuda sobre el Total del Portafolio.")
TARGET_LTV_BASE = st.sidebar.slider("Target LTV Base (%)", 0.0, 0.50, 0.25)
TARGET_LTV_AGRESIVO = st.sidebar.slider("Target LTV Agresivo (%)", 0.0, 0.60, 0.40) # Has pedido 1.75 antes, aquí es LTV Global, 40% es muy agresivo ya.
UMBRAL_DD_AGRESIVO = st.sidebar.slider("Activar Agresivo si DD > (%)", 0.10, 0.50, 0.30)

st.sidebar.header("4. Filtros de Seguridad (Safe Mode)")
UMBRAL_DD_SAFE = st.sidebar.slider("Drawdown es menor a (%)", 0.0, 0.10, 0.05)
UMBRAL_LTV_SAFE = st.sidebar.slider("LTV Actual supera el (%)", 0.10, 0.60, 0.40)

st.sidebar.header("5. Defensa y Liquidación")
LIQ_THRESHOLD = st.sidebar.number_input("Liquidation Threshold (%)", value=75.0) / 100
PCT_UMBRAL_DEFENSA = st.sidebar.slider("Activar Defensa al % del Liq. Threshold", 0.50, 0.95, 0.80)
TRIGGER_DEFENSA_LTV = LIQ_THRESHOLD * PCT_UMBRAL_DEFENSA
MULTIPLO_DEFENSA = st.sidebar.number_input("Multiplicador Aportación en Defensa", value=2.0)

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

def enviar_a_moosend(nombre, email):
    """Envía el contacto a Moosend vía API"""
    try:
        # Recuperamos la clave de los Secrets de Streamlit
        api_key = st.secrets["MOOSEND_API_KEY"]
        list_id = "75c61863-63dc-4fd3-9ed8-856aee90d04a"
        
        url = f"https://api.moosend.com/v3/subscribers/{list_id}/subscribe.json?apikey={api_key}"
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        data = {'Name': nombre, 'Email': email}
        
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 200:
            return True, "¡Suscrito correctamente! Te enviaremos info pronto."
        else:
            return False, f"Error Moosend: {response.text}"
            
    except Exception as e:
        # Si no hay API key configurada o falla la conexión
        return False, "Error de configuración: No se encontró la API Key o falló la conexión."

# ==========================================
# 🚀 MOTOR DE SIMULACIÓN
# ==========================================

if st.sidebar.button("EJECUTAR SIMULACIÓN", type="primary"):
    
    with st.spinner('Simulando Estrategia vs Benchmark...'):
        # 1. Datos
        try:
            data = descargar_datos(TICKER, FECHA_INICIO)
        except Exception as e:
            st.error(f"Error descargando datos: {e}")
            st.stop()
            
        fechas = data.index
        precios = data.values
        
        # --- ESTADOS ---
        btc_acumulado = 0.0
        deuda_acumulada = 0.0
        dinero_invertido = 0.0
        intereses_pagados = 0.0
        estrategia_activa_dca = False 
        compra_inicial_hecha = False
        
        bench_btc = 0.0
        bench_invertido = 0.0
        
        pico_precio = 0.0
        historia = {
            'Fecha': [], 
            'Equity_Strat': [], 'LTV': [], 'Drawdown': [], 'Evento': [],
            'Equity_Bench': []
        }
        registros = []
        liquidado = False
        fecha_liq = None

        # --- BUCLE DIARIO ---
        for i, fecha in enumerate(fechas):
            precio = precios[i]
            
            # Intereses
            if deuda_acumulada > 0:
                interes = deuda_acumulada * (COSTE_DEUDA_APR / 365.0)
                deuda_acumulada += interes
                intereses_pagados += interes
            
            # Drawdown
            if precio > pico_precio: pico_precio = precio
            dd = 0.0
            if pico_precio > 0: dd = (pico_precio - precio) / pico_precio
            
            # Trigger DCA
            if not estrategia_activa_dca and dd >= UMBRAL_INICIO_DCA:
                estrategia_activa_dca = True
            
            # LTV y Liquidación
            colateral_total = btc_acumulado * precio
            ltv = 0.0
            if colateral_total > 0: ltv = deuda_acumulada / colateral_total
            
            if ltv >= LIQ_THRESHOLD:
                liquidado = True
                fecha_liq = fecha
                historia['Fecha'].append(fecha)
                historia['Equity_Strat'].append(0)
                historia['Equity_Bench'].append(bench_btc * precio)
                historia['LTV'].append(ltv)
                historia['Drawdown'].append(dd)
                historia['Evento'].append("💀 LIQ")
                registros.append({'Fecha': fecha, 'Tipo': 'LIQUIDACIÓN', 'LTV': ltv})
                break
            
            # --- COMPRAS ---
            # A) INICIO
            if i == 0: 
                # Estrategia
                btc_acumulado += INVERSION_INICIAL / precio
                dinero_invertido += INVERSION_INICIAL
                compra_inicial_hecha = True
                # Benchmark
                bench_btc += INVERSION_INICIAL / precio
                bench_invertido += INVERSION_INICIAL
                
                tipo_evento = "INICIO"
                etiqueta_tabla = "Inversión Inicial"
                
                registros.append({
                    'Fecha': fecha.strftime('%Y-%m-%d'), 'Precio': precio, 'Tipo': "INICIO",
                    'Cash ($)': INVERSION_INICIAL, 'Deuda Nueva ($)': 0,
                    'LTV Post (%)': 0, 'DD (%)': dd * 100
                })
            
            # B) RECURRENTE
            elif es_dia_de_compra(fecha, FRECUENCIA, locals().get('DIA_SEMANA_IDX'), locals().get('DIA_MES')):
                
                # Benchmark (Siempre compra)
                bench_btc += APORTACION_BASE / precio
                bench_invertido += APORTACION_BASE
                
                # Estrategia
                if estrategia_activa_dca:
                    cash_base = APORTACION_BASE
                    cash_a_invertir = 0.0
                    deuda_a_tomar = 0.0
                    
                    es_extra = False
                    if dd > UMBRAL_DD_EXTRA:
                        cash_base += MONTO_EXTRA
                        es_extra = True
                    
                    if ltv > TRIGGER_DEFENSA_LTV:
                        cash_a_invertir = cash_base * MULTIPLO_DEFENSA
                        target_ltv_hoy = 0.0 
                        tipo_evento = "DEFENSA"
                        etiqueta_tabla = f"🛡️ Defensa"
                    else:
                        cash_a_invertir = cash_base
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

                    if target_ltv_hoy > 0:
                        deuda_a_tomar = calcular_deuda_para_target_ltv(colateral_total, deuda_acumulada, cash_a_invertir, target_ltv_hoy)
                    else:
                        deuda_a_tomar = 0
                    
                    total_compra = cash_a_invertir + deuda_a_tomar
                    btc_acumulado += total_compra / precio
                    deuda_acumulada += deuda_a_tomar
                    dinero_invertido += cash_a_invertir
                    
                    val_post = btc_acumulado * precio
                    ltv_post = deuda_acumulada / val_post
                    
                    registros.append({
                        'Fecha': fecha.strftime('%Y-%m-%d'), 'Precio': precio, 'Tipo': etiqueta_tabla,
                        'Cash ($)': cash_a_invertir, 'Deuda Nueva ($)': deuda_a_tomar,
                        'LTV Post (%)': ltv_post * 100, 'DD (%)': dd * 100
                    })
                else:
                    tipo_evento = None

            historia['Fecha'].append(fecha)
            historia['Equity_Strat'].append((btc_acumulado * precio) - deuda_acumulada)
            historia['Equity_Bench'].append(bench_btc * precio)
            historia['LTV'].append(ltv)
            historia['Drawdown'].append(dd)
            historia['Evento'].append(tipo_evento)

        df = pd.DataFrame(historia).set_index('Fecha')
        df_reg = pd.DataFrame(registros)
        
        # --- CÁLCULOS FINALES ---
        dias_totales = (df.index[-1] - df.index[0]).days
        
        strat_val_final = 0 if liquidado else df['Equity_Strat'].iloc[-1]
        strat_roi = -100 if liquidado else ((strat_val_final - dinero_invertido) / dinero_invertido) * 100
        strat_cagr = calcular_cagr(strat_val_final, dinero_invertido, dias_totales)
        
        bench_val_final = df['Equity_Bench'].iloc[-1]
        bench_roi = ((bench_val_final - bench_invertido) / bench_invertido) * 100
        bench_cagr = calcular_cagr(bench_val_final, bench_invertido, dias_totales)
        
        # ==========================================
        # 📊 PRESENTACIÓN DE RESULTADOS
        # ==========================================
        
        st.divider()
        st.subheader("🏆 Comparativa de Rendimiento")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Valor Neto Estrategia", f"${strat_val_final:,.2f}", f"{strat_roi:.2f}% ROI")
        col2.metric("Valor Neto Benchmark", f"${bench_val_final:,.2f}", f"{bench_roi:.2f}% ROI")
        delta_cagr = (strat_cagr - bench_cagr) * 100
        col3.metric("CAGR Estrategia vs Bench", f"{strat_cagr*100:.2f}%", f"{delta_cagr:+.2f}% Dif")
        
        # --- TABLA RESUMEN ---
        resumen_data = {
            "Métrica": ["Inversión Bolsillo (Total)", "Valor Final (Equity)", "ROI Total", "CAGR (Anualizado)", "Deuda Final / Coste"],
            "🤖 Tu Estrategia (Target LTV)": [
                f"${dinero_invertido:,.0f}", f"${strat_val_final:,.2f}", f"{strat_roi:.2f}%", f"{strat_cagr*100:.2f}%",
                f"${deuda_acumulada:,.0f} (Int: ${intereses_pagados:,.0f})"
            ],
            "🐢 Benchmark (DCA Puro)": [
                f"${bench_invertido:,.0f}", f"${bench_val_final:,.2f}", f"{bench_roi:.2f}%", f"{bench_cagr*100:.2f}%",
                "$0"
            ]
        }
        st.table(pd.DataFrame(resumen_data))
        
        if liquidado:
            st.error(f"☠️ ATENCIÓN: La estrategia fue LIQUIDADA el {fecha_liq.strftime('%Y-%m-%d')}.")

        # --- GRÁFICOS ---
        tab1, tab2 = st.tabs(["Gráficos", "Operaciones"])
        with tab1:
            fig, axes = plt.subplots(3, 1, figsize=(12, 16), sharex=True)
            
            # Equity
            axes[0].set_title("1. Estrategia vs Benchmark (Patrimonio Neto)", fontweight='bold')
            axes[0].plot(df.index, df['Equity_Strat'], color='#1f77b4', linewidth=2, label='Tu Estrategia')
            axes[0].plot(df.index, df['Equity_Bench'], color='gray', linestyle='--', linewidth=1.5, label='Benchmark DCA')
            axes[0].fill_between(df.index, df['Equity_Strat'], df['Equity_Bench'], where=(df['Equity_Strat'] > df['Equity_Bench']), color='green', alpha=0.1)
            axes[0].legend()
            axes[0].grid(True, alpha=0.3)
            
            # Decisiones
            axes[1].set_title("2. Mapa de Decisiones", fontweight='bold')
            axes[1].plot(df.index, df['Drawdown']*-100, color='black', alpha=0.3, label='Mercado')
            evt_def = df[df['Evento'] == "DEFENSA"]
            axes[1].scatter(evt_def.index, [-25]*len(evt_def), marker='s', s=80, color='red', label='Defensa')
            evt_agg = df[df['Evento'] == "AGRESIVO"]
            axes[1].scatter(evt_agg.index, [-15]*len(evt_agg), marker='^', s=60, color='purple', label='Agresivo')
            evt_base = df[df['Evento'] == "BASE"]
            axes[1].scatter(evt_base.index, [-10]*len(evt_base), marker='o', s=30, color='cyan', label='Base')
            axes[1].set_ylabel("DD (%)")
            axes[1].legend(loc='lower left')
            axes[1].grid(True, alpha=0.3)
            
            # LTV
            axes[2].set_title("3. Riesgo LTV", fontweight='bold')
            axes[2].plot(df.index, df['LTV']*100, color='orange', label='LTV Real')
            axes[2].axhline(LIQ_THRESHOLD*100, color='red', linestyle='--', label='Liquidación')
            axes[2].axhline(TRIGGER_DEFENSA_LTV*100, color='brown', linestyle=':', label='Trigger Defensa')
            axes[2].set_ylabel("LTV (%)")
            axes[2].set_ylim(0, 100)
            axes[2].legend(loc='upper left')
            axes[2].grid(True, alpha=0.3)
            st.pyplot(fig)
            
        with tab2:
            st.dataframe(df_reg)

       # ==========================================
        # 📝 INFORME DINÁMICO (CORREGIDO)
        # ==========================================
        st.markdown("---")
        st.subheader("📄 Informe de Estrategia Generada")
        
        valor_defensa_aprox = APORTACION_BASE * MULTIPLO_DEFENSA
        
        # NOTA: He añadido una barra invertida (\) antes de cada signo $ 
        # para evitar que Streamlit lo interprete como fórmula matemática.
        
        informe_texto = f"""
        ### 1. Perfil de Inversión
        Has configurado una estrategia para **{TICKER}** con una inversión inicial de **\${INVERSION_INICIAL}**.
        
        El sistema realizará aportaciones periódicas de **\${APORTACION_BASE}** con una frecuencia **{FRECUENCIA}**.
        
        > *Objetivo:* Acumular activo aprovechando la volatilidad, utilizando deuda inteligente para potenciar el retorno sin comprometer la seguridad.

        ### 2. Mecánica de Entrada (Sniper)
        A diferencia de un DCA ciego, este algoritmo **permanecerá en espera** al inicio. No ejecutará la primera compra recurrente hasta que el mercado no sufra una corrección (Drawdown) superior al **{UMBRAL_INICIO_DCA*100:.0f}%**. Esto evita comprar sistemáticamente en techos de mercado.

        ### 3. Gestión de Deuda (Target LTV)
        La estrategia no utiliza un apalancamiento fijo, sino que ajusta dinámicamente tu deuda para mantener un nivel de riesgo constante sobre el total de tu cartera:
        * **Escenario Base:** Buscará mantener un LTV (Deuda/Colateral) del **{TARGET_LTV_BASE*100:.0f}%**.
        * **Escenario Agresivo:** Si el mercado cae más de un **{UMBRAL_DD_AGRESIVO*100:.0f}%**, el sistema aumentará el riesgo buscando un LTV del **{TARGET_LTV_AGRESIVO*100:.0f}%** para comprar más barato.
        * **Modo Seguro (Safe Mode):** Si el mercado está cerca de máximos (caída < **{UMBRAL_DD_SAFE*100:.0f}%**) o tu deuda ya es elevada (> **{UMBRAL_LTV_SAFE*100:.0f}%** LTV), el sistema **dejará de pedir prestado** y comprará solo con tu efectivo.

        ### 4. Protocolos de Seguridad y Defensa
        * **Defensa Activa:** Si en algún momento tu LTV cruza la línea roja del **{TRIGGER_DEFENSA_LTV*100:.0f}%** (calculado sobre tu umbral de liquidación), el sistema activará el "Modo Pánico": inyectará **{MULTIPLO_DEFENSA}x** veces tu aportación habitual (aprox **\${valor_defensa_aprox}**) sin deuda para diluir el riesgo inmediatamente.
        * **Coste Financiero:** El modelo asume un coste de la deuda del **{COSTE_DEUDA_APR*100:.1f}%** anual, que se acumula diariamente en contra de tu patrimonio neto.
        """
        st.markdown(informe_texto)
        
        # ==========================================
        # 📧 FORMULARIO MOOSEND
        # ==========================================
        st.markdown("---")
        st.subheader("📬 ¿Quieres descubrir más estrategias institucionales?")
        st.write("Suscríbete para recibir alertas sobre nuevos algoritmos DeFi y análisis de mercado.")
        
        with st.form("moosend_form"):
            col_form_1, col_form_2 = st.columns(2)
            with col_form_1:
                nombre_usuario = st.text_input("Nombre")
            with col_form_2:
                email_usuario = st.text_input("Correo Electrónico")
            
            submit_btn = st.form_submit_button("Enviar y Suscribirme")
            
            if submit_btn:
                if email_usuario:
                    exito, mensaje = enviar_a_moosend(nombre_usuario, email_usuario)
                    if exito:
                        st.success(mensaje)
                    else:
                        st.warning(mensaje)
                else:
                    st.error("Por favor, introduce un correo electrónico.")


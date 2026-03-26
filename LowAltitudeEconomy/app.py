import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import base64
from datetime import datetime
import os

# Set page config
st.set_page_config(page_title="低空经济数据可视化大屏", layout="wide", page_icon="🚁")

# Load Data
@st.cache_data
def load_data():
    import mock_data
    # Check if file exists
    if os.path.exists("low_altitude_data.csv"):
        df = pd.read_csv("low_altitude_data.csv")
        # Check if new fields exist, if not, regenerate
        required_cols = ["Vertiports", "Scenario_Logistics", "Scenario_Tourism"]
        if not all(col in df.columns for col in required_cols):
            df = mock_data.generate_data()
            df.to_csv("low_altitude_data.csv", index=False)
    else:
        df = mock_data.generate_data()
        df.to_csv("low_altitude_data.csv", index=False)
    return df

df = load_data()

# Styles
st.markdown("""
<style>
    /* 全局背景设为深色 */
    .stApp {
        background-color: #1a0500; /* 深红褐色背景 */
        background-image: linear-gradient(180deg, #1a0500 0%, #000000 100%);
        color: #fff;
    }
    
    /* 标题样式 */
    h1, h2, h3, h4 {
        color: #FFD700 !important; /* 金色标题 */
        text-shadow: 0 0 10px #FF4500;
        font-family: 'Microsoft YaHei', sans-serif;
    }
    
    /* 侧边栏样式 */
    [data-testid="stSidebar"] {
        background-color: #2b0a05;
        border-right: 1px solid #FF4500;
    }
    
    /* 指标卡片样式 DataV风格 */
    .metric-card {
        background: rgba(40, 10, 5, 0.7);
        border: 1px solid #FF4500;
        box-shadow: 0 0 15px rgba(255, 69, 0, 0.3) inset;
        padding: 15px;
        border-radius: 5px;
        text-align: center;
        margin-bottom: 10px;
    }
    .metric-label {
        font-size: 14px;
        color: #FFB07C;
        margin-bottom: 5px;
    }
    .metric-value {
        font-size: 24px;
        font-weight: bold;
        color: #FFD700;
        text-shadow: 0 0 5px #FF8C00;
    }
    
    /* 容器边框样式 */
    .chart-container {
        background: rgba(20, 5, 5, 0.5);
        border: 1px solid #8B2500;
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 15px;
    }
    
    /* 去除Plotly默认背景 */
    .js-plotly-plot .plotly .main-svg {
        background: transparent !important;
    }
</style>
""", unsafe_allow_html=True)

# Header with DataV style
st.markdown("<h1 style='text-align: center; padding-top: 0; margin-bottom: 30px;'>🚁 全国低空经济产业态势感知平台</h1>", unsafe_allow_html=True)

# Sidebar
st.sidebar.header("🕹️ 指挥控制台")
selected_regions = st.sidebar.multiselect(
    "区域筛选",
    options=df["Region"].unique(),
    default=df["Region"].unique()
)

# Filter data
filtered_df = df[df["Region"].isin(selected_regions)]

# Calculate Metrics
total_flight_hours = filtered_df["FlightHours"].sum()
total_investment = filtered_df["Investment_Billion"].sum()
total_enterprises = filtered_df["Enterprises"].sum()
total_drones = filtered_df["Drones"].sum()
total_patents = filtered_df["Patents"].sum()
total_pilots = filtered_df["Pilots"].sum()
total_vertiports = filtered_df["Vertiports"].sum() if "Vertiports" in filtered_df.columns else 0

# Helper for metric card (Moved up)
def metric_card(label, value):
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
    </div>
    """, unsafe_allow_html=True)

# Main Layout with Tabs
tab_dashboard, tab_report = st.tabs(["📊 态势感知大屏", "📑 研报生成中心"])

# --- Tab 1: Dashboard ---
with tab_dashboard:
    # KPI Metrics
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    with m_col1: metric_card("总飞行时长", f"{total_flight_hours/10000:.1f}万")
    with m_col2: metric_card("投融资总额", f"{total_investment:.0f}亿")
    with m_col3: metric_card("无人机总数", f"{total_drones:,}")
    with m_col4: metric_card("执证飞手", f"{total_pilots:,}")

    # Dashboard 3-Column Layout
    col_left, col_center, col_right = st.columns([1, 2, 1], gap="medium")

    # --- Left Column: Charts ---
    with col_left:
        st.markdown("### 📈 产业规模分析")
        
        # Chart 1: Investment Ranking (Horizontal Bar)
        with st.container():
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            fig_inv = px.bar(
                filtered_df.sort_values("Investment_Billion", ascending=True),
                x="Investment_Billion",
                y="Region",
                orientation='h',
                title="各地投融资规模 (十亿元)",
                template="plotly_dark",
                color="Investment_Billion",
                color_continuous_scale=["#330000", "#FF4500", "#FFD700"] # Dark Red to Gold
            )
            fig_inv.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': '#FFD700'},
                margin=dict(l=10, r=10, t=40, b=10),
                height=280
            )
            st.plotly_chart(fig_inv, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Chart 2: Infrastructure Bar
        with st.container():
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            # Infrastructure: Vertiports
            fig_infra = px.bar(
                filtered_df.sort_values("Vertiports", ascending=False).head(5),
                x="Region",
                y="Vertiports",
                title="TOP5 起降场设施数量",
                template="plotly_dark",
                color="Vertiports",
                color_continuous_scale=["#FF4500", "#FFD700"]
            )
            fig_infra.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': '#FFD700'},
                margin=dict(l=10, r=10, t=40, b=10),
                height=250
            )
            st.plotly_chart(fig_infra, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Chart 3: Enterprise & Patent Bubble
        with st.container():
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            fig_bubble = px.scatter(
                filtered_df,
                x="Enterprises",
                y="Patents",
                size="Investment_Billion",
                color="Region",
                title="企业创新效能矩阵",
                template="plotly_dark"
            )
            fig_bubble.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': '#FFD700'},
                margin=dict(l=10, r=10, t=40, b=10),
                height=250,
                showlegend=False
            )
            st.plotly_chart(fig_bubble, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

    # --- Center Column: Map ---
    with col_center:
        st.markdown("### 🗺️ 产业热力分布图")
        # Map Visualization (Dark Theme)
        with st.container():
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            fig_map = px.scatter_mapbox(
                filtered_df,
                lat="Lat",
                lon="Lon",
                hover_name="Region",
                size="Investment_Billion",
                color="FlightHours",
                color_continuous_scale=["#FFD700", "#FF4500", "#8B0000"], # Gold to Dark Red
                size_max=40,
                zoom=3.5,
                center={"lat": 35.0, "lon": 105.0},
                mapbox_style="carto-darkmatter", # Dark map style
            )
            fig_map.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                margin={"r":0,"t":0,"l":0,"b":0},
                height=600,
                coloraxis_colorbar=dict(
                    title=dict(text="飞行活跃度", font=dict(color="#FFD700")),
                    tickfont=dict(color="#FFD700")
                )
            )
            st.plotly_chart(fig_map, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

    # --- Right Column: Trends & Analysis ---
    with col_right:
        st.markdown("### 📊 运营态势监测")
        
        # Chart 4: Application Scenarios (Rose/Pie)
        with st.container():
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            # Aggregate scenario data
            scenarios = {
                "物流配送": filtered_df["Scenario_Logistics"].sum() if "Scenario_Logistics" in filtered_df.columns else 40,
                "文旅观光": filtered_df["Scenario_Tourism"].sum() if "Scenario_Tourism" in filtered_df.columns else 30,
                "农林植保": filtered_df["Scenario_Agri"].sum() if "Scenario_Agri" in filtered_df.columns else 20,
                "巡检安防": filtered_df["Scenario_Inspection"].sum() if "Scenario_Inspection" in filtered_df.columns else 10
            }
            
            fig_rose = go.Figure(data=[go.Pie(
                labels=list(scenarios.keys()), 
                values=list(scenarios.values()), 
                hole=.3,
                marker_colors=['#FF4500', '#FF8C00', '#FFD700', '#8B0000']
            )])
            fig_rose.update_layout(
                title="应用场景占比分析",
                template="plotly_dark",
                paper_bgcolor='rgba(0,0,0,0)',
                font={'color': '#FFD700'},
                margin=dict(l=10, r=10, t=40, b=10),
                height=250,
                showlegend=True,
                legend=dict(orientation="h", y=-0.1)
            )
            st.plotly_chart(fig_rose, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Chart 5: Safety Trend (Area Chart)
        with st.container():
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            # Mock safety trend
            months = ['1月', '2月', '3月', '4月', '5月', '6月']
            accidents_trend = [5, 4, 6, 3, 2, 1]
            flights_trend = [1200, 1500, 1800, 2200, 2600, 3000]
            
            fig_safe = go.Figure()
            fig_safe.add_trace(go.Scatter(
                x=months, y=flights_trend, name="飞行架次",
                fill='tozeroy', line=dict(color='#FFD700')
            ))
            fig_safe.add_trace(go.Scatter(
                x=months, y=[a*100 for a in accidents_trend], name="安全指数", # Scaled for visibility
                line=dict(color='#FF4500', dash='dot')
            ))
            fig_safe.update_layout(
                title="飞行架次与安全指数趋势",
                template="plotly_dark",
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': '#FFD700'},
                margin=dict(l=10, r=10, t=40, b=10),
                height=250,
                legend=dict(orientation="h", y=1.1)
            )
            st.plotly_chart(fig_safe, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Chart 6: Pilot Distribution (Donut)
        with st.container():
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            # Top regions for pilots
            top_pilots = filtered_df.sort_values("Pilots", ascending=False).head(4)
            others_pilots = filtered_df.sort_values("Pilots", ascending=False).iloc[4:]["Pilots"].sum()
            
            p_labels = list(top_pilots["Region"]) + ["其他"]
            p_values = list(top_pilots["Pilots"]) + [others_pilots]
            
            fig_pilot = go.Figure(data=[go.Pie(
                labels=p_labels, 
                values=p_values, 
                hole=.6,
                marker_colors=['#FFD700', '#FF8C00', '#FF4500', '#8B0000', '#330000']
            )])
            fig_pilot.update_layout(
                title="执证飞手区域分布",
                template="plotly_dark",
                paper_bgcolor='rgba(0,0,0,0)',
                font={'color': '#FFD700'},
                margin=dict(l=10, r=10, t=40, b=10),
                height=250,
                showlegend=True,
                legend=dict(orientation="v", x=1.0)
            )
            # Add center text
            fig_pilot.add_annotation(text=f"{total_pilots}", x=0.5, y=0.5, font_size=20, showarrow=False, font_color="#FFD700")
            
            st.plotly_chart(fig_pilot, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Widget: Real-time Alerts
        with st.container():
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            st.markdown("#### 🔔 实时预警动态")
            alerts = [
                "🔴 [10:23] 深圳蛇口航线突发大风预警，航班暂停",
                "🟡 [09:45] 北京延庆空域出现非报备无人机，已驱离",
                "🟢 [09:00] 上海金山水上机场今日首飞成功",
                "🟢 [08:30] 成都淮州机场开通低空物流专线",
                "🟡 [08:15] 广州南沙空域流量接近饱和，请注意避让"
            ]
            for alert in alerts:
                color = "#FF4500" if "🔴" in alert else ("#FFD700" if "🟡" in alert else "#00FF00")
                st.markdown(f"<div style='padding:5px; border-bottom:1px solid #333; color:{color}; font-size:12px;'>{alert}</div>", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

# --- Tab 2: Report Center ---
with tab_report:
    st.markdown("## 📑 智能研报生成中心")
    st.markdown("请选择下方的专业模板，一键生成高质量行业研究报告。")
    st.markdown("---")

    def generate_pdf_report(dataframe, template_name):
        pdf = FPDF()
        pdf.add_page()
        
        # Title Page
        pdf.set_font("Arial", 'B', 20)
        if "A." in template_name:
            title = "Low-Altitude Economy: Industry Overview"
        elif "B." in template_name:
            title = "Regional Competitiveness Analysis"
        else:
            title = "Operations & Safety Monitoring Report"
            
        pdf.cell(0, 20, title, 0, 1, 'C')
        
        pdf.set_font("Arial", '', 12)
        pdf.cell(0, 10, f'Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M")}', 0, 1, 'C')
        pdf.ln(10)
        
        # Common Header: Scope
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 10, '1. Scope & Coverage', 0, 1)
        pdf.set_font("Arial", '', 11)
        pdf.multi_cell(0, 8, f"This report covers {len(dataframe)} regions with a total investment of {dataframe['Investment_Billion'].sum():.1f} Billion RMB.")
        pdf.ln(5)

        # Template Specific Content
        if "A." in template_name:
            # --- Type A: Overview ---
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, '2. Market Scale & Infrastructure', 0, 1)
            pdf.set_font("Arial", '', 11)
            
            total_inv = dataframe['Investment_Billion'].sum()
            total_ent = dataframe['Enterprises'].sum()
            total_vert = dataframe['Vertiports'].sum() if 'Vertiports' in dataframe else 0
            
            pdf.multi_cell(0, 8, 
                f"The selected regions demonstrate strong market potential.\n"
                f"- Total Investment: {total_inv:.2f} Billion RMB\n"
                f"- Total Enterprises: {total_ent}\n"
                f"- Infrastructure (Vertiports): {total_vert} units operational.\n\n"
                f"Infrastructure build-out is accelerating, providing a solid foundation for future growth."
            )
            
            pdf.ln(5)
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, '3. Key Regional Hubs', 0, 1)
            pdf.set_font("Arial", '', 11)
            top_regions = dataframe.sort_values('Investment_Billion', ascending=False).head(5)
            for i, (idx, row) in enumerate(top_regions.iterrows(), 1):
                 pdf.cell(0, 8, f"{i}. Region {row['Region']}: {row['Investment_Billion']}B Invest, {row['Enterprises']} Enterprises", 0, 1)

        elif "B." in template_name:
            # --- Type B: Competitiveness ---
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, '2. Talent & Innovation Matrix', 0, 1)
            pdf.set_font("Arial", '', 11)
            
            total_pilots = dataframe['Pilots'].sum()
            total_patents = dataframe['Patents'].sum()
            
            pdf.multi_cell(0, 8, 
                f"Talent and technology are the core drivers of competitiveness.\n"
                f"- Total Certified Pilots: {total_pilots}\n"
                f"- Total Registered Patents: {total_patents}\n"
                f"- Innovation Density: {total_patents/len(dataframe):.1f} patents per region avg."
            )
            
            pdf.ln(5)
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, '3. Top Competitive Regions', 0, 1)
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(40, 10, 'Region', 1)
            pdf.cell(40, 10, 'Pilots', 1)
            pdf.cell(40, 10, 'Patents', 1)
            pdf.cell(40, 10, 'Score', 1)
            pdf.ln()
            
            pdf.set_font("Arial", '', 10)
            # Simple weighted score
            df_score = dataframe.copy()
            df_score['Score'] = (df_score['Pilots'] * 0.4 + df_score['Patents'] * 0.6).astype(int)
            top_comp = df_score.sort_values('Score', ascending=False).head(5)
            
            for _, row in top_comp.iterrows():
                pdf.cell(40, 10, str(row['Region']), 1)
                pdf.cell(40, 10, str(row['Pilots']), 1)
                pdf.cell(40, 10, str(row['Patents']), 1)
                pdf.cell(40, 10, str(row['Score']), 1)
                pdf.ln()

        else:
            # --- Type C: Operations ---
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, '2. Operational Statistics', 0, 1)
            pdf.set_font("Arial", '', 11)
            
            total_hours = dataframe['FlightHours'].sum()
            avg_hours = dataframe['FlightHours'].mean()
            
            pdf.multi_cell(0, 8, 
                f"- Total Flight Hours: {total_hours:,.0f} hours\n"
                f"- Average Regional Activity: {avg_hours:,.0f} hours\n"
                f"- Drone Fleet Size: {dataframe['Drones'].sum():,} units"
            )
            
            pdf.ln(5)
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, '3. Scenario Breakdown', 0, 1)
            pdf.set_font("Arial", '', 11)
            
            s_logistics = dataframe['Scenario_Logistics'].sum() if 'Scenario_Logistics' in dataframe else 0
            s_tourism = dataframe['Scenario_Tourism'].sum() if 'Scenario_Tourism' in dataframe else 0
            
            pdf.multi_cell(0, 8, 
                f"Logistics: {s_logistics:,} ops (Approx. {(s_logistics/total_hours)*100:.1f}%)\n"
                f"Tourism: {s_tourism:,} ops (Approx. {(s_tourism/total_hours)*100:.1f}%)\n"
                f"The data suggests a shift towards commercial logistics applications."
            )

        # Conclusion
        pdf.ln(10)
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 10, '4. Strategic Recommendation', 0, 1)
        pdf.set_font("Arial", '', 11)
        
        rec_text = "Based on the data, we recommend focusing on infrastructure expansion."
        if "B." in template_name:
            rec_text = "Regions should increase subsidies for pilot training to match hardware growth."
        elif "C." in template_name:
            rec_text = "Enhanced safety monitoring systems are required for high-density logistics routes."
            
        pdf.multi_cell(0, 10, rec_text)
        
        pdf.ln(10)
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(0, 10, 'Note: PDF generated by Low-Altitude Economy Dashboard POC.', 0, 1)
        
        return pdf.output(dest='S').encode('latin-1')

    # Template Cards Layout
    t_col1, t_col2, t_col3 = st.columns(3)
    
    # --- Template A ---
    with t_col1:
        st.markdown("""
        <div class="metric-card" style="height: 400px; text-align: left;">
            <h3 style="color:#FFD700; text-align:center;">🏆 模板 A<br>产业发展综述</h3>
            <hr style="border-color: #FF4500;">
            <p style="color:#FFB07C;"><b>适用对象：</b><br>政府发改委、行业协会、宏观规划部门</p>
            <p style="color:#EEE;"><b>核心内容：</b></p>
            <ul style="color:#CCC; font-size:14px;">
                <li>产业总体规模 (投资/企业)</li>
                <li>基础设施建设进度 (起降场)</li>
                <li>区域产业热力分布</li>
                <li>核心增长极识别</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        if st.button("生成 A 类报告", key="btn_a", type="secondary", use_container_width=True):
             with st.spinner("生成中..."):
                pdf_bytes = generate_pdf_report(filtered_df, "A. 产业发展综述报告")
                b64 = base64.b64encode(pdf_bytes).decode()
                href = f'<a href="data:application/octet-stream;base64,{b64}" download="Report_Type_A.pdf" style="text-decoration:none;color:#000;background-color:#FFD700;padding:10px;border-radius:5px;display:block;text-align:center;">📥 点击下载报告</a>'
                st.markdown(href, unsafe_allow_html=True)

    # --- Template B ---
    with t_col2:
        st.markdown("""
        <div class="metric-card" style="height: 400px; text-align: left;">
            <h3 style="color:#FFD700; text-align:center;">⚔️ 模板 B<br>区域竞争力分析</h3>
            <hr style="border-color: #FF4500;">
            <p style="color:#FFB07C;"><b>适用对象：</b><br>招商局、产业园区、投资机构</p>
            <p style="color:#EEE;"><b>核心内容：</b></p>
            <ul style="color:#CCC; font-size:14px;">
                <li>区域竞争力横向排名</li>
                <li>人才-技术-资本 3D矩阵</li>
                <li>独家竞争力评分模型</li>
                <li>重点招商目标推荐</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        if st.button("生成 B 类报告", key="btn_b", type="secondary", use_container_width=True):
             with st.spinner("生成中..."):
                pdf_bytes = generate_pdf_report(filtered_df, "B. 区域竞争力专项分析")
                b64 = base64.b64encode(pdf_bytes).decode()
                href = f'<a href="data:application/octet-stream;base64,{b64}" download="Report_Type_B.pdf" style="text-decoration:none;color:#000;background-color:#FFD700;padding:10px;border-radius:5px;display:block;text-align:center;">📥 点击下载报告</a>'
                st.markdown(href, unsafe_allow_html=True)

    # --- Template C ---
    with t_col3:
        st.markdown("""
        <div class="metric-card" style="height: 400px; text-align: left;">
            <h3 style="color:#FFD700; text-align:center;">🛡️ 模板 C<br>安全与运营监测</h3>
            <hr style="border-color: #FF4500;">
            <p style="color:#FFB07C;"><b>适用对象：</b><br>空管部门、应急局、运营企业</p>
            <p style="color:#EEE;"><b>核心内容：</b></p>
            <ul style="color:#CCC; font-size:14px;">
                <li>飞行时长与频次趋势</li>
                <li>四大应用场景落地占比</li>
                <li>安全事故率监测</li>
                <li>高密度航线监管建议</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        if st.button("生成 C 类报告", key="btn_c", type="secondary", use_container_width=True):
             with st.spinner("生成中..."):
                pdf_bytes = generate_pdf_report(filtered_df, "C. 低空安全与运营监测报告")
                b64 = base64.b64encode(pdf_bytes).decode()
                href = f'<a href="data:application/octet-stream;base64,{b64}" download="Report_Type_C.pdf" style="text-decoration:none;color:#000;background-color:#FFD700;padding:10px;border-radius:5px;display:block;text-align:center;">📥 点击下载报告</a>'
                st.markdown(href, unsafe_allow_html=True)

# Bottom Data Table
st.markdown("---")
with st.expander("查看详细数据表 (View Raw Data)", expanded=False):
    st.dataframe(filtered_df)

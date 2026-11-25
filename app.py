import datetime as dt
import mysql.connector
import pandas as pd
import streamlit as st
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score

# ---- CAMBIA ESTOS DATOS POR LOS DE TU MYSQL ----
DB = dict(host="localhost", user="root", password="benji212006", database="restaurante_reservas")
NOMBRE = "Sabor & Mesa"
COL = {"Salón principal": "#2563EB", "Zona VIP": "#7C3AED", "Terraza": "#16A34A"}
HORAS = [f"{h:02d}:{m:02d}" for h in range(12, 22) for m in (0, 30)]

st.set_page_config(page_title=NOMBRE, page_icon="🍽️", layout="wide")


# ================= BASE DE DATOS =================
def conectar():
    return mysql.connector.connect(**DB)


def run(sql, params=None):
    con = conectar()
    try:
        return pd.read_sql(sql, con, params=params)
    finally:
        con.close()


def ejecutar(sql, params=None):
    con = conectar()
    try:
        cur = con.cursor()
        cur.execute(sql, params)
        con.commit()
    finally:
        con.close()


def llamar(nombre, args):
    con = conectar()
    try:
        cur = con.cursor()
        r = cur.callproc(nombre, args)
        con.commit()
        return r
    finally:
        con.close()


def accion(fn, ok):
    try:
        fn()
        st.toast(ok, icon="✅")
        return True
    except mysql.connector.Error as e:
        st.error(f"⚠️ {e.msg}")
        return False


def hms(h):
    return h + ":00"


# ================= LOGIN =================
def entrar(df):
    if len(df):
        st.session_state.user = df.iloc[0].to_dict()
        st.rerun()
    st.error("Credenciales incorrectas o usuario inactivo")


def login():
    st.markdown("""<style>[data-testid=stSidebar],[data-testid=collapsedControl]{display:none}
    .stApp{background:linear-gradient(135deg,#1F2A44 0%,#7A2E1D 100%)}
    div[data-testid=stVerticalBlockBorderWrapper]{background:#FFFAF3;border-radius:18px;padding:14px}
    </style>""", unsafe_allow_html=True)
    _, c, _ = st.columns([1, 1.3, 1])
    with c:
        st.markdown(f"<h1 style='text-align:center;color:#fff;margin-top:50px'>🍽️ {NOMBRE}</h1>"
                    "<p style='text-align:center;color:#E8DDCF;font-size:18px'>Sistema de reserva de mesas</p>",
                    unsafe_allow_html=True)
        with st.container(border=True):
            t1, t2 = st.tabs(["👤 Empleado", "🛡️ Administrador"])
            with t1:
                cod = st.text_input("Código de empleado (DNI)", max_chars=8, key="le")
                if st.button("Ingresar", key="be", type="primary", use_container_width=True):
                    entrar(run("SELECT nombre, rol FROM empleado WHERE codigo=%s AND rol='EMPLEADO' AND activo=1",
                               (cod.strip(),)))
            with t2:
                u = st.text_input("Usuario", key="lu")
                p = st.text_input("Contraseña", type="password", key="lp")
                if st.button("Ingresar como administrador", key="ba", type="primary", use_container_width=True):
                    entrar(run("SELECT nombre, rol FROM empleado WHERE codigo=%s AND rol='ADMIN' "
                               "AND clave_hash=SHA2(%s,256)", (u.strip(), p)))


if "user" not in st.session_state:
    login()
    st.stop()

user = st.session_state.user
admin = user["rol"] == "ADMIN"


# ================= MAPA DE MESAS =================
def leyenda():
    z = run("SELECT nombre, piso FROM zona ORDER BY piso, id_zona")
    h = "".join(f"<span style='background:{COL.get(r.nombre, '#F59E0B')};color:#fff;padding:4px 12px;"
                f"border-radius:12px;margin-right:8px'>{r.nombre} · Piso {r.piso}</span>" for r in z.itertuples())
    h += ("<span style='background:#9CA3AF;color:#fff;padding:4px 12px;border-radius:12px;margin-right:8px'>"
          "Ocupada o capacidad insuficiente</span>"
          "<span style='border:3px solid #111;padding:2px 10px;border-radius:12px'>Seleccionada</span>")
    st.markdown("**Guía de colores:** " + h, unsafe_allow_html=True)


def mesas_estado(fecha, hora, excluir=0):
    return run("""SELECT m.id_mesa, m.numero, m.capacidad, z.nombre AS zona, z.piso,
                  EXISTS(SELECT 1 FROM reserva r WHERE r.id_mesa=m.id_mesa AND r.fecha=%s
                    AND r.estado IN ('CONFIRMADA','ASISTIO') AND r.id_reserva<>%s
                    AND ABS(TIME_TO_SEC(r.hora)-TIME_TO_SEC(%s))<7200) AS ocupada
                  FROM mesa m JOIN zona z USING(id_zona) ORDER BY z.piso, z.id_zona, m.numero""",
               (fecha, excluir, hms(hora)))


def mapa(fecha, hora, pers, pref):
    m = mesas_estado(fecha, hora)
    libres = set(int(i) for i in m[(m.ocupada == 0) & (m.capacidad >= pers)].id_mesa)
    sel = st.session_state.get(pref)
    if sel not in libres:
        sel = st.session_state[pref] = None
    css = ""
    for r in m.itertuples():
        k = f".st-key-{pref}_{r.id_mesa} button"
        if r.id_mesa in libres:
            css += (f"{k}{{background:{COL.get(r.zona, '#F59E0B')}!important;color:#fff!important;"
                    f"border:none!important;{'outline:3px solid #111;' if r.id_mesa == sel else ''}}}")
        else:
            css += f"{k}{{background:#9CA3AF!important;color:#fff!important;border:none!important;opacity:.55}}"
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    for piso, gp in m.groupby("piso"):
        st.markdown(f"##### 🏢 Piso {piso}")
        for zona, gz in gp.groupby("zona", sort=False):
            st.caption(zona)
            for i in range(0, len(gz), 6):
                for col, r in zip(st.columns(6), gz.iloc[i:i + 6].itertuples()):
                    if col.button(f"Mesa {r.numero} · {r.capacidad}👤", key=f"{pref}_{r.id_mesa}",
                                  disabled=r.id_mesa not in libres, use_container_width=True):
                        st.session_state[pref] = int(r.id_mesa)
                        st.rerun()
    return st.session_state.get(pref)


# ================= PAGINAS =================
def pg_inicio():
    st.header(f"👋 Bienvenido, {user['nombre']}")
    h = run("SELECT COUNT(*) n, COALESCE(SUM(personas),0) p FROM reserva WHERE fecha=CURDATE() AND estado='CONFIRMADA'")
    t = run("SELECT COUNT(*) n FROM reserva WHERE fecha>CURDATE() AND estado='CONFIRMADA'")
    a, b, c = st.columns(3)
    a.metric("Reservas de hoy", int(h.n[0]))
    b.metric("Personas esperadas hoy", int(h.p[0]))
    c.metric("Reservas futuras", int(t.n[0]))
    st.subheader("Próximas reservas de hoy")
    st.dataframe(run("""SELECT TIME_FORMAT(r.hora,'%H:%i') AS hora, c.nombre AS cliente, m.numero AS mesa,
                        z.nombre AS zona, r.personas, r.observaciones FROM reserva r JOIN cliente c USING(id_cliente)
                        JOIN mesa m USING(id_mesa) JOIN zona z USING(id_zona)
                        WHERE r.fecha=CURDATE() AND r.estado='CONFIRMADA' ORDER BY r.hora"""),
                 use_container_width=True, hide_index=True)


def pg_nueva():
    st.header("📅 Nueva reserva")
    leyenda()
    cl = run("SELECT id_cliente, CONCAT(nombre,' · ',dni) AS t FROM cliente ORDER BY nombre")
    c1, c2 = st.columns([3, 2])
    cli = c1.selectbox("Cliente", cl.id_cliente, format_func=lambda i: cl.set_index("id_cliente").t[i])
    with c2.expander("➕ Registrar cliente nuevo"):
        n = st.text_input("Nombre", key="cn")
        d = st.text_input("DNI", max_chars=8, key="cd")
        t = st.text_input("Teléfono", key="ct")
        if st.button("Guardar cliente"):
            if n and len(d) == 8 and d.isdigit():
                if accion(lambda: ejecutar("INSERT INTO cliente(nombre,dni,telefono) VALUES(%s,%s,%s)", (n, d, t)),
                          "Cliente registrado"):
                    st.rerun()
            else:
                st.warning("Escribe el nombre y un DNI de 8 dígitos")
    a, b, c = st.columns(3)
    fecha = a.date_input("Fecha", dt.date.today() + dt.timedelta(days=1), min_value=dt.date.today())
    hora = b.selectbox("Hora", HORAS, index=16)
    pers = c.number_input("Personas", 1, 8, 2)
    st.markdown("#### Elige tu mesa")
    sel = mapa(fecha, hora, pers, "nv")
    obs = st.text_area("Observaciones (opcional)", placeholder="(ejemplo: alergias, tipo de evento)", max_chars=255)
    if sel:
        st.info(f"Mesa seleccionada: **{sel}**")
    if st.button("✅ Confirmar reserva", type="primary", disabled=sel is None):
        def go():
            r = llamar("sp_crear_reserva", (int(cli), int(sel), fecha, hms(hora), int(pers), obs.strip() or None, 0))
            st.success(f"Reserva N° {r[-1]} creada correctamente")
            st.session_state["nv"] = None
        accion(go, "Reserva creada")
    if sel is None:
        st.caption("Selecciona una mesa del mapa para poder confirmar.")


def pg_gestion():
    st.header("🗂️ Gestionar reservas")
    f1, f2, f3, f4 = st.columns([2, 1.3, 2, 0.8])
    rango = f1.date_input("Rango de fechas", (dt.date.today(), dt.date.today() + dt.timedelta(days=30)))
    est = f2.selectbox("Estado", ["Todos", "CONFIRMADA", "CANCELADA", "ASISTIO", "NO_SHOW"])
    txt = f3.text_input("Buscar por cliente o DNI")
    f4.write("")
    f4.button("🔄 Actualizar")
    if len(rango) < 2:
        st.info("Selecciona fecha inicial y final")
        return
    df = run("""SELECT r.id_reserva AS id, c.nombre AS cliente, c.dni, m.numero AS mesa, z.nombre AS zona,
                z.piso, r.fecha, TIME_FORMAT(r.hora,'%H:%i') AS hora, r.personas, r.estado, r.observaciones
                FROM reserva r JOIN cliente c USING(id_cliente) JOIN mesa m USING(id_mesa) JOIN zona z USING(id_zona)
                WHERE r.fecha BETWEEN %s AND %s AND (%s='Todos' OR r.estado=%s)
                AND (c.nombre LIKE %s OR c.dni LIKE %s) ORDER BY r.fecha, r.hora LIMIT 300""",
             (rango[0], rango[1], est, est, f"%{txt}%", f"%{txt}%"))
    st.caption(f"{len(df)} reservas encontradas")
    st.dataframe(df, use_container_width=True, hide_index=True)
    if df.empty:
        return
    rid = st.selectbox("Selecciona una reserva", df.id,
                       format_func=lambda i: "#{} · {} · {} {}".format(
                           i, df.set_index("id").cliente[i], df.set_index("id").fecha[i], df.set_index("id").hora[i]))
    r = df.set_index("id").loc[rid]
    st.markdown(f"**Estado actual:** {r.estado}")
    tabs = st.tabs(["✏️ Modificar", "🔁 Cambiar estado"] + (["🗑️ Eliminar"] if admin else []))
    with tabs[0]:
        if r.estado != "CONFIRMADA":
            st.info("Solo se pueden modificar reservas confirmadas.")
        else:
            a, b, c = st.columns(3)
            nf = a.date_input("Nueva fecha", r.fecha, min_value=dt.date.today(), key="mf")
            nh = b.selectbox("Nueva hora", HORAS, index=HORAS.index(r.hora) if r.hora in HORAS else 0, key="mh")
            npers = c.number_input("Personas", 1, 8, int(r.personas), key="mp")
            m = mesas_estado(nf, nh, int(rid))
            m = m[(m.ocupada == 0) & (m.capacidad >= npers)]
            if m.empty:
                st.warning("No hay mesas libres para ese horario")
            else:
                ids = list(m.id_mesa)
                actual = run("SELECT id_mesa FROM reserva WHERE id_reserva=%s", (int(rid),)).id_mesa[0]
                mesa = st.selectbox("Mesa (puedes pasar de Terraza a Salón principal)", ids,
                                    index=ids.index(actual) if actual in ids else 0,
                                    format_func=lambda i: "Mesa {} · {} · Piso {} · {}👤".format(
                                        *m.set_index("id_mesa").loc[i, ["numero", "zona", "piso", "capacidad"]]),
                                    key="mm")
                nobs = st.text_area("Observaciones (opcional)", r.observaciones or "",
                                    placeholder="(ejemplo: alergias, tipo de evento)", key="mo")
                if st.button("💾 Guardar cambios", type="primary"):
                    if accion(lambda: llamar("sp_modificar_reserva", (int(rid), int(mesa), nf, hms(nh), int(npers),
                                                                      nobs.strip() or None)), "Reserva modificada"):
                        st.rerun()
    with tabs[1]:
        c1, c2, c3 = st.columns(3)
        for col, (lbl, e) in zip((c1, c2, c3), (("❌ Cancelar", "CANCELADA"), ("✅ Asistió", "ASISTIO"),
                                                ("🚫 No se presentó", "NO_SHOW"))):
            if col.button(lbl, key=f"e_{e}", use_container_width=True):
                if accion(lambda: llamar("sp_cambiar_estado", (int(rid), e)), f"Estado: {e}"):
                    st.rerun()
    if admin:
        with tabs[2]:
            ok = st.checkbox("Confirmo que quiero eliminar esta reserva definitivamente")
            if st.button("🗑️ Eliminar reserva", disabled=not ok):
                if accion(lambda: llamar("sp_eliminar_reserva", (int(rid),)), "Reserva eliminada"):
                    st.rerun()
    with st.expander("📜 Historial de cambios (auditoría)"):
        st.dataframe(run("SELECT * FROM auditoria_reserva ORDER BY id_auditoria DESC LIMIT 30"),
                     use_container_width=True, hide_index=True)


def pg_dashboard():
    st.header("📊 Dashboard")
    a, b = st.columns(2)
    a.write("Reservas por día de la semana")
    a.bar_chart(run("SELECT DAYNAME(fecha) AS dia, COUNT(*) AS total FROM reserva GROUP BY dia").set_index("dia"))
    b.write("Reservas por hora")
    b.bar_chart(run("SELECT HOUR(hora) AS hora, COUNT(*) AS total FROM reserva GROUP BY hora ORDER BY hora").set_index("hora"))
    c, d = st.columns(2)
    c.write("Reservas por zona")
    c.bar_chart(run("""SELECT z.nombre, COUNT(*) AS total FROM reserva r JOIN mesa m USING(id_mesa)
                       JOIN zona z USING(id_zona) GROUP BY z.nombre""").set_index("nombre"))
    d.write("Reservas por estado")
    d.bar_chart(run("SELECT estado, COUNT(*) AS total FROM reserva GROUP BY estado").set_index("estado"))


def pg_ia():
    st.header("🤖 Predicción de No-Show (árbol de decisión)")
    df = run("""SELECT DAYOFWEEK(fecha) AS dia, HOUR(hora) AS hora, personas,
                DATEDIFF(fecha, fecha_registro) AS anticipacion, (estado='NO_SHOW') AS no_show
                FROM reserva WHERE estado IN ('ASISTIO','NO_SHOW')""")
    X, y = df.drop(columns="no_show"), df["no_show"]
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=42)
    modelo = DecisionTreeClassifier(max_depth=4, random_state=42).fit(Xtr, ytr)
    st.metric("Exactitud del modelo", f"{accuracy_score(yte, modelo.predict(Xte)):.1%}")
    st.write("Importancia de cada variable")
    st.bar_chart(pd.Series(modelo.feature_importances_, index=X.columns))
    c1, c2, c3, c4 = st.columns(4)
    dia = c1.selectbox("Día (1=Dom ... 7=Sáb)", range(1, 8), index=5)
    hora = c2.slider("Hora", 12, 21, 20)
    pers = c3.slider("Personas", 1, 8, 4)
    antic = c4.slider("Días de anticipación", 0, 14, 10)
    prob = modelo.predict_proba(pd.DataFrame([[dia, hora, pers, antic]], columns=X.columns))[0][1]
    st.metric("Probabilidad de no presentarse", f"{prob:.0%}")
    (st.warning if prob > 0.4 else st.success)("Riesgo alto: confirmar por teléfono." if prob > 0.4 else "Riesgo bajo.")


def pg_empleados():
    st.header("👥 Empleados")
    st.dataframe(run("SELECT id_empleado, nombre, codigo AS dni, rol, activo FROM empleado ORDER BY rol, nombre"),
                 use_container_width=True, hide_index=True)
    a, b, c = st.columns([2, 1.5, 1])
    n = a.text_input("Nombre del empleado")
    d = b.text_input("DNI (código)", max_chars=8)
    c.write("")
    if c.button("➕ Agregar", type="primary"):
        if n and len(d) == 8 and d.isdigit():
            if accion(lambda: ejecutar("INSERT INTO empleado(nombre, codigo) VALUES(%s,%s)", (n, d)), "Empleado agregado"):
                st.rerun()
        else:
            st.warning("Escribe el nombre y un DNI de 8 dígitos")
    emp = run("SELECT id_empleado, nombre, activo FROM empleado WHERE rol='EMPLEADO'")
    if len(emp):
        e = st.selectbox("Activar / desactivar", emp.id_empleado,
                         format_func=lambda i: emp.set_index("id_empleado").nombre[i])
        if st.button("Cambiar estado activo"):
            ejecutar("UPDATE empleado SET activo = 1 - activo WHERE id_empleado=%s", (int(e),))
            st.rerun()


# ================= MENU =================
paginas = {"🏠 Inicio": pg_inicio, "📅 Nueva reserva": pg_nueva, "🗂️ Gestionar reservas": pg_gestion}
if admin:
    paginas.update({"📊 Dashboard": pg_dashboard, "🤖 IA: No-Show": pg_ia, "👥 Empleados": pg_empleados})
st.sidebar.markdown(f"## 🍽️ {NOMBRE}")
st.sidebar.write(f"👤 {user['nombre']} · *{'Administrador' if admin else 'Empleado'}*")
op = st.sidebar.radio("Menú", list(paginas))
if st.sidebar.button("🚪 Cerrar sesión"):
    del st.session_state["user"]
    st.rerun()
paginas[op]()

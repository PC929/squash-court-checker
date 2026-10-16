"""壁球場剩位查詢 v2 — 全港 76 間場館

資料來源：康文署 SmartPLAY
API：GET /rest/facility-catalog/api/v1/publ/facilities
     ?distCode=<區碼>&faCode=SQUC&playDate=YYYY-MM-DD
一個 request = 一個分區群 + 一日，回傳早午晚三段、
每間場館每個 30 分鐘時段嘅剩位。4 個分區群 x 3 日 = 12 個 request。
版面跟 v1：揀場館 → 揀日期 → 篩選 → 逐時段顯示。
"""
import streamlit as st
import requests
import base64
from pathlib import Path
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

# Server 行 UTC，日期一定要用香港時間計，唔係半夜 12 點至朝早 8 點會早一日
HK_TZ = ZoneInfo("Asia/Hong_Kong")

st.set_page_config(page_title="壁球場剩位查詢", layout="centered")

# 讀 icon（雙黃點壁球）轉做 data URI，直接嵌喺 hero 入面；
# 搵唔到檔都唔死，最多冇 icon。
# 檔名唔一定要一模一樣：squash-ball-icon 開頭就得（例如 squash-ball-icon (1).png）
_MIME = {".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


def _load_icon():
    folder = Path(__file__).parent
    seen = set()
    candidates = [folder / "squash-ball-icon.png"]
    candidates += [p for p in sorted(folder.glob("squash-ball-icon*"))
                   if p not in seen and not seen.add(p)]
    for p in candidates:
        if not p.is_file():
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        mime = _MIME.get(p.suffix.lower(), "image/png")
        b64 = base64.b64encode(raw).decode()
        return (f'<img src="data:{mime};base64,{b64}" width="40" height="40" '
                f'style="border-radius:50%;vertical-align:-11px;margin-right:10px">')
    return ""


ICON_IMG = _load_icon()

# ---------------- 外觀（Demo C：綠→藍漸變、大圓角白卡、漸變 pill） ----------------
st.markdown("""
<style>
.stApp { background: #f2fbf5; }
.block-container { padding-top: 0.8rem; }
.hero {
    background: linear-gradient(135deg, #1a9e54 0%, #00b4d8 100%);
    color: #fff; border-radius: 20px; padding: 22px 20px; margin-bottom: 16px;
}
.hero h1 { font-size: 30px; margin: 0; color: #fff; }
.hero p { margin: 6px 0 0; opacity: .9; }
.venue-bar { background: #fff; border-radius: 16px; padding: 16px 20px; margin-bottom: 8px;
    border: 1px solid #e6f4ec; box-shadow: 0 2px 10px rgba(26,158,84,0.10); }
.venue-bar .venue { font-size: 28px; font-weight: bold; }
.venue-bar .date { color: #666; font-size: 20px; font-weight: bold; margin-top: 4px; }
.venue-bar .day-total { display: inline-block; background: linear-gradient(135deg, #1a9e54, #00b4d8);
    color: #fff; border-radius: 999px; padding: 8px 18px; font-weight: bold; margin-top: 10px; font-size: 18px; }
.card { background: #fff; border-radius: 18px; padding: 14px 18px; margin-bottom: 10px;
    display: flex; justify-content: space-between; align-items: center;
    box-shadow: 0 2px 10px rgba(26,158,84,0.10); border: 1px solid #e6f4ec; }
.pill { border-radius: 999px; padding: 8px 18px; font-weight: bold; font-size: 14px; white-space: nowrap; }
.avail { background: linear-gradient(135deg, #1a9e54, #00b4d8); color: #fff; }
.full { background: #eef1f0; color: #a0aaa5; }
.group-title { font-size: 24px; font-weight: bold; margin: 20px 4px 10px; color: #1a7a44; }
.footnote { color: #999; font-size: 13px; text-align: center; margin-top: 24px; }
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="hero">
  <h1>{ICON_IMG}壁球場剩位查詢</h1>
  <p>全港壁球場・未來 8 日剩位一覽</p>
</div>
""", unsafe_allow_html=True)

# ---------------- 資料層 ----------------
API_URL = "https://www.smartplay.lcsd.gov.hk/rest/facility-catalog/api/v1/publ/facilities"
REGION_GROUPS = [
    ("港島", "CW,EN,SN,WCH"),
    ("九龍", "KC,KT,SSP,WTS,YTM"),
    ("新界東", "N,SK,ST,TP"),
    ("新界西", "IS,KWT,TW,TM,YL"),
]
# 康文署官方分區排序（立法會文件 HAB470 及 SmartPLAY API 回傳順序一致）
DISTRICTS = [
    ("CW", "中西區"), ("EN", "東區"), ("SN", "南區"), ("WCH", "灣仔區"),
    ("KC", "九龍城區"), ("KT", "觀塘區"), ("SSP", "深水埗區"),
    ("WTS", "黃大仙區"), ("YTM", "油尖旺區"),
    ("IS", "離島區"), ("KWT", "葵青區"), ("N", "北區"), ("SK", "西貢區"),
    ("ST", "沙田區"), ("TP", "大埔區"), ("TW", "荃灣區"),
    ("TM", "屯門區"), ("YL", "元朗區"),
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "zh-hk",
    "Referer": "https://www.smartplay.lcsd.gov.hk/facilities/home",
    "channel": "INTERNET",
}
# 場館名統一：SmartPLAY 寫「歌和老街壁球及乒乓球中心」，app 一律用「歌和老街體育館」
NAME_FIX = {"歌和老街壁球及乒乓球中心": "歌和老街體育館"}

PERIODS = [("morning", "上午段節", "上午"),
           ("afternoon", "下晝段節", "下晝"),
           ("evening", "夜晚段節", "夜晚")]


def _get(url, params):
    """問一次 API，失敗就重試一次。"""
    for _ in range(2):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
    return None


def _pick_fat(fat_list):
    """揀壁球嗰個 fat（faCode=SQUC），冇就用第一個。"""
    for f in fat_list:
        if f.get("faCode") == "SQUC":
            return f
    return fat_list[0] if fat_list else None


def _parse_one(resp, region_name):
    """將一個 response（一個分區群＋一日）拆成場館 list。"""
    venues = []
    if not resp or resp.get("code") != "0":
        return venues
    data = resp["data"]
    for period_key, _, _ in PERIODS:
        for dist in data.get(period_key, {}).get("distList", []):
            for v in dist.get("venueList", []):
                fat = _pick_fat(v.get("fatList", []))
                if not fat:
                    continue
                slots = [(s["ssnStartTime"][:5], s["ssnEndTime"][:5],
                          s["sessionCount"], s["available"])
                         for s in fat.get("sessionList", [])]
                venues.append({
                    "key": f"{v['venueId']}",
                    "name": NAME_FIX.get(v["venueName"], v["venueName"]),
                    "distCode": dist.get("distCode"),
                    "dist": dist.get("distName", "").strip(),
                    "region": region_name,
                    "period": period_key,
                    "slots": slots,
                    "period_total": sum(n for _, _, n, _ in slots),
                })
    # 同一間場館會喺早午晚出現三次，合併做一日總數
    merged = {}
    for v in venues:
        m = merged.setdefault(v["key"], {
            "key": v["key"], "name": v["name"], "distCode": v["distCode"],
            "dist": v["dist"], "region": v["region"],
            "day_total": 0, "periods": {}})
        m["day_total"] += v["period_total"]
        m["periods"][v["period"]] = {"slots": v["slots"], "total": v["period_total"]}
    return list(merged.values())


@st.cache_data(ttl=600)
def fetch_all(play_dates):
    """4 個分區群 x N 日，一次過並行問晒。回傳 {date: [venues]}。"""
    jobs = [(d, region, codes)
            for d in play_dates
            for region, codes in REGION_GROUPS]
    results = {d: [] for d in play_dates}

    def work(job):
        play_date, region, codes = job
        resp = _get(API_URL, {"distCode": codes, "faCode": "SQUC",
                              "playDate": play_date})
        return play_date, _parse_one(resp, region)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(work, j) for j in jobs]
        for f in as_completed(futures):
            play_date, venues = f.result()
            results[play_date].extend(venues)
    return results


# ---------------- 抓數據 ----------------
today_hk = datetime.now(HK_TZ).date()
dates = [(today_hk + timedelta(days=i)).isoformat() for i in range(8)]
weekdays = ["一", "二", "三", "四", "五", "六", "日"]

with st.spinner("問緊 SmartPLAY 攞最新剩位…"):
    all_data = fetch_all(tuple(dates))
    fetched_at = datetime.now(HK_TZ).strftime("%Y-%m-%d %H:%M")

# 防禦：SmartPLAY 有時會 block 自動查詢（尤其朝早 7 點搶場高峰期），
# 攞唔到數據唔好炸 app，顯示提示＋重試掣
if sum(len(v) for v in all_data.values()) == 0:
    fetch_all.clear()  # 清走空結果嘅 cache，重試嗰陣先會真係再問過
    st.error("⚠️ 而家問唔到 SmartPLAY 攞數據，佢哋嘅防禦系統暫時 block 咗自動查詢（朝早 7 點搶場高峰期成日會咁）。")
    st.info("💡 請直接用官方 SmartPLAY app 睇剩位，或者等多陣撳下面再試一次。")
    if st.button("🔄 再試一次"):
        st.rerun()
    st.stop()

# ---------------- 日期（兩個模式共用） ----------------
def _date_label(d):
    dt = date.fromisoformat(d)
    idx = dates.index(d)
    tag = {0: "・今日", 1: "・聽日", 2: "・後日"}.get(idx, "")
    if idx == len(dates) - 2:
        tag += "・最遠可訂日"
    elif idx == len(dates) - 1:
        tag += "・明天預約"
    return f"{dt.month}月{dt.day}日（星期{weekdays[dt.weekday()]}）{tag}"

display_dates = list(reversed(dates))  # 新日在前
date_labels = [_date_label(d) for d in display_dates]

def _date_banner(play_date):
    """最遠可訂日／明天預約提示，兩個模式共用。"""
    if play_date == dates[-2]:
        nxt = date.fromisoformat(play_date) + timedelta(days=1)
        st.info(f"💡 呢日係現時最遠可訂嘅日子，聽朝 7 點會開賣 {nxt.month}月{nxt.day}日。")
    elif play_date == dates[-1]:
        st.info("💡 呢日現時只可觀看，聽朝 7 點開賣後就可以預約（同官方 app 一樣）。")

def _on_dist_change():
    # 轉區之後，舊嘅場館選擇可能唔喺新區個 list 入面，清走佢等佢用返預設
    st.session_state.pop("single_venue", None)

def _jump_to_venue(dist, venue_name, date_label):
    # 注意：一定要經 on_click callback 嚟 set session_state！
    # callback 喺 script 重跑「之前」執行，嗰陣 widget 未起好，set 乜都得；
    # 如果喺 script 主體（mode 個 radio 已經起好之後）先 set，就會炸
    # StreamlitAPIException: cannot be modified after the widget is instantiated
    st.session_state["mode"] = "🔍 查單間場館"
    st.session_state["single_dist"] = dist
    st.session_state["single_venue"] = venue_name
    st.session_state["single_date"] = date_label

# Widget 預設值初始化（每個 browser session 只做一次）：
# 之後啲 widget 唔再傳 index= default，全部經 session_state 攞值。
# 咁 jump 嗰陣 set 值就唔會同 default 打架，唔會再出
# "created with a default value but also had its value set via the Session State API" warning。
if "mode" not in st.session_state:
    st.session_state["mode"] = "🔍 查單間場館"
if "single_dist" not in st.session_state:
    st.session_state["single_dist"] = "深水埗區"

# ---------------- 模式切換 ----------------
mode = st.radio("模式", ["🔍 查單間場館", "🏆 全港剩位排名"], horizontal=True, key="mode")

if mode == "🏆 全港剩位排名":
    # 排名唔使再問 API：all_data 已經有齊 8 日 × 76 間，淨係排序
    day_choice = st.selectbox("揀日期", date_labels, index=0, key="rank_date")
    play_date = display_dates[date_labels.index(day_choice)]
    wd = weekdays[date.fromisoformat(play_date).weekday()]
    _date_banner(play_date)
    scope = st.selectbox("排名範圍", ["全港"] + [name for _, name in DISTRICTS],
                         index=0, key="rank_scope")
    venues = all_data.get(play_date, [])
    if scope != "全港":
        # list comprehension：淨係要啱區嘅場館
        venues = [v for v in venues if v["dist"] == scope]
    ranked = sorted(venues, key=lambda v: v["day_total"], reverse=True)
    st.markdown(f"### 🏆 {play_date}（星期{wd}）・{scope}剩位排名")
    if not ranked:
        st.info("呢日暫時冇數據。")
    medals = ["🥇", "🥈", "🥉"]
    for i, v in enumerate(ranked, 1):
        tag = medals[i - 1] if i <= 3 else f"{i}."
        p = v["periods"]
        m = p.get("morning", {}).get("total", 0)
        a = p.get("afternoon", {}).get("total", 0)
        e = p.get("evening", {}).get("total", 0)
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(
                f'<div class="card"><span>{tag} <b>{v["name"]}・{v["dist"]}</b>'
                f'<br><small>早 {m}・午 {a}・晚 {e} 場</small></span>'
                f'<span class="pill avail">全日 {v["day_total"]} 場</span></div>',
                unsafe_allow_html=True)
        with c2:
            # 墊返少少，等個掣同隔籬綠色 pill 垂直對齊
            st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
            st.button("詳情", key=f"goto_{v['key']}_{play_date}",
                      on_click=_jump_to_venue,
                      args=(v["dist"], v["name"], _date_label(play_date)),
                      help=f"睇{v['name']}喺{play_date}嘅全日詳情")
else:
    # ---------------- 查單間場館（原有流程） ----------------
    dist_names = [name for _, name in DISTRICTS]
    dist_choice = st.selectbox("揀分區", dist_names,
                               key="single_dist", on_change=_on_dist_change)
    dist_code = DISTRICTS[dist_names.index(dist_choice)][0]

    # 場館名單由 8 日數據合併（唔淨係靠今日，驚個別日子 request 失敗）
    seen = {}
    for d in dates:
        for v in all_data.get(d, []):
            if v["distCode"] == dist_code:
                seen.setdefault(v["key"], v)
    all_venues = sorted(seen.values(), key=lambda v: v["name"])
    venue_names = [v["name"] for v in all_venues]

    # 場館預設：歌和老街優先，唔喺呢區就用第一間；
    # jump 過嚟嘅值如果啱用就保留，唔啱（或未 set 過）先至用預設
    if st.session_state.get("single_venue") not in venue_names:
        st.session_state["single_venue"] = (
            "歌和老街體育館" if "歌和老街體育館" in venue_names else venue_names[0])
    choice = st.selectbox("揀場館", venue_names, key="single_venue")
    venue_key = all_venues[venue_names.index(choice)]["key"]
    
    if st.session_state.get("single_date") not in date_labels:
        st.session_state["single_date"] = date_labels[0]  # 預設「明天預約」
    day_choice = st.selectbox("揀日期", date_labels, key="single_date")
    play_date = display_dates[date_labels.index(day_choice)]
    wd = weekdays[date.fromisoformat(play_date).weekday()]
    
    filter_choice = st.radio("篩選", ["全部", "有位", "已滿"], horizontal=True)
    
    _date_banner(play_date)
    
    # ---------------- 場館資訊卡 ----------------
    venue = next((v for v in all_data.get(play_date, []) if v["key"] == venue_key), None)

    if venue is None:
        st.error("搵唔到呢間場館嘅資料。")
    else:
        st.markdown(f"""
        <div class="venue-bar">
          <div class="venue">{venue["name"]}</div>
          <div class="date">{play_date}（星期{wd}）・{venue["region"]}・{venue["dist"]}</div>
          <div class="day-total">全日可預約場次：{venue["day_total"]}</div>
        </div>
        """, unsafe_allow_html=True)

        # ---------------- 三段時段（全部攤開） ----------------
        for period_key, group_name, prefix in PERIODS:
            pdata = venue["periods"].get(period_key, {"slots": [], "total": 0})
            st.markdown(f'<div class="group-title">{group_name}（可預約 {pdata["total"]} 場次）</div>',
                        unsafe_allow_html=True)
            shown = 0
            for start, end, n, avail in pdata["slots"]:
                if filter_choice == "有位" and not avail:
                    continue
                if filter_choice == "已滿" and avail:
                    continue
                shown += 1
                pill = (f'<span class="pill avail">可預約 {n} 場</span>'
                        if avail else '<span class="pill full">已滿</span>')
                st.markdown(f'<div class="card"><span>{prefix} {start} - {end}</span>{pill}</div>',
                            unsafe_allow_html=True)
            if shown == 0:
                st.write("呢個段節冇符合篩選嘅時段")

st.markdown(f"""
<div class="footnote">
資料來源：康文署 SmartPLAY<br>資料更新時間：{fetched_at}
</div>
""", unsafe_allow_html=True)

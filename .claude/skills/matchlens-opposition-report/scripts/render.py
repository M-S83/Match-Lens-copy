#!/usr/bin/env python3
"""Match Lens report renderer.
Usage: python render.py <report.md> <match_data.json> <out.pdf>
report_type in the JSON selects styling/layout. See match_data.schema in README.
"""
import sys, os, re, json, subprocess

HERE=os.path.dirname(os.path.abspath(__file__))
ASSETS=os.path.join(os.path.dirname(HERE),"assets") if os.path.isdir(os.path.join(os.path.dirname(HERE),"assets")) else HERE
CSS=os.path.join(ASSETS,"brand.css")
import viz

GOLD="#F0B429"; GOLDr="rgba(240,180,41,0.5)"
EV={"A":"#1D9E75","B":"#BA7517","C":"#888780"}
TYPE_META={
 "tactical":    {"label":"TACTICAL REPORT","cat":"#2BD58C","short":"Tactical","tl":True,"sm":False,"rail":True,"cards":False,"board":"both","drop_km":True},
 "opposition":  {"label":"OPPOSITION REPORT","cat":"#4D9BFF","short":"Opposition","tl":True,"sm":True,"rail":False,"cards":True,"board":"focus","drop_km":False},
 "flagged":     {"label":"FLAGGED MOMENTS","cat":"#FF6B4A","short":"Moments","tl":True,"sm":False,"rail":True,"cards":False,"board":"both","drop_km":False},
 "pass_network":{"label":"PASS NETWORK","cat":"#A98BFF","short":"Network","tl":False,"sm":False,"rail":False,"cards":False,"board":"both","drop_km":False},
}
UK_PAIRS=[("organization","organisation"),("organizations","organisations"),("organizational","organisational"),
 ("organize","organise"),("organized","organised"),("organizing","organising"),("organizes","organises"),
 ("behavior","behaviour"),("behaviors","behaviours"),("behavioral","behavioural"),
 ("defense","defence"),("defenses","defences"),("offense","offence"),("offenses","offences"),
 ("favor","favour"),("favors","favours"),("favored","favoured"),("favoring","favouring"),("favorite","favourite"),("favorable","favourable"),
 ("center","centre"),("centers","centres"),("centered","centred"),("centering","centring"),
 ("color","colour"),("colors","colours"),("colored","coloured"),
 ("analyze","analyse"),("analyzed","analysed"),("analyzing","analysing"),("analyzes","analyses"),
 ("emphasize","emphasise"),("emphasized","emphasised"),("emphasizing","emphasising"),
 ("recognize","recognise"),("recognized","recognised"),("recognizing","recognising"),
 ("prioritize","prioritise"),("prioritized","prioritised"),("prioritizing","prioritising"),
 ("utilize","utilise"),("utilized","utilised"),("utilizing","utilising"),("utilization","utilisation"),
 ("minimize","minimise"),("minimized","minimised"),("maximize","maximise"),("maximized","maximised"),
 ("modeled","modelled"),("modeling","modelling"),("labeled","labelled"),("labeling","labelling"),
 ("traveled","travelled"),("traveling","travelling"),("canceled","cancelled"),
 ("meter","metre"),("meters","metres"),("maneuver","manoeuvre"),
 ("toward","towards"),("specialize","specialise"),("specialized","specialised")]
def uk_english(t):
    def fac(uk):
        def f(m):
            w=m.group(0)
            if w.isupper(): return uk.upper()
            if w[:1].isupper(): return uk[:1].upper()+uk[1:]
            return uk
        return f
    for us,uk in UK_PAIRS: t=re.sub(r"\b"+us+r"\b",fac(uk),t,flags=re.I)
    return t
def rgba(h,a):
    h=h.lstrip("#"); return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"
def esc(s): return s.replace('"','\\"')
def remove_section(md,name):
    out=[]; skip=False
    for l in md.split("\n"):
        if l.startswith("## ") and l[3:].strip().lower()==name.lower(): skip=True; continue
        if skip and l.startswith("## "): skip=False
        if not skip: out.append(l)
    return "\n".join(out)

def pitch_svg(t):
    W,H,pad,top,bot=300,418,18,46,384; lc="rgba(255,255,255,0.10)"; col=t["color"]; rows=[r[1] for r in t["lines"]]
    s=[f'<svg viewBox="0 0 {W} {H}" width="100%" style="display:block">',
       f'<rect x="2" y="2" width="{W-4}" height="{H-4}" rx="10" fill="#0E141B"/>',
       f'<rect x="{pad}" y="{top-10}" width="{W-2*pad}" height="{bot-top+22}" fill="none" stroke="{lc}" stroke-width="1"/>']
    midY=(top+bot)//2
    s+=[f'<line x1="{pad}" y1="{midY}" x2="{W-pad}" y2="{midY}" stroke="{lc}" stroke-width="1"/>',
        f'<circle cx="{W//2}" cy="{midY}" r="32" fill="none" stroke="{lc}" stroke-width="1"/>',
        f'<rect x="{W//2-46}" y="{bot-14}" width="92" height="36" fill="none" stroke="{lc}" stroke-width="1"/>',
        f'<rect x="{W//2-46}" y="{top-10}" width="92" height="36" fill="none" stroke="{lc}" stroke-width="1"/>',
        f'<text x="{W//2}" y="27" text-anchor="middle" fill="{GOLD}" font-family="PM" font-size="11" letter-spacing="2">{t["formation"]}</text>']
    n=len(rows)
    for i,row in enumerate(rows):
        y=bot-(i/(n-1))*(bot-top)
        for j,p in enumerate(row):
            x=pad+18+((j+0.5)/len(row))*(W-2*pad-36)
            s+=[f'<circle cx="{x:.1f}" cy="{y:.1f}" r="13.5" fill="{col}" stroke="#0E141B" stroke-width="2"/>',
                f'<text x="{x:.1f}" y="{y+4:.1f}" text-anchor="middle" fill="#fff" font-family="PM" font-weight="500" font-size="11">{p[0]}</text>',
                f'<text x="{x:.1f}" y="{y+24:.1f}" text-anchor="middle" fill="#C7CDD4" font-family="SG" font-size="9.5">{p[1]}</text>']
    s.append('</svg>'); return "".join(s)

def board_html(teams):
    if not teams: return ""
    def cell(t):
        subs=", ".join(f'#{s[0]} {s[1]}' for s in t.get("subs",[]))
        sub_html=f'<div class="csubs"><span class="gl">SUBS USED</span> {subs}</div>' if subs else ""
        return (f'<td><div class="pteam"><span class="pd" style="background:{t["color"]}"></span>{t["name"]}</div>'
                f'{pitch_svg(t)}{sub_html}</td>')
    if len(teams)==1:
        inner=f'<table class="bd"><tr><td style="width:22%"></td>{cell(teams[0])}<td style="width:22%"></td></tr></table>'
    else:
        inner=f'<table class="bd"><tr>{cell(teams[0])}{cell(teams[1])}</tr></table>'
    return f'<div class="board"><div class="bdh">Line-ups</div>{inner}</div>'

def parse_profiles(md):
    m=re.search(r"\n## Player Profiles\b", md)
    if not m: return [], md
    start=m.end(); nx=re.search(r"\n## ", md[start:]); end=start+nx.start() if nx else len(md)
    sec=md[start:end]
    name_re=re.compile(r"([A-Z][A-Za-zÀ-ÿ.'\- ]+?)\s*\(#(\d+)\)")
    ms=list(name_re.finditer(sec)); players=[]
    for i,mm in enumerate(ms):
        nm=mm.group(1).strip().lstrip(":").strip(); num=mm.group(2)
        bstart=mm.end(); bend=ms[i+1].start() if i+1<len(ms) else len(sec); block=sec[bstart:bend]
        pos=""; pmm=re.search(r"-\s*([A-Z]{1,3})\s*\*\*", sec[mm.start():bstart+3])
        if pmm: pos=pmm.group(1)
        attrs=[]; grade=""
        for am in re.finditer(r"([A-Za-z0-9][\w\-/ ]{1,28}?):\s*([ABCD])\b", block):
            lab=am.group(1).strip(); g=am.group(2)
            if "overall" in lab.lower() or "profile grade" in lab.lower(): grade=g
            else: attrs.append((lab.replace("-"," ").strip().capitalize(),g))
        if attrs or grade: players.append({"name":nm,"num":num,"pos":pos,"attrs":attrs,"grade":grade})
    cleaned=[]
    for l in sec.split("\n"):
        s=l.strip()
        if re.match(r"^[-*]?\s*\*?\*?[A-Za-z0-9][\w\-/ ]{1,28}\*?\*?:\s*[ABCD]$",s): continue
        if s.lower() in ("**attributes:**","attributes:"): continue
        if s.lower().startswith("**overall profile grade:**"): continue
        cleaned.append(l)
    return players, md[:start]+"\n".join(cleaned)+md[end:]

def main(md_path, data_path, out_path):
    data=json.load(open(data_path,encoding="utf-8"))
    rtype=data.get("report_type","tactical"); M=TYPE_META.get(rtype,TYPE_META["tactical"])
    cat=data.get("category_color") or M["cat"]; label=M["label"]; short=M["short"]
    teams=data.get("teams",{}); focus=data.get("focus_team","home")
    def team_color(side): return teams.get(side,{}).get("color","#888")
    def team_tag(side): return teams.get(side,{}).get("short","")
    raw=open(md_path,encoding="utf-8").read().replace("─","-")
    md="\n".join(l for l in raw.split("\n") if not l.strip().upper().startswith("ROSTER CHECK"))
    md=uk_english(md); md=remove_section(md,"Confirmed Lineups")
    if M["drop_km"]: md=remove_section(md,"Key Moments")
    cards_html=""
    if M["cards"]:
        players, md = parse_profiles(md)
        tcol=team_color(focus)
        if players: cards_html=f'<div class="vizblock">{viz.player_cards(players,tcol)}</div>'
    lines=md.split("\n"); title=data.get("title") or "Match Report"; i0=0
    for i,l in enumerate(lines):
        if l.startswith("# "):
            if not data.get("title"): title=l[2:].strip()
            i0=i; break
    meta=[]; j=i0+1
    while j<len(lines):
        s=lines[j].strip()
        if s=="": j+=1; continue
        if s.startswith("**") and ("**" in s[2:]): meta.append(re.sub(r"\*\*","",s).replace("&nbsp;"," ").strip()); j+=1; continue
        break
    k=j
    while k<len(lines) and lines[k].strip()=="": k+=1
    if k<len(lines) and lines[k].strip()=="---": k+=1
    body_md="\n".join(lines[k:]); meta_str=data.get("meta") or " · ".join(m for m in meta if m)
    html=subprocess.run(["pandoc","-f","gfm","-t","html5","--wrap=none"],input=body_md,capture_output=True,text=True).stdout
    html=re.sub(r"\[([ABC])\]", lambda m:f'<span class="chip"><span class="dot" style="background:{EV[m.group(1)]}"></span>{m.group(1)}</span>', html)
    html=re.sub(r"<p>(<strong>[^<]*\(#\d+\)[^<]*</strong>)</p>", r'<p class="pname">\1</p>', html)
    html=re.sub(r"<td([^>]*)>\s*([ABC])\s*</td>", lambda m:f'<td{m.group(1)}><span class="chip"><span class="dot" style="background:{EV[m.group(2)]}"></span>{m.group(2)}</span></td>', html)
    if M["cards"] and cards_html:
        html=re.sub(r"(<h2[^>]*>\s*Player Profiles\s*</h2>)", lambda m:m.group(1)+cards_html, html, count=1)
    # events/shots with resolved colours
    events=[]
    for e in data.get("events",[]):
        e=dict(e); e["col"]=team_color(e.get("team","home")); e["tag"]=team_tag(e.get("team","home")); events.append(e)
    statband=""
    if data.get("stats"):
        cells="".join(f'<td class="tile"><span class="tl">{s[0]}</span><span class="tv {"cat" if (len(s)>2 and s[2]) else ""}">{s[1]}</span></td>' for s in data["stats"])
        statband=f'<table class="stats"><tr>{cells}</tr></table>'
    tl=f'<div class="vizblock"><div class="vizh">Match timeline</div>{viz.timeline_svg(events, cat)}</div>' if (M["tl"] and events) else ""
    if M["board"]=="focus": bteams=[teams[focus]] if focus in teams else []
    else: bteams=[teams[s] for s in ("home","away") if s in teams]
    board=board_html(bteams)
    sm=""
    if M["sm"] and data.get("shots"):
        fs=[s for s in data["shots"] if s.get("team")==focus] or data["shots"]
        sm=f'<div class="vizblock"><div class="vizh">Shot map</div><div class="shotwrap">{viz.shotmap_svg(fs, cat)}</div></div>'
    rail=f'<div class="vizblock"><div class="vizh">Key moments</div>{viz.rail_html(events)}</div>' if (M["rail"] and events) else ""
    perstyle=(f":root{{--cat:{cat};--catgrid:{rgba(cat,0.10)};--catbd:{rgba(cat,0.5)};--gold:{GOLD};--goldbd:{GOLDr}}}"
              f'.hero{{string-set:rtitle "{esc(short)} · {esc(title)[:38]}", rlabel "{esc(label)}"}}')
    hkey=('<div class="hkey"><span class="kl">EVIDENCE</span>'
          '<span class="ki"><span class="dot" style="background:#1D9E75"></span>A directly observed</span>'
          '<span class="ki"><span class="dot" style="background:#BA7517"></span>B pattern across phases</span>'
          '<span class="ki"><span class="dot" style="background:#888780"></span>C single sighting</span></div>')
    hero=(f'<div class="hero"><table class="mast"><tr><td><span class="wm">Match<b>Lens</b></span></td>'
          f'<td class="r"><span class="lab">{label}</span></td></tr></table><div class="htitle">{title}</div>'
          + (f'<div class="hmeta">{meta_str}</div>' if meta_str else '') + hkey + '</div>')
    doc=(f"<!doctype html><html><head><meta charset='utf-8'><style>{perstyle}</style></head>"
         f"<body>{hero}{statband}{tl}{board}{sm}{rail}{html}</body></html>")
    from weasyprint import HTML
    HTML(string=doc, base_url=ASSETS).write_pdf(out_path, stylesheets=[CSS])
    print("wrote", out_path)

if __name__=="__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])

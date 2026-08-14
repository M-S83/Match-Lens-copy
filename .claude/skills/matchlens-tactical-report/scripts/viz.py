# Generic Match Lens visual renderers (SVG/HTML) for WeasyPrint
TEAMCOL={"BAY":"#D7263D","PSG":"#2D6CDF"}
EVGOAL="#1D9E75"; CARD="#F0B429"

def timeline_svg(events, cat='#888', full=96):
    W,H=760,104; x0,x1=46,716; base=58
    def X(t): return x0+(t/full)*(x1-x0)
    s=[f'<svg viewBox="0 0 {W} {H}" width="100%" style="display:block">']
    s.append(f'<line x1="{x0}" y1="{base}" x2="{x1}" y2="{base}" stroke="{cat}" stroke-width="2"/>')
    for tk in (0,15,30,45,60,75,90):
        s.append(f'<line x1="{X(tk):.0f}" y1="{base-4}" x2="{X(tk):.0f}" y2="{base+4}" stroke="{cat}" stroke-width="1"/>')
        s.append(f'<text x="{X(tk):.0f}" y="{base+18}" text-anchor="middle" fill="#9AA0A8" font-family="PM" font-size="9">{tk}\'</text>')
    for e in events:
        x=X(e["t"]); col=e.get("col","#888")
        if e["type"]=="goal":
            s.append(f'<circle cx="{x:.0f}" cy="{base}" r="7" fill="{col}" stroke="#fff" stroke-width="2"/>')
            s.append(f'<text x="{x:.0f}" y="{base-14}" text-anchor="middle" fill="{col}" font-family="PM" font-weight="500" font-size="9.5">{e["mm"]} {e["who"]}</text>')
        elif e["type"]=="card":
            s.append(f'<rect x="{x-3:.0f}" y="{base-26}" width="6" height="9" rx="1" fill="{CARD}"/>')
            s.append(f'<text x="{x:.0f}" y="{base-30}" text-anchor="middle" fill="#9A7A1E" font-family="PM" font-size="8">{e["mm"]}</text>')
        else:
            s.append(f'<path d="M{x:.0f} {base+10} l5 6 l-5 6 l-5 -6 z" fill="#B4B2A9"/>')
    s.append(f'<text x="{x0}" y="16" fill="#9A7A1E" font-family="PM" font-size="9" letter-spacing="1.5">'
             f'<tspan fill="{EVGOAL}">●</tspan> GOAL  <tspan fill="{CARD}">▮</tspan> CARD  <tspan fill="#B4B2A9">◆</tspan> SUB</text>')
    s.append('</svg>')
    return "".join(s)

def rail_html(events):
    rows=[]
    for e in events:
        col=e.get("col","#888")
        shape=("border-radius:50%;" if e["type"]=="goal" else ("border-radius:2px;" if e["type"]=="card" else "transform:rotate(45deg);"))
        c=(col if e["type"]!="card" else CARD)
        rows.append(f'<div class="rl"><span class="rd" style="background:{c};{shape}"></span>'
                    f'<span class="rt">{e["mm"]}</span> <span class="rx">{e["desc"]} '
                    f'<span class="rg">{e.get("tag","")}</span></span></div>')
    return '<div class="rail">'+"".join(rows)+'</div>'

def shotmap_svg(shots, cat='#F0B429'):
    W,H=360,232
    s=[f'<svg viewBox="0 0 {W} {H}" width="100%" style="display:block">']
    s.append('<rect x="40" y="2" width="280" height="150" fill="none" stroke="rgba(255,255,255,.13)" stroke-width="1"/>')
    s.append('<rect x="120" y="2" width="120" height="62" fill="none" stroke="rgba(255,255,255,.13)" stroke-width="1"/>')
    s.append(f'<rect x="160" y="2" width="40" height="8" fill="none" stroke="{cat}" stroke-width="2"/>')
    OUT={"goal":"#1D9E75","on":"#FFFFFF","off":"#6B7480","blocked":"#BA7517"}
    for sh in shots:
        col=OUT.get(sh["o"],"#888")
        op=("1" if sh["o"] in ("goal","on") else ".6")
        s.append(f'<circle cx="{sh["x"]}" cy="{sh["y"]}" r="6" fill="{col}" fill-opacity="{op}" stroke="none"/>')
    s.append('<text x="180" y="182" text-anchor="middle" fill="#6B7480" font-family="PM" font-size="8.5">'
             '<tspan fill="#1D9E75">●</tspan> goal   <tspan fill="#fff">●</tspan> on target   <tspan fill="#6B7480">●</tspan> off   <tspan fill="#BA7517">●</tspan> blocked</text>')
    s.append('<text x="180" y="200" text-anchor="middle" fill="#6B7480" font-family="PM" font-size="8">indicative placement</text>')
    s.append('</svg>')
    return "".join(s)

GRADE={"A":4,"B":3,"C":2,"D":1}
def grade_bar(g):
    n=GRADE.get(g.upper(),0); seg=""
    for i in range(4):
        c="#2BD58C" if i<n else "#2A3340"
        seg+=f'<i style="width:9pt;height:5pt;background:{c};display:inline-block;margin-left:2pt"></i>'
    return seg

def player_cards(players, color):
    cells=[]
    for p in players:
        rows=""
        for (lab,g) in p["attrs"][:5]:
            rows+=f'<div class="pa">{lab}<span class="pg">{grade_bar(g)}</span></div>'
        num=p.get("num","")
        cells.append(f'<td class="pcard"><div class="ph"><span class="pn" style="background:{color}">{num}</span>'
                     f'<span class="pnm">{p["name"]}<span class="ppos">{p.get("pos","")}</span></span></div>{rows}</td>')
    # 2 per row
    out='<table class="pcards">'
    for i in range(0,len(cells),2):
        pair=cells[i:i+2]
        if len(pair)==1: pair.append('<td class="pcard pcblank"></td>')
        out+='<tr>'+''.join(pair)+'</tr>'
    out+='</table>'
    return out

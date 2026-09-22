#!/usr/bin/env python3
from __future__ import annotations

import csv, hashlib, html, re, time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results"
OUT.mkdir(exist_ok=True)

START_DATE = "2020-01-01"
END_DATE = datetime.now(timezone.utc).date().isoformat()
SESSION = requests.Session()
SESSION.headers.update({"User-Agent":"Ion-TADF-literature-search/1.0 academic research"})

QUERIES = [
    "ionic thermally activated delayed fluorescence",
    "ionic TADF",
    "charged thermally activated delayed fluorescence",
    "cationic thermally activated delayed fluorescence",
    "anionic thermally activated delayed fluorescence",
    "phosphonium TADF",
    "imidazolium TADF",
    "pyridinium TADF",
    "ammonium TADF",
    "counterion TADF",
    "ionic emitter TADF",
    "TADF light-emitting electrochemical cell",
    "TADF light emitting electrochemical cell",
    "TADF LEC",
    "TADF LEEC",
]

ION_TERMS = [
    "ionic","cationic","anionic","charged","phosphonium","imidazolium",
    "pyridinium","ammonium","counterion","counter ion","ion pair","ion-pair",
    "light-emitting electrochemical","light emitting electrochemical",
    "electrochemical self-doping","self-doping"
]

def clean(x: Any) -> str:
    if x is None: return ""
    s = html.unescape(str(x))
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def norm_doi(x: str|None) -> str:
    if not x: return ""
    x=x.strip().lower()
    x=re.sub(r"^https?://(?:dx\.)?doi\.org/","",x)
    x=re.sub(r"^doi:\s*","",x)
    return x.rstrip(" .;,)")

def norm_title(x: str) -> str:
    return re.sub(r"[^a-z0-9]+"," ",clean(x).lower()).strip()

def request_json(url, params=None, retries=5):
    for n in range(retries):
        try:
            r=SESSION.get(url,params=params,timeout=60)
            if r.status_code==429:
                time.sleep(min(60, 2**(n+2))); continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print("request error:", e)
            if n==retries-1: return {}
            time.sleep(min(30,2**(n+1)))
    return {}

@dataclass
class Paper:
    title: str
    abstract: str=""
    authors: list[str]=field(default_factory=list)
    journal: str=""
    date: str=""
    year: str=""
    doi: str=""
    url: str=""
    sources: list[str]=field(default_factory=list)
    queries: list[str]=field(default_factory=list)

def openalex_abstract(inv):
    if not inv: return ""
    words=[]
    for w,poses in inv.items():
        for p in poses: words.append((p,w))
    return " ".join(w for _,w in sorted(words))

def search_openalex():
    out=[]
    for q in QUERIES:
        print("[OpenAlex]",q)
        cursor="*"
        for _ in range(10):
            data=request_json("https://api.openalex.org/works",{
                "search":q,
                "filter":f"from_publication_date:{START_DATE},to_publication_date:{END_DATE}",
                "per-page":200,
                "cursor":cursor,
            })
            rows=data.get("results") or []
            if not rows: break
            for w in rows:
                title=clean(w.get("title"))
                if not title: continue
                doi=norm_doi(w.get("doi"))
                src=((w.get("primary_location") or {}).get("source") or {}).get("display_name","")
                authors=[clean((a.get("author") or {}).get("display_name")) for a in w.get("authorships") or []]
                authors=[x for x in authors if x]
                out.append(Paper(
                    title=title,
                    abstract=openalex_abstract(w.get("abstract_inverted_index")),
                    authors=authors,
                    journal=clean(src),
                    date=clean(w.get("publication_date")),
                    year=str(w.get("publication_year") or ""),
                    doi=doi,
                    url=f"https://doi.org/{doi}" if doi else clean(w.get("id")),
                    sources=["OpenAlex"],queries=[q]))
            cursor=(data.get("meta") or {}).get("next_cursor")
            if not cursor: break
            time.sleep(.15)
    return out

def crossref_date(item):
    for k in ("published-online","published-print","published","issued"):
        dp=((item.get(k) or {}).get("date-parts") or [])
        if dp and dp[0]:
            a=dp[0]
            y=int(a[0]); m=int(a[1]) if len(a)>1 else 1; d=int(a[2]) if len(a)>2 else 1
            return f"{y:04d}-{m:02d}-{d:02d}"
    return ""

def search_crossref():
    out=[]
    for q in QUERIES:
        print("[Crossref]",q)
        cursor="*"
        for _ in range(6):
            data=request_json("https://api.crossref.org/works",{
                "query.bibliographic":q,
                "filter":f"from-pub-date:{START_DATE},until-pub-date:{END_DATE}",
                "rows":1000,"cursor":cursor
            })
            msg=data.get("message") or {}
            items=msg.get("items") or []
            if not items: break
            for it in items:
                titles=it.get("title") or []
                if not titles: continue
                title=clean(titles[0]); doi=norm_doi(it.get("DOI"))
                cont=it.get("container-title") or []
                authors=[]
                for a in it.get("author") or []:
                    n=" ".join(x for x in [clean(a.get("given")),clean(a.get("family"))] if x)
                    if n: authors.append(n)
                d=crossref_date(it)
                out.append(Paper(title=title,abstract=clean(it.get("abstract")),
                    authors=authors,journal=clean(cont[0] if cont else ""),
                    date=d,year=d[:4] if d else "",doi=doi,
                    url=f"https://doi.org/{doi}" if doi else clean(it.get("URL")),
                    sources=["Crossref"],queries=[q]))
            nxt=msg.get("next-cursor")
            if not nxt or nxt==cursor or len(items)<1000: break
            cursor=nxt; time.sleep(.2)
    return out

def merge(records):
    merged={}
    title_map={}
    for p in records:
        key=("doi:"+p.doi) if p.doi else ("title:"+hashlib.sha1(norm_title(p.title).encode()).hexdigest())
        nt=norm_title(p.title)
        if nt in title_map: key=title_map[nt]
        if key not in merged:
            merged[key]=p; title_map[nt]=key; continue
        a=merged[key]
        if len(p.abstract)>len(a.abstract): a.abstract=p.abstract
        if not a.doi and p.doi: a.doi=p.doi
        if not a.journal and p.journal: a.journal=p.journal
        if not a.date and p.date: a.date=p.date
        if not a.year and p.year: a.year=p.year
        if len(p.authors)>len(a.authors): a.authors=p.authors
        if not a.url and p.url: a.url=p.url
        a.sources=sorted(set(a.sources+p.sources))
        a.queries=sorted(set(a.queries+p.queries))
    return list(merged.values())

def relevant(p):
    text=(" ".join([p.title,p.abstract,p.journal])).lower()
    tadf=("thermally activated delayed fluorescence" in text) or ("tadf" in text)
    ionic=any(t in text for t in ION_TERMS)
    return tadf and ionic

def main():
    raw=search_openalex()+search_crossref()
    unique=merge(raw)
    kept=[p for p in unique if relevant(p)]
    kept.sort(key=lambda p:(p.year,p.date,p.title.lower()),reverse=True)

    csv_path=OUT/"ion_tadf_2020_present.csv"
    with csv_path.open("w",newline="",encoding="utf-8-sig") as f:
        fields=["year","date","journal","title","doi","authors","url","sources","matched_queries","abstract"]
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for p in kept:
            w.writerow({
                "year":p.year,"date":p.date,"journal":p.journal,"title":p.title,
                "doi":p.doi,"authors":"; ".join(p.authors),"url":p.url,
                "sources":"; ".join(p.sources),"matched_queries":"; ".join(p.queries),
                "abstract":p.abstract
            })

    md=OUT/"ion_tadf_2020_present.md"
    lines=[f"# Ion-TADF literature, 2020-present","",f"Found **{len(kept)}** candidate papers after deduplication and relevance filtering.",""]
    for i,p in enumerate(kept,1):
        link=p.url or (f"https://doi.org/{p.doi}" if p.doi else "")
        lines.append(f"## {i}. [{p.title}]({link})" if link else f"## {i}. {p.title}")
        lines.append("")
        lines.append(f"- Journal: {p.journal}")
        lines.append(f"- Date: {p.date}")
        lines.append(f"- DOI: {p.doi}")
        lines.append(f"- Sources: {', '.join(p.sources)}")
        lines.append("")
    md.write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"Saved {len(kept)} papers")

if __name__=="__main__":
    main()

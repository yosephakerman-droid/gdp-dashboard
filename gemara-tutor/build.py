"""Build gemara-tutor/index.html from template.html plus texts fetched from Sefaria.

Usage: python3 build.py [Berakhot.2a]

Fetches the Vilna text (Wikisource edition), Rashi, Tosafot and the Steinsaltz
Hebrew explanation for one amud and injects them as JSON into the template.
"""
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

API = "https://www.sefaria.org/api/texts/"
HERE = pathlib.Path(__file__).parent


def fetch(ref, version=None):
    q = {"context": "0", "commentary": "0", "pad": "0"}
    if version:
        q["vhe"] = version
    url = API + urllib.parse.quote(ref) + "?" + urllib.parse.urlencode(q)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def keep_basic_tags(s):
    """Keep <b>, <small>, <big> from the Steinsaltz text; drop everything else."""
    s = re.sub(r"<(?!/?(b|small|big)>)[^>]+>", "", s or "")
    return s.replace("<big>", '<b class="sec">').replace("</big>", "</b>").strip()


def split_dh(s):
    """Split a commentary into (dibbur hamatchil, body)."""
    s = strip_tags(s)
    m = re.search(r"\s[–-]\s", s)
    if m and m.start() < 120:
        return [s[: m.start()].strip(), s[m.end():].strip()]
    return ["", s]


def build(ref):
    g = fetch(ref, "Wikisource Talmud Bavli")
    rashi = fetch("Rashi on " + ref)
    tos = fetch("Tosafot on " + ref)
    stz = fetch("Steinsaltz on " + ref)

    segs = [strip_tags(x) for x in g["he"]]
    n = len(segs)

    def per_seg(arr):
        out = [[] for _ in range(n)]
        for i, comments in enumerate(arr[:n]):
            out[i] = [split_dh(c) for c in comments if strip_tags(c)]
        return out

    stz_he = stz["he"] + [""] * (n - len(stz["he"]))
    return {
        "ref": ref,
        "heRef": g.get("heRef", ref),
        "segments": segs,
        "rashi": per_seg(rashi["he"]),
        "tosafot": per_seg(tos["he"]),
        "steinsaltz": [keep_basic_tags(x) for x in stz_he[:n]],
        "sources": {
            "gemara": [g.get("heVersionTitle"), g.get("license") or g.get("heLicense")],
            "rashi": [rashi.get("heVersionTitle"), rashi.get("heLicense")],
            "tosafot": [tos.get("heVersionTitle"), tos.get("heLicense")],
            "steinsaltz": [stz.get("heVersionTitle"), stz.get("heLicense")],
        },
    }


if __name__ == "__main__":
    ref = sys.argv[1] if len(sys.argv) > 1 else "Berakhot.2a"
    data = build(ref)
    tpl = (HERE / "template.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    (HERE / "index.html").write_text(tpl.replace("/*DAF_DATA*/null", blob), encoding="utf-8")
    print("built", ref, len(data["segments"]), "segments")

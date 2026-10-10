#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
sub_pipeline.py - Subtitulos Text+ (SUB_ARRIBA / SUB_ABAJO) para la timeline
"Sebas_lo_dijo_40s_v4" del proyecto "Lluvias_Sebas_lo_dijo_40s".
DaVinci Resolve Studio 21 (Windows). Solo API de scripting (DaVinciResolveScript):
sin ffmpeg, sin burn-in.

Pasos (en orden; se detiene si falta una fuente o si V4/V5 no son pistas de titulos):
  1. Fuentes: Montserrat Thin y Montserrat Black Italic visibles para Fusion.
  2. Mide los cortes reales de V1 (GetItemListInTrack), los exporta a
     resolve\v1_cortes_medidos.json y los compara con resolve\bloques_sub.json.
  3. Verifica los 11 Text+ de V4/V5: StyledText = nombre del clip = texto esperado,
     in/out = bloque (recortado al clip de V1 si hiciera falta), sin cruzar cortes.
     Corrige el texto si difiere.
  4. Renombra V4 -> SUB_ARRIBA y V5 -> SUB_ABAJO (si ya existen, solo re-aplica) y
     aplica el estilo a cada Text+. Si un clip no es un TextPlus real, lo convierte
     in situ (Fusion comp con TextPlus en la misma posicion; no se mueve nada).
  5. Comprueba que V1, V2, V3 y todo el audio quedaron identicos y borra la pista
     de subtitulos "Subtitle 1" si existe.
  6. Guarda el proyecto y escribe resolve\sub_report.txt y resolve\sub_report.json.
  7. Render H.264 1080x1920 30 fps + AAC a
     resolve\export\Sebas_lo_dijo_40s_v4.mp4 (si no hay nada bloqueante).

Ejecutar:
  a) Dentro de Resolve: Workspace > Console > Py3 y pegar
       exec(open(r"C:\Users\PREDATOR\Downloads\Video_Lluvias\CapCut_Lluvias\historico\resolve\sub_pipeline.py", encoding="utf-8").read())
  b) Desde una terminal (Preferences > System > General > External scripting using = Local):
       python sub_pipeline.py                 # pasos 1-7
       python sub_pipeline.py --solo-medir    # pasos 1-3 sin modificar nada
       python sub_pipeline.py --sin-render    # pasos 1-6
       python sub_pipeline.py --forzar-render # renderiza aunque haya bloqueantes
       python sub_pipeline.py --borrar-v2-v3  # al final borra las timelines v2 y v3
  Idempotente: se puede ejecutar las veces que haga falta.

AAC 320 kbps: la API no expone el bitrate de audio. Si existe un preset de render
llamado RENDER_PRESET (abajo) se carga primero; crealo una vez en Deliver con
MP4 / H.264 / AAC 320 kb/s y "Save as new preset".
"""
from __future__ import print_function

import datetime
import json
import os
import re
import sys
import time
import traceback
import unicodedata

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
PROJECT_NAME = "Lluvias_Sebas_lo_dijo_40s"
TIMELINE_NAME = "Sebas_lo_dijo_40s_v4"
OLD_TIMELINES = ("Sebas_lo_dijo_40s_v2", "Sebas_lo_dijo_40s_v3")

BASE_DIR = r"C:\Users\PREDATOR\Downloads\Video_Lluvias\CapCut_Lluvias\historico"
RESOLVE_DIR = os.path.join(BASE_DIR, "resolve")
BLOQUES_JSON = os.path.join(RESOLVE_DIR, "bloques_sub.json")
CORTES_JSON = os.path.join(RESOLVE_DIR, "v1_cortes_medidos.json")
REPORT_BASE = os.path.join(RESOLVE_DIR, "sub_report")
EXPORT_DIR = os.path.join(RESOLVE_DIR, "export")
EXPORT_NAME = "Sebas_lo_dijo_40s_v4"
RENDER_PRESET = "SUB_H264_AAC320"

SOLO_MEDIR = False
RENDER = True
FORZAR_RENDER = False
BORRAR_V2_V3 = False

FPS = 30
TL_WIDTH, TL_HEIGHT, TL_FRAMES = 1080, 1920, 1192
V1_EXPECTED = ("H00", "H01", "H02", "H03", "H04", "H05", "H06", "R07")

SUB_ARRIBA, SUB_ABAJO = "SUB_ARRIBA", "SUB_ABAJO"
ROLES = (SUB_ARRIBA, SUB_ABAJO)
SUB_DEFAULT_IDX = {SUB_ARRIBA: 4, SUB_ABAJO: 5}

# n, in, out, clip de V1, ARRIBA, ABAJO. Frames de timeline a 30 fps;
# out = primer frame sin texto (= TimelineItem.GetEnd()). Si la timeline usa la
# convencion inclusiva (out + 1) tambien se acepta y se reporta.
BLOQUES = [
    (1, 193, 255, "H01", "somos propensos", "a inundaciones"),
    (2, 400, 443, "H02", None, "paños de agua tibia"),
    (3, 448, 541, "H02", "problemas estructurales", "no avanza en su solución"),
    (4, 679, 719, "H03", "estamos hablando", "de vidas"),
    (5, 821, 884, "H04", "el río tiene", "más de 100 puntos críticos"),
    (6, 928, 1016, "H05", "cada invierno estaremos", "en una sesión de estas"),
]

# Nombres posibles de familia/estilo segun como Windows/Fusion agrupe la familia.
FONT_CANDIDATES = {
    SUB_ARRIBA: [("Montserrat", "Thin"), ("Montserrat Thin", "Regular"),
                 ("Montserrat Thin", "Thin")],
    SUB_ABAJO: [("Montserrat", "Black Italic"), ("Montserrat Black", "Italic"),
                ("Montserrat Black Italic", "Regular"),
                ("Montserrat Black Italic", "Italic")],
}
FONT_LABEL = {SUB_ARRIBA: "Montserrat Thin", SUB_ABAJO: "Montserrat Black Italic"}
FONT_REGISTRY = {
    SUB_ARRIBA: (r"^montserrat thin\s*\((truetype|opentype)\)$",
                 r"montserrat-thin\.(ttf|otf)$"),
    SUB_ABAJO: (r"^montserrat black italic\s*\((truetype|opentype)\)$",
                r"montserrat-blackitalic\.(ttf|otf)$"),
}

# Size, Center X, Center Y
LAYOUT = {SUB_ARRIBA: (0.0739, 0.5, 0.4659), SUB_ABAJO: (0.0627, 0.5, 0.4396)}
OUTLINE = {"thickness": 0.15, "softness": 12.0, "opacity": 1.0, "offset": (0.0, -0.010)}

LINE_MAX_CHARS, LINE_MAX_WORDS, BLOCK_MAX_WORDS = 26, 5, 7
DUR_MIN_S, DUR_MAX_S = 0.8, 3.5
NO_LINE_END = {
    "a", "al", "ante", "bajo", "con", "contra", "de", "del", "desde", "durante",
    "en", "entre", "hacia", "hasta", "mediante", "para", "por", "según", "sin",
    "sobre", "tras", "vía", "el", "la", "lo", "los", "las", "un", "una", "unos",
    "unas", "y", "e", "ni", "o", "u", "pero", "mas", "sino", "que", "porque",
    "pues", "aunque", "si", "su", "sus",
}
TOL = 1e-4


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
class Abort(Exception):
    pass


class Report(object):
    def __init__(self):
        self.lines, self.blockers, self.warnings, self.notes = [], [], [], []
        self.data = {"inicio": datetime.datetime.now().isoformat(timespec="seconds")}

    def out(self, s=""):
        self.lines.append(s)
        try:
            print(s)
        except UnicodeEncodeError:
            print(s.encode("ascii", "replace").decode("ascii"))

    def h(self, title):
        self.out("")
        self.out("=" * 78)
        self.out(title)
        self.out("=" * 78)

    def block(self, s):
        self.blockers.append(s)
        self.out("  [BLOQUEANTE] " + s)

    def warn(self, s):
        self.warnings.append(s)
        self.out("  [AVISO] " + s)

    def note(self, s):
        self.notes.append(s)
        self.out("  [NOTA] " + s)

    def save(self):
        try:
            if not os.path.isdir(RESOLVE_DIR):
                os.makedirs(RESOLVE_DIR)
            with open(REPORT_BASE + ".txt", "w", encoding="utf-8") as f:
                f.write("\n".join(self.lines) + "\n")
            d = dict(self.data)
            d.update(bloqueantes=self.blockers, avisos=self.warnings, notas=self.notes)
            with open(REPORT_BASE + ".json", "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:  # el reporte nunca debe tumbar el script
            print("No se pudo escribir el reporte: %s" % e)


def norm(s):
    if s is None:
        return ""
    return " ".join(unicodedata.normalize("NFC", str(s)).split())


def tc(frames):
    f = int(frames)
    s, fr = divmod(f, FPS)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return "%02d:%02d:%02d:%02d" % (h, m, s, fr)


def call(obj, name, *args):
    """Llama obj.name(*args); None si el metodo no existe o falla."""
    if obj is None:
        return None
    try:
        fn = getattr(obj, name)
    except Exception:
        return None
    if not callable(fn):
        return None
    try:
        return fn(*args)
    except Exception:
        return None


def as_list(x):
    if not x:
        return []
    if isinstance(x, dict):
        return [x[k] for k in sorted(x)]
    return list(x)


def to_float(x, default=None):
    m = re.search(r"[-+]?\d+(\.\d+)?", str(x)) if x is not None else None
    return float(m.group(0)) if m else default


def prefix(name):
    return norm(name)[:3].upper()


def point(v):
    """Lee un input Point de Fusion (dict {1: x, 2: y}, lista o tupla)."""
    if isinstance(v, dict):
        x = v.get(1, v.get(1.0))
        y = v.get(2, v.get(2.0))
        return (x, y) if x is not None and y is not None else None
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return (v[0], v[1])
    return None


def same(got, want):
    if isinstance(want, tuple):
        p = point(got)
        return p is not None and all(abs(float(a) - b) < TOL for a, b in zip(p, want))
    if isinstance(want, (int, float)):
        try:
            return abs(float(got) - want) < TOL
        except (TypeError, ValueError):
            return False
    return norm(got) == norm(want)


def fmt(v):
    p = point(v) if isinstance(v, (dict, list)) else None
    if p:
        return "(%.4f, %.4f)" % (float(p[0]), float(p[1]))
    if isinstance(v, float):
        return "%.4f" % v
    return repr(v)


def items(tl, kind, idx):
    return as_list(tl.GetItemListInTrack(kind, idx))


def describe(item, t0):
    d = {"name": item.GetName(), "start": item.GetStart() - t0,
         "end": item.GetEnd() - t0, "dur": item.GetDuration()}
    for key, fn in (("left_offset", "GetLeftOffset"), ("right_offset", "GetRightOffset"),
                    ("src_start", "GetSourceStartFrame"), ("src_end", "GetSourceEndFrame"),
                    ("uid", "GetUniqueId")):
        d[key] = call(item, fn)
    return d


def snapshot(tl):
    t0 = tl.GetStartFrame()
    snap = {}
    for kind, tag in (("video", "V"), ("audio", "A"), ("subtitle", "S")):
        for i in range(1, (tl.GetTrackCount(kind) or 0) + 1):
            snap["%s%d" % (tag, i)] = {
                "name": tl.GetTrackName(kind, i),
                "items": [describe(it, t0) for it in items(tl, kind, i)],
            }
    return snap


def textplus_of(item):
    """(comp, [TextPlus tools]) del clip; (None, []) si no tiene comp Fusion."""
    n = call(item, "GetFusionCompCount") or 0
    if n < 1:
        return None, []
    comp = call(item, "GetFusionCompByIndex", 1)
    if comp is None:
        return None, []
    return comp, as_list(call(comp, "GetToolList", False, "TextPlus"))


def get_resolve():
    g = globals()
    if g.get("resolve") is not None:
        return g["resolve"]
    if g.get("bmd") is not None:
        r = call(g["bmd"], "scriptapp", "Resolve")
        if r is not None:
            return r
    try:
        import DaVinciResolveScript as dvr
    except ImportError:
        api = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                           "Blackmagic Design", "DaVinci Resolve", "Support",
                           "Developer", "Scripting")
        os.environ.setdefault("RESOLVE_SCRIPT_API", api)
        os.environ.setdefault("RESOLVE_SCRIPT_LIB",
                              r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")
        sys.path.append(os.path.join(api, "Modules"))
        import DaVinciResolveScript as dvr
    return dvr.scriptapp("Resolve")


# ----------------------------------------------------------------------------
# Paso 0 - conexion
# ----------------------------------------------------------------------------
def step0_connect(resolve, rep):
    rep.h("PASO 0 - Conexion con Resolve")
    if resolve is None:
        raise Abort("Sin conexion con Resolve. Abre Resolve y activa "
                    "Preferences > System > General > External scripting using = Local.")
    pm = resolve.GetProjectManager()
    proj = pm.GetCurrentProject() if pm else None
    pname = proj.GetName() if proj else None
    if pname != PROJECT_NAME:
        raise Abort("El proyecto abierto es %r, no %r. No cambio de proyecto por mi cuenta."
                    % (pname, PROJECT_NAME))
    tl, names = None, []
    for i in range(1, (proj.GetTimelineCount() or 0) + 1):
        t = proj.GetTimelineByIndex(i)
        if t is None:
            continue
        names.append(t.GetName())
        if t.GetName() == TIMELINE_NAME:
            tl = t
    if tl is None:
        raise Abort("No existe la timeline %r. Timelines: %s" % (TIMELINE_NAME, names))
    cur = proj.GetCurrentTimeline()
    if cur is None or cur.GetName() != TIMELINE_NAME:
        if not proj.SetCurrentTimeline(tl):
            raise Abort("No pude activar la timeline %r" % TIMELINE_NAME)
    w = int(to_float(tl.GetSetting("timelineResolutionWidth"), 0))
    h = int(to_float(tl.GetSetting("timelineResolutionHeight"), 0))
    fps = to_float(tl.GetSetting("timelineFrameRate"), 0.0)
    t0, t1 = tl.GetStartFrame(), tl.GetEndFrame()
    rep.out("  Proyecto: %s | Timeline: %s" % (pname, TIMELINE_NAME))
    rep.out("  %dx%d @ %s fps | tcStart %s | frames %d..%d (%d) | timelines: %s"
            % (w, h, fps, call(tl, "GetStartTimecode"), t0, t1, t1 - t0, ", ".join(names)))
    if (w, h) != (TL_WIDTH, TL_HEIGHT) or abs(fps - FPS) > 0.01:
        raise Abort("La timeline no es %dx%d @ %d fps" % (TL_WIDTH, TL_HEIGHT, FPS))
    if abs((t1 - t0) - TL_FRAMES) > 1:
        rep.warn("Duracion %d frames (esperado ~%d)" % (t1 - t0, TL_FRAMES))
    rep.data["timeline"] = {"name": TIMELINE_NAME, "width": w, "height": h, "fps": fps,
                            "start_frame": t0, "end_frame": t1, "timelines": names}
    return pm, proj, tl


# ----------------------------------------------------------------------------
# Paso 1 - fuentes
# ----------------------------------------------------------------------------
def fusion_fonts(resolve):
    fu = call(resolve, "Fusion")
    if fu is None:
        return None
    try:
        fm = fu.FontManager
    except Exception:
        fm = None
    fl = call(fm, "GetFontList")
    if not isinstance(fl, dict) or not fl:
        return None
    out = {}
    for fam, styles in fl.items():
        if isinstance(styles, dict):
            out[str(fam)] = dict((str(k), v) for k, v in styles.items())
        elif isinstance(styles, (list, tuple)):
            out[str(fam)] = dict((str(s), None) for s in styles)
        else:
            out[str(fam)] = {}
    return out


def registry_fonts():
    try:
        import winreg
    except ImportError:
        return None
    res = []
    for hive, scope in ((winreg.HKEY_LOCAL_MACHINE, "todos los usuarios"),
                        (winreg.HKEY_CURRENT_USER, "solo este usuario")):
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
        except OSError:
            continue
        i = 0
        while True:
            try:
                name, val, _ = winreg.EnumValue(key, i)
            except OSError:
                break
            i += 1
            if "montserrat" in name.lower() or "montserrat" in str(val).lower():
                res.append((name, str(val), scope))
        winreg.CloseKey(key)
    return res


def step1_fonts(resolve, rep):
    rep.h("PASO 1 - Fuentes")
    ff = fusion_fonts(resolve)
    reg = registry_fonts()
    if ff is None:
        rep.warn("No pude leer el FontManager de Fusion; uso el registro de Windows.")
    else:
        mont = dict((k, v) for k, v in ff.items() if "montserrat" in k.lower())
        rep.out("  Fusion ve %d familias; Montserrat: %s" % (
            len(ff), "; ".join("%s [%s]" % (k, ", ".join(sorted(v))) for k, v in sorted(mont.items()))
            or "ninguna"))
    if reg is not None:
        rep.out("  Registro de Windows (Montserrat): %s" % (
            "; ".join("%s (%s)" % (n, s) for n, _, s in reg) or "ninguna"))

    resolved, missing = {}, []
    for role in ROLES:
        hit = None
        if ff:
            low = dict((k.lower(), k) for k in ff)
            for fam, sty in FONT_CANDIDATES[role]:
                real_fam = low.get(fam.lower())
                if not real_fam:
                    continue
                for s, path in ff[real_fam].items():
                    if s.lower() == sty.lower():
                        hit = (real_fam, s, path)
                        break
                if hit:
                    break
        rx_name, rx_file = FONT_REGISTRY[role]
        reg_hits = [r for r in (reg or [])
                    if re.search(rx_name, r[0].strip().lower()) or re.search(rx_file, r[1].lower())]
        if hit:
            resolved[role] = hit
            rep.out("  OK %-24s -> Font=%r Style=%r  %s" % (FONT_LABEL[role], hit[0], hit[1], hit[2] or ""))
        elif ff is None and reg_hits:
            fam, sty = FONT_CANDIDATES[role][0]
            resolved[role] = (fam, sty, reg_hits[0][1])
            rep.warn("%s confirmada solo por el registro (%s); se usa Font=%r Style=%r"
                     % (FONT_LABEL[role], reg_hits[0][2], fam, sty))
        else:
            why = "no instalada"
            if reg_hits:
                why = ("instalada en Windows (%s) pero Fusion no la lista: instalala 'para todos "
                       "los usuarios' y reinicia Resolve" % reg_hits[0][2])
            elif reg and any("variable" in r[1].lower() or "[wght]" in r[1].lower() for r in reg):
                why = "solo esta la Montserrat variable; instala los .ttf estaticos"
            missing.append("%s: %s" % (FONT_LABEL[role], why))
    rep.data["fuentes"] = dict((r, {"font": v[0], "style": v[1], "file": v[2]})
                               for r, v in resolved.items())
    if missing:
        raise Abort("Faltan fuentes (no sustituyo): " + " | ".join(missing))
    return resolved


# ----------------------------------------------------------------------------
# Paso 2 - cortes de V1
# ----------------------------------------------------------------------------
def walk_dicts(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            for d in walk_dicts(v):
                yield d
    elif isinstance(o, list):
        for v in o:
            for d in walk_dicts(v):
                yield d


def compare_json(v1, rep):
    rep.out("")
    rep.out("  Comparacion con bloques_sub.json:")
    if not os.path.isfile(BLOQUES_JSON):
        rep.warn("No existe %s" % BLOQUES_JSON)
        return
    try:
        with open(BLOQUES_JSON, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        rep.warn("No pude leer bloques_sub.json: %s" % e)
        return

    for d in walk_dicts(data):
        if "fps" in d and abs(to_float(d["fps"], FPS) - FPS) > 1e-3:
            rep.warn("bloques_sub.json dice fps=%s" % d["fps"])

    # Bloques (dicts con tl_start_f / tl_end_f)
    jblocks = [d for d in walk_dicts(data) if "tl_start_f" in d and "tl_end_f" in d]
    if not jblocks:
        rep.warn("bloques_sub.json no tiene entradas con tl_start_f/tl_end_f")
    used = set()
    for nb, s, e, clip, _, _ in BLOQUES:
        js = [d for d in jblocks if int(round(to_float(d["tl_start_f"], -1))) == s]
        if not js:
            js = [d for d in jblocks if to_float(d["tl_start_f"], 0) < e and to_float(d["tl_end_f"], 0) > s]
        used.update(id(d) for d in js)
        if not js:
            rep.warn("B%d %d-%d: no esta en bloques_sub.json" % (nb, s, e))
            continue
        for d in js:
            js_, je = int(round(to_float(d["tl_start_f"]))), int(round(to_float(d["tl_end_f"])))
            texts = " | ".join(norm(v) for v in d.values() if isinstance(v, str))
            if js_ == s and je in (e - 1, e, e + 1):
                rep.out("    B%d %4d-%4d = JSON %4d-%4d  %s" % (nb, s, e, js_, je, texts))
            else:
                rep.warn("B%d esperado %d-%d, JSON %d-%d (%s); manda lo definido + V1 medido"
                         % (nb, s, e, js_, je, texts))
    for d in jblocks:
        if id(d) not in used:
            rep.warn("Entrada de bloques_sub.json sin bloque definido: %s" % json.dumps(d, ensure_ascii=False))

    # Offsets por clip: cualquier dict cuyo valor o clave empiece por H0x/R0x.
    prefixes = set(prefix(c["name"]) for c in v1)
    recs = []
    for d in walk_dicts(data):
        if "tl_start_f" in d:
            continue
        label = next((norm(v) for v in d.values() if isinstance(v, str) and prefix(v) in prefixes), None)
        if label:
            recs.append((label, dict((k, v) for k, v in d.items() if isinstance(v, (int, float)))))
        for k, v in d.items():
            if prefix(k) in prefixes and isinstance(v, (int, float)):
                recs.append((k, {"offset": v}))
            elif prefix(k) in prefixes and isinstance(v, dict):
                recs.append((k, dict((kk, vv) for kk, vv in v.items() if isinstance(vv, (int, float)))))
    for label, nums in recs:
        meas = [c for c in v1 if prefix(c["name"]) == prefix(label)]
        if not meas or not nums:
            continue
        c = meas[0]
        diffs = []
        for k, v in nums.items():
            kl = k.lower()
            if re.search(r"src|source|media|asset", kl):
                continue
            if "dur" in kl:
                ref = c["dur"]
            elif re.search(r"end|out", kl):
                ref = c["end"]
            elif re.search(r"start|offset|in|tl|rec", kl):
                ref = c["start"]
            else:
                continue
            if ref not in (int(round(v)), int(round(v * FPS))):
                diffs.append("%s=%s (medido %d)" % (k, v, ref))
        if diffs:
            rep.warn("Clip %s: JSON difiere de V1 medido: %s" % (label, ", ".join(diffs)))
        else:
            rep.out("    Clip %-34s JSON = V1 medido" % label)


def step2_v1(snap, rep):
    rep.h("PASO 2 - Cortes reales de V1 (GetItemListInTrack)")
    if "V1" not in snap:
        raise Abort("La timeline no tiene V1")
    v1 = snap["V1"]["items"]
    rep.out("   # clip                                  in    out   dur  TC in        TC out")
    for i, c in enumerate(v1, 1):
        rep.out("  %2d %-36s %5d  %5d  %4d  %s  %s"
                % (i, c["name"], c["start"], c["end"], c["dur"], tc(c["start"]), tc(c["end"])))
    rep.out("  Cortes (frame donde empieza cada clip): %s"
            % ", ".join(str(c["start"]) for c in v1[1:]))
    got = tuple(prefix(c["name"]) for c in v1)
    if got != V1_EXPECTED:
        rep.warn("V1 tiene %d clips %s; esperado %s" % (len(v1), list(got), list(V1_EXPECTED)))
    for a, b in zip(v1, v1[1:]):
        if b["start"] != a["end"]:
            rep.warn("V1: %s termina en %d y %s empieza en %d (%s)" % (
                a["name"], a["end"], b["name"], b["start"],
                "hueco" if b["start"] > a["end"] else "solape"))
    try:
        with open(CORTES_JSON, "w", encoding="utf-8") as f:
            json.dump({"timeline": TIMELINE_NAME, "fps": FPS, "v1": v1}, f, ensure_ascii=False, indent=2)
        rep.out("  Exportado: %s" % CORTES_JSON)
    except Exception as e:
        rep.warn("No pude escribir %s: %s" % (CORTES_JSON, e))
    rep.data["v1"] = v1
    compare_json(v1, rep)
    return v1


# ----------------------------------------------------------------------------
# Paso 3 - verificacion de texto y tiempos
# ----------------------------------------------------------------------------
def clip_for(v1, pfx, s, e):
    cands = [c for c in v1 if prefix(c["name"]) == pfx]
    if not cands:
        return None
    return max(cands, key=lambda c: min(e, c["end"]) - max(s, c["start"]))


def v1_at(v1, f):
    return next((c for c in v1 if c["start"] <= f < c["end"]), None)


def text_rules(rep):
    rep.out("")
    rep.out("  Reglas de texto (solo se reportan; los bloques los definiste tu):")
    for nb, s, e, _, up, down in BLOQUES:
        lines = [l for l in (up, down) if l]
        words = sum(len(l.split()) for l in lines)
        msgs = []
        for l in lines:
            if len(l) > LINE_MAX_CHARS:
                msgs.append("'%s' %d caracteres (>%d)" % (l, len(l), LINE_MAX_CHARS))
            if len(l.split()) > LINE_MAX_WORDS:
                msgs.append("'%s' %d palabras (>%d)" % (l, len(l.split()), LINE_MAX_WORDS))
            if l.rstrip()[-1:] in ".,;:":
                msgs.append("'%s' termina en puntuacion" % l)
        if words > BLOCK_MAX_WORDS:
            msgs.append("%d palabras en el bloque (max ~%d)" % (words, BLOCK_MAX_WORDS))
        if words <= 4 and len(lines) == 2:
            one = " ".join(lines)
            if len(one) <= LINE_MAX_CHARS:
                msgs.append("<=4 palabras: la regla pide 1 linea en SUB_ABAJO ('%s', %d car.)"
                            % (one, len(one)))
            else:
                rep.out("    B%d en 2 lineas aunque tiene <=4 palabras: en 1 linea serian %d car. (>%d)"
                        % (nb, len(one), LINE_MAX_CHARS))
        if up and up.split()[-1].lower() in NO_LINE_END:
            msgs.append("la linea ARRIBA termina en '%s'" % up.split()[-1])
        dur = (e - s) / float(FPS)
        if not DUR_MIN_S <= dur <= DUR_MAX_S:
            msgs.append("duracion %.2f s fuera de %.1f-%.1f s" % (dur, DUR_MIN_S, DUR_MAX_S))
        if msgs:
            for m in msgs:
                rep.note("B%d: %s" % (nb, m))
        else:
            rep.out("    B%d OK (%d palabras, %.2f s)" % (nb, words, dur))


def step3_subs(tl, v1, opts, rep):
    rep.h("PASO 3 - Verificacion de los Text+ (texto y tiempos)")
    n = tl.GetTrackCount("video") or 0
    names = dict((i, tl.GetTrackName("video", i)) for i in range(1, n + 1))
    idx = {}
    for role in ROLES:
        hits = [i for i in sorted(names) if names[i] == role]
        idx[role] = hits[0] if hits else SUB_DEFAULT_IDX[role]
    if idx[SUB_ARRIBA] == idx[SUB_ABAJO] or max(idx.values()) > n:
        raise Abort("No encuentro dos pistas de subtitulos distintas (pistas: %s)" % names)
    for role, i in idx.items():
        other = SUB_ABAJO if role == SUB_ARRIBA else SUB_ARRIBA
        if names[i] == other:
            raise Abort("V%d ya se llama %s; no se puede usar como %s" % (i, other, role))
    if sorted(idx.values()) != [n - 1, n]:
        above = [i for i in range(max(idx.values()) + 1, n + 1) if items(tl, "video", i)]
        msg = "Las pistas de subtitulos (V%d, V%d) no son las dos superiores (hay %d pistas)" % (
            idx[SUB_ARRIBA], idx[SUB_ABAJO], n)
        if above:
            rep.block(msg + "; con clips encima en V%s" % above)
        else:
            rep.warn(msg + "; las de encima estan vacias")

    t0 = tl.GetStartFrame()
    pools = {}
    for role in ROLES:
        i = idx[role]
        pool = []
        for it in items(tl, "video", i):
            if call(it, "GetMediaPoolItem") is not None:
                raise Abort("V%d contiene media (%s), no solo titulos: no la toco"
                            % (i, it.GetName()))
            comp, tools = textplus_of(it)
            pool.append({"item": it, "name": it.GetName(), "start": it.GetStart() - t0,
                         "end": it.GetEnd() - t0, "comp": comp, "tools": tools,
                         "styled": call(tools[0], "GetInput", "StyledText") if tools else None})
        pools[role] = pool
        rep.out("  V%d '%s' -> %s: %d clips" % (i, names[i], role, len(pool)))

    entries = []
    for nb, s, e, clip, up, down in BLOQUES:
        c = clip_for(v1, clip, s, e)
        for role, text in ((SUB_ARRIBA, up), (SUB_ABAJO, down)):
            if not text:
                continue
            x = {"block": nb, "role": role, "track": idx[role], "text": text, "s": s, "e": e,
                 "clip": clip, "issues": []}
            if c is None:
                rep.block("B%d %s: no hay clip %s en V1" % (nb, role, clip))
                x["s2"], x["e2"] = s, e
            else:
                x["clip_name"], x["clip_range"] = c["name"], (c["start"], c["end"])
                x["s2"], x["e2"] = max(s, c["start"]), min(e, c["end"])
                if x["s2"] >= x["e2"]:
                    rep.block("B%d: %d-%d no solapa con %s (%d-%d)" % (nb, s, e, c["name"], c["start"], c["end"]))
                elif (x["s2"], x["e2"]) != (s, e):
                    rep.warn("B%d: %d-%d no cabe en %s (%d-%d) -> recortado a %d-%d"
                             % (nb, s, e, c["name"], c["start"], c["end"], x["s2"], x["e2"]))
            entries.append(x)

    for role in ROLES:
        pool = list(pools[role])
        for x in [x for x in entries if x["role"] == role]:
            m = next((p for p in pool if p["start"] == x["s2"]), None)
            if m is None:
                m = next((p for p in pool if norm(x["text"]) in (norm(p["styled"]), norm(p["name"]))), None)
            if m is None:
                m = next((p for p in pool if p["start"] < x["e2"] and p["end"] > x["s2"]), None)
            if m is not None:
                pool.remove(m)
                x.update(m)
        for p in pool:
            rep.block("%s tiene un clip que no corresponde a ningun bloque: '%s' %d-%d"
                      % (role, p["name"], p["start"], p["end"]))

    convention = set()
    for x in entries:
        tag = "B%d %s" % (x["block"], x["role"])
        if "item" not in x:
            rep.block("%s '%s': no hay Text+ en V%d" % (tag, x["text"], x["track"]))
            continue
        # tiempos
        ok_start = x["start"] == x["s2"]
        if x["end"] == x["e2"]:
            convention.add("exclusivo")
            ok_end = True
        else:
            ok_end = x["end"] == x["e2"] + 1 and x["e2"] < x.get("clip_range", (0, 10 ** 9))[1]
            if ok_end:
                convention.add("inclusivo (+1)")
        if not (ok_start and ok_end):
            rep.block("%s '%s': esta en %d-%d, debe ser %d-%d. La API no mueve ni recorta clips: "
                      "ajustalo en el Edit page y vuelve a ejecutar." % (
                          tag, x["text"], x["start"], x["end"], x["s2"], x["e2"]))
        c = v1_at(v1, x["start"])
        if c is None or x["end"] > c["end"]:
            rep.block("%s cruza un corte de V1 (%d-%d)" % (tag, x["start"], x["end"]))
        elif prefix(c["name"]) != x["clip"]:
            rep.block("%s cae sobre %s, no sobre %s" % (tag, c["name"], x["clip"]))
        dur = (x["end"] - x["start"]) / float(FPS)
        if not DUR_MIN_S <= dur <= DUR_MAX_S:
            rep.warn("%s dura %.2f s (fuera de %.1f-%.1f s)" % (tag, dur, DUR_MIN_S, DUR_MAX_S))
        # tipo de clip
        if not x["tools"]:
            rep.warn("%s '%s' no es un TextPlus real (%s); se convertira in situ en el paso 4"
                     % (tag, x["name"], "sin comp Fusion" if x["comp"] is None else "comp sin TextPlus"))
        elif len(x["tools"]) > 1:
            rep.warn("%s tiene %d TextPlus en la comp; se estilan todos" % (tag, len(x["tools"])))
        # texto
        if x["tools"] and norm(x["styled"]) != norm(x["text"]):
            if opts.solo_medir:
                rep.out("    %s StyledText %r != %r (se corregiria)" % (tag, x["styled"], x["text"]))
            else:
                for t in x["tools"]:
                    t.SetInput("StyledText", x["text"])
                now = call(x["tools"][0], "GetInput", "StyledText")
                if norm(now) == norm(x["text"]):
                    rep.out("    %s StyledText corregido: %r -> %r" % (tag, x["styled"], now))
                    x["styled"] = now
                else:
                    rep.block("%s no pude fijar StyledText (%r)" % (tag, now))
        if norm(x["name"]) != norm(x["text"]):
            if opts.solo_medir:
                rep.out("    %s nombre %r != %r (se corregiria)" % (tag, x["name"], x["text"]))
            else:
                call(x["item"], "SetName", x["text"])
                now = call(x["item"], "GetName")
                if norm(now) == norm(x["text"]):
                    rep.out("    %s nombre corregido: %r -> %r" % (tag, x["name"], now))
                    x["name"] = now
                else:
                    rep.warn("%s nombre del clip %r != %r (la API no lo renombra; el texto "
                             "renderizado es el StyledText)" % (tag, x["name"], x["text"]))
        if x["tools"] and norm(x["styled"]) == norm(x["text"]) and ok_start and ok_end:
            rep.out("    %s OK  %4d-%4d  '%s'" % (tag, x["start"], x["end"], x["text"]))
    if convention:
        rep.out("  Convencion de 'out' en la timeline: %s" % ", ".join(sorted(convention)))
    found = sum(1 for x in entries if "item" in x)
    rep.out("  Text+ encontrados: %d de %d" % (found, len(entries)))
    text_rules(rep)
    return {"idx": idx, "names": names, "entries": entries}


# ----------------------------------------------------------------------------
# Paso 4 - pistas SUB_ y estilo
# ----------------------------------------------------------------------------
def input_map(tool):
    m = {}
    for inp in as_list(call(tool, "GetInputList")):
        a = call(inp, "GetAttrs") or {}
        iid = a.get("INPS_ID")
        if iid:
            m[str(iid)] = (inp, a.get("INPS_DataType"))
    return m


def set_input(tool, imap, iid, value):
    """Fija un input y lo lee de vuelta. Devuelve (estado, valor_leido)."""
    if iid not in imap:
        return "missing", None
    inp = imap[iid][0]
    if call(inp, "GetConnectedOutput") is not None:
        return "animado", call(tool, "GetInput", iid)
    if isinstance(value, tuple):
        tool.SetInput(iid, {1: value[0], 2: value[1]})
        got = tool.GetInput(iid)
        if not same(got, value):
            tool.SetInput(iid, [value[0], value[1]])
            got = tool.GetInput(iid)
    else:
        tool.SetInput(iid, value)
        got = tool.GetInput(iid)
    return ("ok" if same(got, value) else "difiere"), got


def suggest(imap, *words):
    return sorted(i for i in imap if any(w.lower() in i.lower() for w in words))[:12]


def style_tool(tool, role, font, tag, rep):
    size, cx, cy = LAYOUT[role]
    o = OUTLINE
    # (etiqueta, IDs candidatos, valor, obligatorio)
    spec = [
        ("Font", ["Font"], font[0], True),
        ("Style", ["Style"], font[1], True),
        ("Size", ["Size"], size, True),
        ("Center", ["Center"], (cx, cy), True),
        ("Elem1 on", ["Enabled1"], 1.0, False),
        ("Texto R", ["Red1"], 1.0, True),
        ("Texto G", ["Green1"], 1.0, True),
        ("Texto B", ["Blue1"], 1.0, True),
        ("Texto A", ["Alpha1"], 1.0, False),
        ("Elem2 on", ["Enabled2"], 1.0, True),
        ("Elem2 R", ["Red2"], 0.0, True),
        ("Elem2 G", ["Green2"], 0.0, True),
        ("Elem2 B", ["Blue2"], 0.0, True),
        ("Elem2 A", ["Alpha2"], 1.0, False),
        ("Elem2 Opacity", ["Opacity2"], o["opacity"], False),
        ("Elem2 Thickness", ["Thickness2"], o["thickness"], True),
        ("Elem2 Offset", ["Offset2"], o["offset"], True),
        ("Elem3 on", ["Enabled3"], 0.0, True),
    ]
    imap = input_map(tool)
    if not imap:
        rep.block("%s: no pude listar los inputs del TextPlus" % tag)
        return {}
    used, problems = {}, []
    for label, ids, value, required in spec:
        iid = next((i for i in ids if i in imap), None)
        if iid is None:
            msg = "%s: input %s no existe" % (label, "/".join(ids))
            if required:
                problems.append(msg + " (similares: %s)" % suggest(imap, ids[0][:-1] if ids[0][-1].isdigit() else ids[0]))
            continue
        st, got = set_input(tool, imap, iid, value)
        used[iid] = fmt(got)
        if st != "ok":
            problems.append("%s (%s): %s, leido %s" % (label, iid, st, fmt(got)))

    # Softness: SoftnessX2/SoftnessY2 o Softness2
    soft_ids = [i for i in ("SoftnessX2", "SoftnessY2") if i in imap] or \
               [i for i in ("Softness2",) if i in imap]
    if not soft_ids:
        problems.append("Elem2 Softness: no existe (similares: %s)" % suggest(imap, "Soft"))
    for iid in soft_ids:
        st, got = set_input(tool, imap, iid, o["softness"])
        used[iid] = fmt(got)
        if st != "ok":
            problems.append("Elem2 Softness (%s): %s, leido %s" % (iid, st, fmt(got)))

    # CharacterOffset: a cero / desactivado (point -> (0,0), numero -> 0)
    co = [i for i in imap if "characteroffset" in i.lower()]
    for iid in co:
        dtype = str(imap[iid][1] or "")
        st, got = set_input(tool, imap, iid, (0.0, 0.0) if dtype == "Point" else 0.0)
        used[iid] = fmt(got)
        if st != "ok":
            problems.append("CharacterOffset (%s): %s, leido %s" % (iid, st, fmt(got)))

    # Resolucion del Text+: debe ser la de la timeline
    if "Width" in imap and "Height" in imap:
        w, h = tool.GetInput("Width"), tool.GetInput("Height")
        uff = tool.GetInput("UseFrameFormatSettings") if "UseFrameFormatSettings" in imap else None
        if (to_float(w, 0), to_float(h, 0)) != (TL_WIDTH, TL_HEIGHT) and not uff:
            set_input(tool, imap, "Width", float(TL_WIDTH))
            set_input(tool, imap, "Height", float(TL_HEIGHT))
            w, h = tool.GetInput("Width"), tool.GetInput("Height")
        used["Width x Height"] = "%s x %s%s" % (w, h, " (frame format)" if uff else "")

    for p in problems:
        rep.block("%s %s" % (tag, p))
    rb = {
        "Font": call(tool, "GetInput", "Font"), "Style": call(tool, "GetInput", "Style"),
        "Size": call(tool, "GetInput", "Size"), "Center": point(call(tool, "GetInput", "Center")),
        "StyledText": call(tool, "GetInput", "StyledText"),
        "CharacterOffset_inputs": co, "inputs_fijados": used,
        "otros": dict((k, fmt(call(tool, "GetInput", k))) for k in
                      ("LayoutType", "HorizontalJustificationNew", "VerticalJustificationNew",
                       "LineSpacing", "CharacterSpacing", "ElementShape2", "Level2") if k in imap),
    }
    return rb


def convert_in_place(x, rep):
    """Clip que no es TextPlus: crea comp Fusion con TextPlus -> MediaOut en el mismo clip."""
    tag = "B%d %s" % (x["block"], x["role"])
    it = x["item"]
    comp = x["comp"] or call(it, "AddFusionComp")
    if comp is None:
        rep.block("%s: no pude crear una comp Fusion en '%s'" % (tag, x["name"]))
        return False
    tp = call(comp, "AddTool", "TextPlus", -32768, -32768)
    mo = next(iter(as_list(call(comp, "GetToolList", False, "MediaOut"))), None)
    if tp is None or mo is None:
        rep.block("%s: no pude anadir TextPlus/MediaOut en la comp" % tag)
        return False
    tp.SetInput("StyledText", x["text"])
    mo.ConnectInput("Input", tp)
    x["comp"], x["tools"], x["styled"] = comp, [tp], tp.GetInput("StyledText")
    rep.warn("%s: convertido in situ a TextPlus (misma posicion %d-%d)" % (tag, x["start"], x["end"]))
    return True


def step4_style(tl, subs, fonts, rep):
    rep.h("PASO 4 - Pistas SUB_ARRIBA / SUB_ABAJO y estilo Text+")
    for role in ROLES:
        i = subs["idx"][role]
        cur = tl.GetTrackName("video", i)
        if cur == role:
            rep.out("  V%d ya se llama %s (solo se re-aplica el estilo)" % (i, role))
            continue
        tl.SetTrackName("video", i, role)
        now = tl.GetTrackName("video", i)
        if now == role:
            rep.out("  V%d '%s' -> '%s'" % (i, cur, now))
        else:
            rep.block("No pude renombrar V%d a %s (quedo %r)" % (i, role, now))
    for x in subs["entries"]:
        if "item" not in x:
            continue
        tag = "B%d %s" % (x["block"], x["role"])
        if not x["tools"] and not convert_in_place(x, rep):
            continue
        comp = x["comp"]
        call(comp, "Lock")
        call(comp, "StartUndo", "SUB estilo")
        try:
            rbs = [style_tool(t, x["role"], fonts[x["role"]], tag, rep) for t in x["tools"]]
        finally:
            call(comp, "EndUndo", True)
            call(comp, "Unlock")
        x["readback"] = rbs[0] if rbs else {}
        rb = x["readback"]
        rep.out("    %s V%d %4d-%4d  Font=%r Style=%r Size=%s Center=%s  '%s'" % (
            tag, x["track"], x["start"], x["end"], rb.get("Font"), rb.get("Style"),
            fmt(rb.get("Size")), fmt(rb.get("Center")), norm(rb.get("StyledText"))))
        if rb.get("CharacterOffset_inputs") == []:
            x["co_note"] = "sin input CharacterOffset"


# ----------------------------------------------------------------------------
# Paso 5 - integridad y pista Subtitle 1
# ----------------------------------------------------------------------------
FIELDS_FULL = ("name", "start", "end", "dur", "left_offset", "right_offset", "src_start", "src_end")
FIELDS_POS = ("start", "end", "dur")


def step5_integrity(tl, before, subs, rep):
    rep.h("PASO 5 - Integridad de V1/V2/V3/audio y pista de subtitulos")
    for i in range((tl.GetTrackCount("subtitle") or 0), 0, -1):
        nm = tl.GetTrackName("subtitle", i) or ""
        if norm(nm).lower() != "subtitle 1":
            rep.warn("Pista de subtitulos S%d '%s' no es 'Subtitle 1': no la borro" % (i, nm))
            continue
        cnt = len(items(tl, "subtitle", i))
        ok = call(tl, "DeleteTrack", "subtitle", i)
        if ok:
            rep.out("  Borrada la pista de subtitulos S%d '%s' (%d subtitulos)" % (i, nm, cnt))
        else:
            rep.block("No pude borrar la pista de subtitulos S%d '%s'" % (i, nm))
    if not (tl.GetTrackCount("subtitle") or 0):
        rep.out("  Sin pistas de subtitulos en la timeline")

    after = snapshot(tl)
    role_keys = set("V%d" % i for i in subs["idx"].values())
    for key in sorted(k for k in before if not k.startswith("S")):
        b, a = before[key]["items"], after.get(key, {}).get("items")
        fields = FIELDS_POS if key in role_keys else FIELDS_FULL
        if a is None:
            rep.block("%s desaparecio" % key)
            continue
        diffs = []
        if len(a) != len(b):
            diffs.append("%d clips -> %d" % (len(b), len(a)))
        for ib, ia in zip(b, a):
            for f in fields:
                if ib.get(f) != ia.get(f):
                    diffs.append("%s %s: %r -> %r" % (ib["name"], f, ib.get(f), ia.get(f)))
        if diffs:
            rep.block("%s cambio: %s" % (key, "; ".join(diffs[:6])))
        else:
            rep.out("  %-3s %-12s %2d clips intactos" % (key, (after[key]["name"] or "")[:12], len(a)))
    for key in after:
        if key not in before and not key.startswith("S"):
            rep.warn("Pista nueva %s '%s'" % (key, after[key]["name"]))

    # Adjustment clips / grade sobre el texto
    adj = [(k, it["name"]) for k, v in after.items() if k.startswith("V") and k not in role_keys
           for it in v["items"] if "adjustment" in norm(it["name"]).lower()]
    if adj:
        rep.out("  Adjustment clips bajo los subtitulos: %s" % adj)
    g = call(tl, "GetNodeGraph")
    if g is not None:
        nn = call(g, "GetNumNodes") or 0
        luts = [l for l in (call(g, "GetLUT", i) for i in range(1, nn + 1)) if l]
        rep.out("  Grade de timeline: %d nodos%s" % (nn, ", LUTs %s" % luts if luts else ""))
        if nn > 1 or luts:
            rep.warn("La timeline tiene grade a nivel de timeline: tambien afecta a los Text+. Revisa el Color page.")
    for x in subs["entries"]:
        gi = call(x.get("item"), "GetNodeGraph")
        if gi is None:
            continue
        nn = call(gi, "GetNumNodes") or 0
        luts = [l for l in (call(gi, "GetLUT", i) for i in range(1, nn + 1)) if l]
        if nn > 1 or luts:
            rep.warn("B%d %s: el Text+ tiene grade propio (%d nodos, LUTs %s)" % (x["block"], x["role"], nn, luts))
    rep.data["pistas_despues"] = dict((k, {"name": v["name"], "clips": len(v["items"])}) for k, v in after.items())


# ----------------------------------------------------------------------------
# Paso 6 - guardar y reporte
# ----------------------------------------------------------------------------
def step6_save(pm, rep):
    rep.h("PASO 6 - Guardar proyecto")
    if pm.SaveProject():
        rep.out("  Proyecto guardado")
    else:
        rep.block("SaveProject() devolvio False")


def summary(rep, v1, subs, fonts):
    rep.h("REPORTE")
    rep.out("Cortes de V1 medidos (frames de timeline @ %d fps, tcStart 00:00:00:00):" % FPS)
    for i, c in enumerate(v1, 1):
        rep.out("  %d. %-36s %4d-%4d  %s-%s  %5.2f s"
                % (i, c["name"], c["start"], c["end"], tc(c["start"]), tc(c["end"]), c["dur"] / float(FPS)))
    rep.out("  Cortes: %s" % ", ".join(str(c["start"]) for c in v1[1:]))
    rep.out("")
    entries = sorted(subs["entries"], key=lambda x: (x["s"], x["role"] != SUB_ARRIBA))
    rep.out("Text+ (%d):" % sum(1 for x in entries if "item" in x))
    rep.out("  blq pista       in    out   TC in        dur    texto                        Font / Style (leido)")
    table = []
    for x in entries:
        rb = x.get("readback", {})
        st, en = x.get("start"), x.get("end")
        row = {"bloque": x["block"], "pista": x["role"], "V": x["track"], "in": st, "out": en,
               "texto": norm(x.get("styled") or x["text"]), "font": rb.get("Font"), "style": rb.get("Style"),
               "size": rb.get("Size"), "center": rb.get("Center"), "inputs": rb.get("inputs_fijados"),
               "otros": rb.get("otros")}
        table.append(row)
        if st is None:
            rep.out("  B%d  %-10s  FALTA  (%d-%d) '%s'" % (x["block"], x["role"], x["s2"], x["e2"], x["text"]))
            continue
        rep.out("  B%d  %-10s %4d  %4d   %s  %4.2f s  %-28s %s / %s" % (
            x["block"], x["role"], st, en, tc(st), (en - st) / float(FPS), "'%s'" % row["texto"],
            rb.get("Font", "(sin estilar)"), rb.get("Style", "")))
    rep.data["textplus"] = table
    rep.out("")
    for role in ROLES:
        f = fonts.get(role)
        if f:
            rep.out("Fuente %s: Font=%r Style=%r archivo=%s" % (role, f[0], f[1], f[2]))
    rep.out("")
    rep.out("Pendiente / dudas:")
    rep.out("  - '100 puntos criticos' (placa final R07 y bloque 5): cifra pendiente de verificar; no tocada.")
    rep.out("  - Transcripcion: el script no escucha el audio. Comprobar a oido los 6 bloques.")
    for n in rep.notes:
        rep.out("  - " + n)
    rep.out("")
    rep.out("Bloqueantes: %d | Avisos: %d" % (len(rep.blockers), len(rep.warnings)))
    for b in rep.blockers:
        rep.out("  [BLOQUEANTE] " + b)


# ----------------------------------------------------------------------------
# Paso 7 - render
# ----------------------------------------------------------------------------
def step7_render(resolve, proj, tl, rep):
    rep.h("PASO 7 - Render")
    if not os.path.isdir(EXPORT_DIR):
        os.makedirs(EXPORT_DIR)
        rep.out("  Carpeta creada: %s" % EXPORT_DIR)
    target = os.path.join(EXPORT_DIR, EXPORT_NAME + ".mp4")
    if os.path.exists(target):
        bak = os.path.join(EXPORT_DIR, "%s_prev_%s.mp4" % (EXPORT_NAME, datetime.datetime.now().strftime("%Y%m%d_%H%M%S")))
        os.replace(target, bak)
        rep.out("  El .mp4 anterior se movio a %s" % bak)
    proj.SetCurrentTimeline(tl)
    call(resolve, "OpenPage", "deliver")

    abr = None
    presets = as_list(call(proj, "GetRenderPresetList"))
    if RENDER_PRESET in presets and call(proj, "LoadRenderPreset", RENDER_PRESET):
        abr = "preset '%s'" % RENDER_PRESET
        rep.out("  Preset cargado: %s" % RENDER_PRESET)
    codecs = call(proj, "GetRenderCodecs", "mp4") or {}
    keys = [str(v) for v in (codecs.values() if isinstance(codecs, dict) else codecs)]
    codec = "H264" if "H264" in keys else next((k for k in keys if "264" in k), None)
    if codec is None or not proj.SetCurrentRenderFormatAndCodec("mp4", codec):
        rep.block("No pude fijar MP4/H.264 (codecs mp4: %s)" % keys)
        return False
    rep.out("  Formato/codec: %s (disponibles: %s)" % (call(proj, "GetCurrentRenderFormatAndCodec"), keys))

    settings = [("SelectAllFrames", True, True), ("TargetDir", EXPORT_DIR, True),
                ("CustomName", EXPORT_NAME, True), ("ExportVideo", True, True),
                ("ExportAudio", True, True), ("FormatWidth", TL_WIDTH, True),
                ("FormatHeight", TL_HEIGHT, True), ("FrameRate", float(FPS), False),
                ("AudioCodec", "aac", True), ("AudioSampleRate", 48000, False),
                ("ExportSubtitle", False, False)]
    for k, v, required in settings:
        if not proj.SetRenderSettings({k: v}):
            (rep.block if required else rep.warn)("SetRenderSettings %s=%r fallo" % (k, v))
    if abr is None:
        for k in ("AudioBitRate", "AudioBitrate", "AudioDataRate"):
            if proj.SetRenderSettings({k: 320}) or proj.SetRenderSettings({k: 320000}):
                abr = "clave %s" % k
                break
    if abr is None:
        rep.warn("AAC 320 kbps: la API no expone el bitrate de audio y no existe el preset '%s'. "
                 "Se renderiza con el bitrate AAC actual de Deliver." % RENDER_PRESET)
    else:
        rep.out("  AAC 320 kbps via %s" % abr)
    if rep.blockers and not FORZAR_RENDER:
        return False

    jid = proj.AddRenderJob()
    if not jid:
        rep.block("AddRenderJob() fallo")
        return False
    job = next((j for j in as_list(proj.GetRenderJobList()) if j.get("JobId") == jid), {})
    rep.out("  Job %s: %s" % (jid, ", ".join("%s=%s" % (k, job[k]) for k in sorted(job) if k != "JobId")))
    checks = (("FormatWidth", TL_WIDTH), ("FormatHeight", TL_HEIGHT), ("FrameRate", FPS))
    for k, want in checks:
        if k in job and to_float(job[k]) != float(want):
            rep.block("Job %s=%s (esperado %s)" % (k, job[k], want))
    if rep.blockers and not FORZAR_RENDER:
        return False

    if not proj.StartRendering([jid], False):
        if not proj.StartRendering(jid):
            rep.block("StartRendering fallo")
            return False
    t_start, last, idle = time.time(), -1, 0
    while True:
        time.sleep(2)
        st = proj.GetRenderJobStatus(jid) or {}
        pct = st.get("CompletionPercentage", 0)
        if pct != last and int(pct) % 10 == 0:
            print("  render %s%%" % pct)
            last = pct
        if st.get("JobStatus") in ("Complete", "Failed", "Cancelled"):
            break
        idle = idle + 1 if not proj.IsRenderingInProgress() else 0
        if idle >= 3 or time.time() - t_start > 3600:
            break
    st = proj.GetRenderJobStatus(jid) or {}
    rep.out("  Estado: %s" % st)
    out = os.path.join(job.get("TargetDir") or EXPORT_DIR, job.get("OutputFilename") or EXPORT_NAME + ".mp4")
    if st.get("JobStatus") == "Complete" and os.path.isfile(out):
        rep.out("  Exportado: %s (%.1f MB, %.1f s de render)" % (
            out, os.path.getsize(out) / 1048576.0, (st.get("TimeTakenToRenderInMs") or 0) / 1000.0))
        rep.data["export"] = {"file": out, "bytes": os.path.getsize(out), "job": job, "status": st}
        return True
    rep.block("El render no termino bien (%s); archivo %s %s" % (
        st.get("JobStatus"), out, "existe" if os.path.isfile(out) else "no existe"))
    return False


def delete_old_timelines(proj, rep):
    rep.h("Limpieza - timelines v2 y v3")
    olds = []
    for i in range(1, (proj.GetTimelineCount() or 0) + 1):
        t = proj.GetTimelineByIndex(i)
        if t is not None and t.GetName() in OLD_TIMELINES:
            olds.append(t)
    if not olds:
        rep.out("  No hay timelines v2/v3")
        return
    names = [t.GetName() for t in olds]
    if proj.GetMediaPool().DeleteTimelines(olds):
        rep.out("  Borradas: %s" % names)
    else:
        rep.warn("No pude borrar %s" % names)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
class Options(object):
    pass


def parse_args(argv):
    import argparse
    p = argparse.ArgumentParser(description="Subtitulos Text+ SUB_ARRIBA/SUB_ABAJO")
    p.add_argument("--solo-medir", action="store_true")
    p.add_argument("--sin-render", action="store_true")
    p.add_argument("--forzar-render", action="store_true")
    p.add_argument("--borrar-v2-v3", action="store_true")
    try:
        a, _ = p.parse_known_args(argv)
    except SystemExit:
        a, _ = p.parse_known_args([])
    o = Options()
    o.solo_medir = SOLO_MEDIR or a.solo_medir
    o.render = RENDER and not a.sin_render and not o.solo_medir
    o.forzar_render = FORZAR_RENDER or a.forzar_render
    o.borrar_v2_v3 = BORRAR_V2_V3 or a.borrar_v2_v3
    return o


def run(opts, rep):
    global FORZAR_RENDER
    FORZAR_RENDER = opts.forzar_render
    resolve = get_resolve()
    pm, proj, tl = step0_connect(resolve, rep)
    fonts = step1_fonts(resolve, rep)
    before = snapshot(tl)
    rep.data["pistas_antes"] = dict((k, {"name": v["name"], "clips": len(v["items"])}) for k, v in before.items())
    v1 = step2_v1(before, rep)
    subs = step3_subs(tl, v1, opts, rep)
    if opts.solo_medir:
        summary(rep, v1, subs, fonts)
        rep.out("")
        rep.out("SOLO MEDICION: no se modifico nada.")
        return
    step4_style(tl, subs, fonts, rep)
    step5_integrity(tl, before, subs, rep)
    step6_save(pm, rep)
    summary(rep, v1, subs, fonts)
    rep.save()
    if not opts.render:
        rep.out("")
        rep.out("Render omitido (--sin-render).")
        return
    if rep.blockers and not opts.forzar_render:
        rep.out("")
        rep.out("Render NO lanzado: hay %d bloqueantes (usa --forzar-render para ignorarlos)." % len(rep.blockers))
        return
    rendered = step7_render(resolve, proj, tl, rep)
    if rendered and opts.borrar_v2_v3 and not rep.blockers:
        delete_old_timelines(proj, rep)
    pm.SaveProject()


def main(argv=None):
    opts = parse_args(argv if argv is not None else getattr(sys, "argv", [""])[1:])
    rep = Report()
    try:
        run(opts, rep)
    except Abort as e:
        rep.h("DETENIDO")
        rep.out("  " + str(e))
        rep.data["detenido"] = str(e)
    except Exception:
        rep.h("ERROR")
        rep.out(traceback.format_exc())
        rep.data["error"] = traceback.format_exc()
    rep.data["fin"] = datetime.datetime.now().isoformat(timespec="seconds")
    rep.out("")
    rep.out("Reporte: %s.txt / .json" % REPORT_BASE)
    rep.save()
    return rep


if __name__ == "__main__":
    main()

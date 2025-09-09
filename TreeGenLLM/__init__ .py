# -*- coding: utf-8 -*-
# Tree Gen LLM - Blender Add-on
# - Natural language -> Geometry Nodes parameters (Qwen2.5-7B GGUF via llama.cpp)
# - Manifest auto download / Setup in Preferences
# - Generate after inference (spawn object only on success)
# - Reset deletes TreeGen object
# - Cancel:
#     SOFT: abort_callback (if supported) / safe-ignore result
#     HARD: run inference in subprocess and kill on cancel (always stoppable)
# - Single-flight lock + "Stopping..." UI
# - Full sockets UI (IDProp types only), section/group via custom_defaults
# - UI tweaks: vertical Status/Cancel, "Wood Material" & "leaf", operator label "Generate"
# - Setup: Windows のシステムコンソールを自動表示（成功時は自動クローズ）

bl_info = {
    "name":        "Tree Gen LLM",
    "author":      "Sekiyu & GPT-5 Thinking",
    "version":     (2, 7, 4),
    "blender":     (4, 3, 0),
    "location":    "3D View > Sidebar (N) > Tree Gen LLM",
    "description": "Natural language -> Geometry Nodes parameters (Qwen2.5-7B GGUF via llama.cpp)",
    "category":    "Add Mesh",
}

import bpy
import json
import os
import sys
import time
import random
import textwrap
import threading
import re
import logging
import importlib, importlib.util
import subprocess
import inspect

logger = logging.getLogger("TreeGen")
if not logger.handlers:
    _h = logging.StreamHandler(stream=sys.stdout)
    _h.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s [TreeGen] %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

# ------------------------- Local imports -------------------------
def addon_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))

def _import_local_module(mod_name: str):
    try:
        pkg = __package__ or (__name__.rpartition(".")[0] if "." in __name__ else None)
        if pkg:
            return importlib.import_module(f".{mod_name}", pkg)
    except Exception:
        pass
    path = os.path.join(addon_root(), f"{mod_name}.py")
    if os.path.exists(path):
        spec = importlib.util.spec_from_file_location(mod_name, path)
        m = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = m
        spec.loader.exec_module(m)
        return m
    raise ImportError(f"Local module not found: {mod_name}")

try:
    SC = _import_local_module("user_socket_schema").USER_SOCKET_SCHEMA
except Exception as e:
    SC = {}
    print("[TreeGen] WARN: user_socket_schema import failed:", e)

try:
    _cd = _import_local_module("custom_defaults")
    CUSTOM_DEFAULTS = getattr(_cd, "CUSTOM_DEFAULTS", {})
    BOOL_CHILDREN   = getattr(_cd, "BOOL_CHILDREN", {})
    SECTION_LABELS  = getattr(_cd, "SECTION_LABELS", {})
except Exception as e:
    CUSTOM_DEFAULTS = {}
    BOOL_CHILDREN   = {}
    SECTION_LABELS  = {}
    print("[TreeGen] WARN: custom_defaults import failed:", e)

_LLAMA_IMPORT_ERROR = None
def _lazy_import_llama():
    global _LLAMA_IMPORT_ERROR
    if _LLAMA_IMPORT_ERROR:
        return None
    try:
        from llama_cpp import Llama  # noqa
        return True
    except Exception as e:
        _LLAMA_IMPORT_ERROR = e
        return None

# ------------------------- Single-flight / Cancel -------------------------
class _Task:
    __slots__ = ("id", "cancel_event", "started_at", "proc")
    def __init__(self, tid: int):
        self.id = tid
        self.cancel_event = threading.Event()
        self.started_at = time.perf_counter()
        self.proc = None  # HARD モード用: subprocess.Popen

_CURRENT_TASK = None
_TASK_SEQ = 0
INFER_LOCK = threading.Lock()  # Llamaへの並列呼出し禁止

def _new_task() -> "_Task":
    global _TASK_SEQ, _CURRENT_TASK
    _TASK_SEQ += 1
    t = _Task(_TASK_SEQ)
    _CURRENT_TASK = t
    return t

def _get_task(): return _CURRENT_TASK
def _clear_task_if(task: "_Task"):
    global _CURRENT_TASK
    if _CURRENT_TASK is task:
        _CURRENT_TASK = None

# ------------------------- UI State -------------------------
PROGRESS_DURATION = 15.0
PROGRESS_FPS      = 30

def ensure_dir(p: str): os.makedirs(p, exist_ok=True)
def absolute_path(rel: str) -> str:
    return rel if os.path.isabs(rel) else os.path.join(addon_root(), rel)

def load_node_group(group_name: str = "TreeNodeGen"):
    return bpy.data.node_groups.get(group_name)

def try_append_node_group(group_name="TreeNodeGen", blend_path=None):
    if load_node_group(group_name):
        return bpy.data.node_groups[group_name]
    blend_path = blend_path or absolute_path("TreeNodeGen.blend")
    if not os.path.exists(blend_path): return None
    try:
        with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
            if group_name in data_from.node_groups:
                data_to.node_groups = [group_name]
        return bpy.data.node_groups.get(group_name)
    except Exception as e:
        logger.error(f"Append failed: {e}")
        return None

def spawn_new_object(name_base: str = "TreeGen") -> bpy.types.Object:
    idx = 1
    while True:
        name_obj  = f"{name_base}_{idx:03d}"
        name_mesh = f"{name_base}Mesh_{idx:03d}"
        if (name_obj not in bpy.data.objects) and (name_mesh not in bpy.data.meshes): break
        idx += 1
    mesh = bpy.data.meshes.new(name_mesh)
    obj  = bpy.data.objects.new(name_obj, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    return obj

# ------------------------- Validation helpers -------------------------
def clip_value(value, spec):
    t = spec.get("type")
    if t == "float":
        try: x = float(value)
        except Exception: x = float(spec.get("default", 0.0))
        lo = float(spec.get("min", x)); hi = float(spec.get("max", x))
        return min(max(x, lo), hi)
    if t == "integer":
        try: x = int(round(float(value)))
        except Exception: x = int(spec.get("default", 0))
        lo = int(spec.get("min", x)); hi = int(spec.get("max", x))
        return min(max(x, lo), hi)
    if t == "bool":
        if isinstance(value, bool): return value
        return str(value).lower() in ("true", "1", "yes", "on")
    return value

def validate_and_clip(params: dict, schema: dict):
    out, clipped, violations = {}, {}, {}
    for k, spec in schema.items():
        if k not in params:
            out[k] = spec.get("default"); violations[k] = "missing->default"; continue
        v_in = params.get(k); v = clip_value(v_in, spec); out[k] = v
        if v != v_in: clipped[k] = {"in": v_in, "out": v}
    for k in list(params.keys()):
        if k not in schema: violations[k] = "unknown-key->dropped"
    return out, clipped, violations

def confidence_score(validated: dict, defaults: dict, clipped: dict) -> float:
    eps = 1e-9; keys = [k for k in validated.keys() if k in defaults]
    if not keys: return 0.0
    diffs = []
    for k in keys:
        v = validated[k]; d = defaults[k]
        if isinstance(v,(int,float)) and isinstance(d,(int,float)):
            rng = abs(d) + 1.0; diffs.append(min(1.0, abs(v-d)/(rng+eps)))
        elif isinstance(v,bool) and isinstance(d,bool):
            diffs.append(0.3 if v!=d else 0.0)
    base = sum(diffs)/max(1,len(diffs))
    clip_penalty = min(0.5, len(clipped)/max(1,len(validated)))
    return max(0.0, min(1.0, base*(1.0-clip_penalty)))

def defaults_from_schema(schema: dict) -> dict:
    return {k: v.get("default") for k, v in schema.items()}

def build_spec_block(schema: dict) -> str:
    def fmt(v): return f"{v:.2f}" if isinstance(v, float) else v
    lines=[]
    for k,s in list(schema.items())[:25]:
        if not s: continue
        lo,hi,df = s.get("min"), s.get("max"), s.get("default")
        desc = s.get("description","")
        mid = (lo+hi)/2 if isinstance(lo,(int,float)) and isinstance(hi,(int,float)) else df
        lines.append(f"{k}: {s.get('type')} {lo}–{hi}  # {desc}, 例:{fmt(mid)} (default:{fmt(df)})")
    return "\n".join(lines) + "\n"

def _gbnf_for_schema(schema: dict) -> str:
    number_keys = [k for k,s in schema.items() if s.get("type") in ("float","integer")]
    bool_keys   = [k for k,s in schema.items() if s.get("type")=="bool"]
    number_keys.sort(); bool_keys.sort()

    def _alts(xs): return " | ".join(json.dumps(x) for x in xs)
    boolean_def = "\n".join([
        r'boolean ::= "true" | "false"',
        r'number  ::= integer frac? exp?',
        r'integer ::= "-"? ("0" | [1-9] [0-9]*)',
        r'frac    ::= "." [0-9]+',
        r'exp     ::= ("e" | "E") ("+" | "-")? [0-9]+',
        r'ws ::= ([ \t\n\r] | comment)*',
        r'comment ::= "/*" ([^*] | "*"+ [^*/])* "*"+ "/"',
        ""
    ])

    if number_keys and bool_keys:
        return "\n".join([
            r'root ::= ws "{" ws members? ws "}" ws',
            r'members ::= pair (ws "," ws pair)*',
            r'pair ::= number_pair | bool_pair',
            r'number_pair ::= number_key ws ":" ws number',
            "number_key ::= " + _alts(number_keys),
            r'bool_pair ::= bool_key ws ":" ws boolean',
            "bool_key ::= " + _alts(bool_keys),
            "",
            boolean_def
        ])

    if number_keys:
        return "\n".join([
            r'root ::= ws "{" ws members? ws "}" ws',
            r'members ::= number_pair (ws "," ws number_pair)*',
            r'number_pair ::= number_key ws ":" ws number',
            "number_key ::= " + _alts(number_keys),
            "",
            boolean_def
        ])

    return "\n".join([r'root ::= ws "{" ws "}" ws', "", boolean_def])

# ------------------------- LLM Generator/Loader -------------------------
class Generator:
    _instance = None
    def __init__(self):
        self.llm = None
        self.model_path = ""
        self.n_ctx = 4096
        self.n_threads = max(os.cpu_count() or 8, 8)  # If cpu count missing, default to 8
        self.n_gpu_layers = int(os.environ.get("TREEGEN_N_GPU_LAYERS", "0"))
        self.n_batch = 512 # 256〜1024 目安。VRAMに余裕あれば上げてもOK
        self.cache_prompt = True # 先頭プロンプトのKVを使い回し
        self.verbose = False
        self.required_models = []
        self.downloaded_models = {}

    @classmethod
    def instance(cls):
        if cls._instance is None: cls._instance = Generator()
        return cls._instance

    def _manifest_path(self):
        for p in (os.path.join(addon_root(),"models","manifest.json"),
                  os.path.join(addon_root(),"manifest.json")):
            if os.path.exists(p): return p
        return None

    def _load_manifest(self):
        self.required_models=[]
        mp = self._manifest_path()
        if not mp:
            self.required_models=[{"repo_id":"lmstudio-community/Qwen2.5-7B-Instruct-GGUF",
                                   "filename":"Qwen2.5-7B-Instruct-Q4_K_M.gguf"}]
            return
        try:
            with open(mp,"r",encoding="utf-8") as f: data=json.load(f)
            self.required_models=list(data.get("required_models",[]))
        except Exception as e:
            logger.error(f"manifest load failed: {e}")
            self.required_models=[{"repo_id":"lmstudio-community/Qwen2.5-7B-Instruct-GGUF",
                                   "filename":"Qwen2.5-7B-Instruct-Q4_K_M.gguf"}]

    def _models_dir(self):
        p=os.path.join(addon_root(),"models"); os.makedirs(p,exist_ok=True); return p

    def _list_downloaded_models(self):
        self.downloaded_models={}
        mdl_dir=self._models_dir()
        try:
            for m in self.required_models:
                fn=m.get("filename"); 
                if not fn: continue
                ap=os.path.join(mdl_dir,fn)
                if os.path.exists(ap): self.downloaded_models[fn]=ap
        except Exception as e:
            logger.error(f"list models failed: {e}")

    def ensure_models(self, auto_download: bool=True) -> bool:
        if not self.required_models: self._load_manifest()
        self._list_downloaded_models()
        missing=[m for m in self.required_models if m.get("filename") not in self.downloaded_models]
        if not missing: return True
        if not auto_download: return False
        try:
            from huggingface_hub import hf_hub_download
        except Exception as e:
            logger.error(f"huggingface_hub not available: {e}")
            return False
        mdl_dir=self._models_dir()
        for m in missing:
            repo=m.get("repo_id"); fn=m.get("filename")
            if not repo or not fn: continue
            logger.info(f"downloading {repo} / {fn} → {mdl_dir}")
            try: hf_hub_download(repo_id=repo, filename=fn, local_dir=mdl_dir)
            except Exception as e:
                logger.error(f"download failed {repo}/{fn}: {e}"); return False
        self._list_downloaded_models()
        return all(m.get("filename") in self.downloaded_models for m in self.required_models)

    def default_model_path(self)->str:
        if not self.required_models: self._load_manifest()
        if not self.downloaded_models: self._list_downloaded_models()
        if not self.required_models: return ""
        first=self.required_models[0].get("filename","")
        return self.downloaded_models.get(first, os.path.join(self._models_dir(), first))

    def load(self, path: str=""):
        if not path: path=self.default_model_path()
        if not os.path.exists(path): raise FileNotFoundError(f"Model not found: {path}")
        if not _lazy_import_llama(): raise RuntimeError(f"llama_cpp import failed: {_LLAMA_IMPORT_ERROR}")
        from llama_cpp import Llama
        logger.info(f"Loading LLM: {os.path.basename(path)} (gpu_layers={self.n_gpu_layers})")
        self.llm = Llama(model_path=path, n_ctx=self.n_ctx, n_threads=self.n_threads,
                         n_gpu_layers=self.n_gpu_layers, n_batch=self.n_batch, cache_prompt=self.cache_prompt,
                         use_mmap=True, logits_all=False, seed=0, verbose=False)
        self.model_path = path
    def is_loaded(self)->bool: return self.llm is not None

# ------------------------- System console helpers (Windows only) ------------
IS_WIN32 = (sys.platform == "win32")
_CONSOLE_OPENED_BY_TG = False

def _console_is_visible_win32():
    if not IS_WIN32:
        return None
    try:
        import ctypes
        gw = ctypes.windll.kernel32.GetConsoleWindow()
        if gw == 0:
            return False
        return bool(ctypes.windll.user32.IsWindowVisible(gw))
    except Exception:
        return None

def _console_open_for_progress():
    """Setup 実行前にコンソールを開く（必要なら）。開いた場合 True を返す。"""
    global _CONSOLE_OPENED_BY_TG
    if not IS_WIN32:
        return False
    vis = _console_is_visible_win32()
    if vis is False:
        try:
            bpy.ops.wm.console_toggle()
            _CONSOLE_OPENED_BY_TG = True
            return True
        except Exception:
            pass
    _CONSOLE_OPENED_BY_TG = False
    return False

def _console_close_if_opened_by_us():
    """成功時のみ、TreeGen が開いたコンソールを閉じる。"""
    global _CONSOLE_OPENED_BY_TG
    if not IS_WIN32 or not _CONSOLE_OPENED_BY_TG:
        return False
    try:
        bpy.ops.wm.console_toggle()
        _CONSOLE_OPENED_BY_TG = False
        return True
    except Exception:
        return False

# ------------------------- Addon Prefs -------------------------
class TreeGenPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    model_path: bpy.props.StringProperty(
        name="7B Model Path", description="Resolved model path from manifest (read-only UI)",
        subtype='FILE_PATH', default=os.path.join(addon_root(),"models","Qwen2.5-7B-Instruct-Q4_K_M.gguf")
    )
    inference_mode: bpy.props.EnumProperty(
        name="Inference", description="FAST: 7B model (manifest first entry)",
        items=[('FAST',"FAST (7B)","Use 7B model from manifest")], default='FAST'
    )
    cancel_mode: bpy.props.EnumProperty(
        name="Cancel Mode",
        description="How to stop inference",
        items=[
            ('AUTO', "Auto", "Use abort_callback if available; otherwise subprocess kill"),
            ('SOFT', "Soft", "Use abort_callback/event only (cannot force-stop if unsupported)"),
            ('HARD', "Hard", "Always run inference in a subprocess and kill on cancel")
        ],
        default='AUTO'
    )
    def draw(self, _):
        layout=self.layout
        layout.prop(self,"inference_mode")
        row=layout.row(); row.enabled=False; row.prop(self,"model_path")
        layout.prop(self, "cancel_mode")
        r=layout.row(align=True)
        r.operator("treegen.load_generator", text="Setup", icon='IMPORT')
        r.operator("treegen.refresh_model_path", text="Refresh Model Path", icon='FILE_REFRESH')
        c=layout.column(align=True)
        c.operator("treegen.open_models_folder", text="Open Models Folder", icon='FILE_FOLDER')
        c.label(text="1) Online: Press 'Setup' to auto-download & load.")
        c.label(text="2) Offline: Put GGUF into /models and press 'Refresh'.")

# ------------------------- Scene/WM props -------------------------
def update_material(self, context):
    obj=context.active_object; 
    if not obj: return
    mod=obj.modifiers.get("TreeGen"); 
    if not mod: return
    try: mod["Socket_2"]=self.material
    except Exception as e: logger.error(f"Material update failed: {e}")

def update_collection(self, context):
    obj=context.active_object
    if not obj: return
    mod=obj.modifiers.get("TreeGen")
    if not mod: return
    try: mod["Socket_43"]=self.collection
    except Exception as e: logger.error(f"Collection update failed: {e}")

class TreeGenProperties(bpy.types.PropertyGroup):
    prompt         : bpy.props.StringProperty(name="Prompt", default="")
    generated_text : bpy.props.StringProperty(name="Last JSON", default="")
    material       : bpy.props.PointerProperty(name="Wood Material",  type=bpy.types.Material,  update=update_material)
    collection     : bpy.props.PointerProperty(name="leaf",          type=bpy.types.Collection, update=update_collection)

def _wm_props_register():
    bpy.types.WindowManager.treegen_busy        = bpy.props.BoolProperty(default=False)  # progress表示用
    bpy.types.WindowManager.treegen_engine_busy = bpy.props.BoolProperty(default=False)  # 実行中/停止中

def _wm_props_unregister():
    for k in ("treegen_busy","treegen_engine_busy"):
        if hasattr(bpy.types.WindowManager,k): delattr(bpy.types.WindowManager,k)

# ------------------------- Progress -------------------------
_PROGRESS_TOKEN = {"running": False, "start": 0.0}
def _start_continuous_progress(wm):
    _PROGRESS_TOKEN["running"]=True; _PROGRESS_TOKEN["start"]=time.perf_counter()
    wm.progress_begin(0.0,100.0)
    def _tick():
        if not _PROGRESS_TOKEN["running"]: return None
        elapsed=time.perf_counter()-_PROGRESS_TOKEN["start"]
        frac=min(1.0, elapsed/PROGRESS_DURATION); wm.progress_update(frac*100.0)
        return 1.0/PROGRESS_FPS
    bpy.app.timers.register(_tick, first_interval=0.0)
def _end_progress(wm):
    _PROGRESS_TOKEN["running"]=False
    try: wm.progress_end()
    except Exception: pass

# ------------------------- GN UI helpers -------------------------
def _init_idprop_for_socket(mod, ident: str, socket_type: str):
    try:
        if ident in mod: return
        tail = socket_type.rsplit('.',1)[-1] if '.' in socket_type else socket_type
        if tail.endswith("Float"): mod[ident]=0.0
        elif tail.endswith("Int"): mod[ident]=0
        elif tail.endswith("Bool"): mod[ident]=False
        else: pass
    except Exception as e:
        logger.warning(f"init idprop failed: {ident} ({socket_type}): {e}")

def ensure_all_input_idprops(mod: bpy.types.Modifier, ng: bpy.types.NodeTree):
    itree=getattr(ng,"interface",None)
    items=getattr(itree,"items_tree",[]) if itree else []
    for it in items:
        try:
            if getattr(it,"item_type","")!='SOCKET' or getattr(it,"in_out","")!='INPUT': continue
            ident=getattr(it,"identifier",None) or getattr(it,"name",None)
            stype=getattr(it,"socket_type",""); 
            if not ident: continue
            _init_idprop_for_socket(mod, ident, stype)
        except Exception as e:
            logger.warning(f"ensure_all_input_idprops: {e}")

def _interface_input_items(ng: bpy.types.NodeTree):
    out=[]; itree=getattr(ng,"interface",None)
    items=getattr(itree,"items_tree",[]) if itree else []
    for it in items:
        if getattr(it,"item_type","")!='SOCKET' or getattr(it,"in_out","")!='INPUT': continue
        name=getattr(it,"name","Socket"); ident=getattr(it,"identifier",None) or name
        stype=getattr(it,"socket_type",""); out.append((name,ident,stype))
    return out

def _draw_idprop_or_label(layout, mod, ident, name, stype):
    # 1) IDProp として描画（float/int/bool）
    if ident in mod:
        try:
            layout.prop(mod, f'["{ident}"]', text=name); return True
        except Exception:
            pass
    # 2) RNA プロパティとして描画（Material/Collection/Object など）
    try:
        layout.prop(mod, ident, text=name); return True
    except Exception:
        row=layout.row(); row.enabled=False; row.label(text=f"{name} (unsupported: {stype})"); return False

def draw_parameters_grouped(layout: bpy.types.UILayout, mod: bpy.types.Modifier, ng: bpy.types.NodeTree):
    items=_interface_input_items(ng)
    if not items:
        layout.label(text="(no inputs)", icon='INFO'); return
    # 逆引き（子→親）
    child_to_parent={}
    for p,children in BOOL_CHILDREN.items():
        for ch in children: child_to_parent[ch]=p
    def _start_section(parent, title:str):
        box=parent.box()
        if title: box.label(text=title)
        return box
    current_section=None
    ensure_all_input_idprops(mod, ng)
    drawn=set()
    for name,ident,stype in items:
        # Geometry 型はモディファイア UI から設定不可のため非表示
        if "NodeSocketGeometry" in stype or stype.endswith("Geometry"):
            continue
        # セクション見出し
        if ident in SECTION_LABELS: current_section=_start_section(layout, SECTION_LABELS.get(ident,""))
        if current_section is None: current_section=_start_section(layout,"")
        if ident in drawn: continue
        # ブール親 → 子グループ
        if ident in BOOL_CHILDREN:
            okp=_draw_idprop_or_label(current_section,mod,ident,name,stype)
            children=BOOL_CHILDREN.get(ident,[])
            sub=current_section.box(); sub.enabled=bool(mod.get(ident,False)) if okp else False
            for ch in children:
                m=next((t for t in items if t[1]==ch),None)
                if not m: continue
                ch_name,ch_ident,ch_st = m
                if "NodeSocketGeometry" in ch_st or ch_st.endswith("Geometry"):
                    continue
                _draw_idprop_or_label(sub,mod,ch_ident,ch_name,ch_st); drawn.add(ch_ident)
            drawn.add(ident); continue
        if ident in child_to_parent: continue
        _draw_idprop_or_label(current_section,mod,ident,name,stype)

# ------------------------- GN apply helpers -------------------------
def ensure_gn_modifier(obj: bpy.types.Object, group_name: str="TreeNodeGen"):
    """TreeGen 用の GN モディファイアを確実に付与し、全INPUTソケットのIDPropを準備して返す。"""
    mod = obj.modifiers.get("TreeGen")
    ng  = load_node_group(group_name)
    if not ng:
        ng = try_append_node_group(group_name, absolute_path("TreeNodeGen.blend"))
        if not ng:
            return None, None
    if not mod:
        mod = obj.modifiers.new("TreeGen", type='NODES')
    mod.node_group = ng
    try:
        ensure_all_input_idprops(mod, ng)
    except Exception as e:
        logger.warning(f"init all sockets idprop failed: {e}")
    return mod, ng

# ------------------------- LLM Calls -------------------------
def _qwen_messages(spec_block: str, prompt_text: str, rand_tag: int):
    system_msg = textwrap.dedent(f"""\
あなたは “TreeGen” のパラメータ推定器です。
次のキー仕様を **すべて** JSON で返してください。
型（float/integer/bool）を守り、余計なキーは書かないこと。

# Sockets
{spec_block}

# 出力ルール
- 純粋 JSON 1 個のみ（先頭 '{{'、末尾 '}}'）
- 値は数値/真偽のみ。配列・オブジェクト・文字列禁止
- コメント・説明・コードフェンス禁止
- ルールに違反した場合は空オブジェクト {{}} を返す
""")
    user_msg = f"TreeGen用パラメータを生成してください: {prompt_text} | id:{rand_tag}"
    return [{"role":"system","content":system_msg},{"role":"user","content":user_msg}]

def _supports_abort_callback():
    try:
        from llama_cpp import Llama
        return "abort_callback" in inspect.signature(Llama.create_chat_completion).parameters
    except Exception:
        return False

def run_llm_soft(prompt_text: str, cancel_event: threading.Event | None, model_path: str, schema: dict) -> dict:
    from time import perf_counter
    if not os.path.exists(model_path):
        return {"ok":False,"params":None,"elapsed":0.0,"confidence":0.0,"raw":None,
                "clipped":None,"violations":{"error":"model_missing"},"model":"(unset)"}
    if not schema:
        return {"ok":False,"params":None,"elapsed":0.0,"confidence":0.0,"raw":None,
                "clipped":None,"violations":{"error":"schema_missing"},"model":os.path.basename(model_path)}
    if not _lazy_import_llama():
        return {"ok":False,"params":None,"elapsed":0.0,"confidence":0.0,"raw":None,
                "clipped":None,"violations":{"error":f"llama import failed: {_LLAMA_IMPORT_ERROR}"},
                "model":os.path.basename(model_path)}
    from llama_cpp import Llama
    with INFER_LOCK:
        gen = Generator.instance()
        if (not gen.is_loaded()) or (gen.model_path != model_path):
            gen.load(model_path)
        llm = gen.llm
        grammar_obj=None
        try:
            from llama_cpp import LlamaGrammar
            grammar_str=_gbnf_for_schema(schema)
            grammar_obj=LlamaGrammar.from_string(grammar_str)
        except Exception as e:
            logger.warning(f"Grammar disabled (fallback): {e}")
            grammar_obj=None
        spec_block=build_spec_block(schema)
        messages=_qwen_messages(spec_block, prompt_text, random.randint(100000,999999))
        supports_abort=_supports_abort_callback()
        t0=perf_counter()
        def _call(temp: float, use_grammar: bool=True):
            kwargs=dict(messages=messages, temperature=temp, top_p=0.9, max_tokens=420,
                        seed=random.randint(0,2**31-1))
            if use_grammar and grammar_obj is not None: kwargs["grammar"]=grammar_obj
            if cancel_event is not None and supports_abort: kwargs["abort_callback"]=cancel_event.is_set
            try:
                return llm.create_chat_completion(**kwargs)
            except TypeError as e:
                if "abort_callback" in str(e):
                    kwargs.pop("abort_callback", None)
                    return llm.create_chat_completion(**kwargs)
                raise
        last_err=None
        for temp,use_g in ((0.4,True),(0.2,True),(0.4,False)):
            if cancel_event is not None and cancel_event.is_set():
                return {"ok":False,"params":None,"elapsed":perf_counter()-t0,"confidence":0.0,
                        "raw":None,"clipped":None,"violations":{"error":"canceled"},
                        "model":os.path.basename(model_path)}
            try:
                out=_call(temp,use_grammar=use_g)
                if cancel_event is not None and cancel_event.is_set():
                    return {"ok":False,"params":None,"elapsed":perf_counter()-t0,"confidence":0.0,
                            "raw":None,"clipped":None,"violations":{"error":"canceled"},
                            "model":os.path.basename(model_path)}
                raw=(out["choices"][0]["message"]["content"] or "").strip()
                if not raw: raise RuntimeError("empty_response")
                m=re.search(r"\{.*\}", raw, flags=re.S)
                json_text=m.group(0) if m else raw
                parsed=json.loads(json_text)
                validated,clipped,violations=validate_and_clip(parsed, schema)
                conf=confidence_score(validated, defaults_from_schema(schema), clipped)
                return {"ok":True,"params":validated,"elapsed":perf_counter()-t0,"confidence":conf,
                        "raw":raw,"clipped":clipped or None,"violations":violations or None,
                        "model":os.path.basename(model_path)}
            except Exception as e:
                if cancel_event is not None and cancel_event.is_set():
                    return {"ok":False,"params":None,"elapsed":perf_counter()-t0,"confidence":0.0,
                            "raw":None,"clipped":None,"violations":{"error":"canceled"},
                            "model":os.path.basename(model_path)}
                last_err=f"{type(e).__name__}: {e}"; continue
        return {"ok":False,"params":None,"elapsed":perf_counter()-t0,"confidence":0.0,"raw":None,
                "clipped":None,"violations":{"error":last_err or 'unknown'},
                "model":os.path.basename(model_path)}

# ---- HARD: subprocess worker ---------------------------------------------------------
def _ensure_worker_script() -> str:
    """
    別プロセス用の最小スクリプトを、アドオン配下に生成して返す。
    Grammar が失敗したらフォールバック（grammar=None）で継続。
    """
    path = os.path.join(addon_root(), "_llm_worker.py")
    code = r'''# -*- coding: utf-8 -*-
import sys, json, time, re, random, textwrap

def _gbnf_for_schema(schema: dict) -> str:
    number_keys=[k for k,s in schema.items() if s.get("type") in ("float","integer")]
    bool_keys=[k for k,s in schema.items() if s.get("type")=="bool"]
    number_keys.sort(); bool_keys.sort()
    def _alts(xs): return " | ".join(json.dumps(x) for x in xs)
    boolean_def="\n".join([
        r'boolean ::= "true" | "false"',
        r'number  ::= integer frac? exp?',
        r'integer ::= "-"? ("0" | [1-9] [0-9]*)',
        r'frac    ::= "." [0-9]+',
        r'exp     ::= ("e" | "E") ("+" | "-")? [0-9]+',
        r'ws ::= ([ \t\n\r] | comment)*',
        r'comment ::= "/*" ([^*] | "*"+ [^*/])* "*"+ "/"',
        ""
    ])
    if number_keys and bool_keys:
        return "\n".join([
            r'root ::= ws "{" ws members? ws "}" ws',
            r'members ::= pair (ws "," ws pair)*',
            r'pair ::= number_pair | bool_pair',
            r'number_pair ::= number_key ws ":" ws number',
            "number_key ::= " + _alts(number_keys),
            r'bool_pair ::= bool_key ws ":" ws boolean',
            "bool_key ::= " + _alts(bool_keys),
            "",
            boolean_def
        ])
    if number_keys:
        return "\n".join([
            r'root ::= ws "{" ws members? ws "}" ws',
            r'members ::= number_pair (ws "," ws number_pair)*',
            r'number_pair ::= number_key ws ":" ws number',
            "number_key ::= " + _alts(number_keys),
            "",
            boolean_def
        ])
    return "\n".join([r'root ::= ws "{" ws "}" ws', "", boolean_def])

def _build_spec_block(schema: dict) -> str:
    def fmt(v): return f"{v:.2f}" if isinstance(v, float) else v
    lines=[]
    for k,s in list(schema.items())[:25]:
        if not s: continue
        lo,hi,df = s.get("min"), s.get("max"), s.get("default")
        desc = s.get("description","")
        mid = (lo+hi)/2 if isinstance(lo,(int,float)) and isinstance(hi,(int,float)) else df
        lines.append(f"{k}: {s.get('type')} {lo}–{hi}  # {desc}, 例:{fmt(mid)} (default:{fmt(df)})")
    return "\n".join(lines) + "\n"

def _messages(spec_block: str, prompt_text: str, tag: int):
    system_msg = textwrap.dedent(f"""\
あなたは “TreeGen” のパラメータ推定器です。
次のキー仕様を **すべて** JSON で返してください。
型（float/integer/bool）を守り、余計なキーは書かないこと。

# Sockets
{spec_block}

# 出力ルール
- 純粋 JSON 1 個のみ（先頭 '{{'、末尾 '}}'）
- 値は数値/真偽のみ。配列・オブジェクト・文字列禁止
- コメント・説明・コードフェンス禁止
- ルールに違反した場合は空オブジェクト {{}} を返す
""")
    user_msg = f"TreeGen用パラメータを生成してください: {prompt_text} | id:{tag}"
    return [{"role":"system","content":system_msg},{"role":"user","content":user_msg}]

def main():
    import os
    t0=time.perf_counter()
    arg_path=sys.argv[1]
    with open(arg_path,"r",encoding="utf-8") as f:
        args=json.load(f)
    model_path=args["model_path"]
    schema=args["schema"]
    n_ctx=args.get("n_ctx",4096)
    n_threads=args.get("n_threads",8)
    n_gpu_layers=args.get("n_gpu_layers",0)
    n_batch=args.get("n_batch",512)
    cache_prompt=args.get("cache_prompt", True)
    prompt=args["prompt"]

    # Import llama_cpp（LlamaGrammar は任意扱い）
    try:
        from llama_cpp import Llama
        try:
            from llama_cpp import LlamaGrammar
        except Exception:
            LlamaGrammar = None
    except Exception as e:
        print(json.dumps({"ok":False,"violations":{"error":f"llama import failed: {e}"}}, ensure_ascii=False))
        return

    # モデルロード & 文法（失敗したら grammar=None でフォールバック）
    try:
        llm=Llama(model_path=model_path, n_ctx=n_ctx, n_threads=n_threads,
                  n_gpu_layers=n_gpu_layers, n_batch=n_batch,
                  cache_prompt=cache_prompt, use_mmap=True, logits_all=False, seed=0, verbose=False)
        grammar=None
        if LlamaGrammar is not None:
            try:
                grammar=LlamaGrammar.from_string(_gbnf_for_schema(schema))
            except Exception:
                grammar=None  # フォールバック
    except Exception as e:
        print(json.dumps({"ok":False,"violations":{"error":f"load failed: {type(e).__name__}: {e}"}}, ensure_ascii=False))
        return

    messages=_messages(_build_spec_block(schema), prompt, random.randint(100000,999999))
    try:
        kwargs=dict(messages=messages, temperature=0.4, top_p=0.9, max_tokens=420,
                    seed=random.randint(0,2**31-1))
        if grammar is not None:
            kwargs["grammar"]=grammar
        try:
            out=llm.create_chat_completion(**kwargs)
        except TypeError as e:
            if "grammar" in str(e):
                kwargs.pop("grammar", None)
                out=llm.create_chat_completion(**kwargs)
            else:
                raise
        raw=(out["choices"][0]["message"]["content"] or "").strip()
        print(json.dumps({"ok":True,"raw":raw,"elapsed":time.perf_counter()-t0}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok":False,"violations":{"error":f"gen failed: {type(e).__name__}: {e}"}}, ensure_ascii=False))

if __name__=="__main__":
    main()
'''
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
    except Exception as e:
        logger.error(f"write worker failed: {e}")
    return path

def run_llm_hard(prompt_text: str, cancel_event: threading.Event | None, model_path: str, schema: dict) -> dict:
    """
    別プロセスで推論。Cancelでkillして確実に停止。
    - Blender 同梱 Python を使用
    - 親プロセスの sys.path を PYTHONPATH として子に伝播
    """
    t0 = time.perf_counter()
    if not os.path.exists(model_path):
        return {"ok":False,"params":None,"elapsed":0.0,"confidence":0.0,"raw":None,
                "clipped":None,"violations":{"error":"model_missing"},"model":"(unset)"}
    if not schema:
        return {"ok":False,"params":None,"elapsed":0.0,"confidence":0.0,"raw":None,
                "clipped":None,"violations":{"error":"schema_missing"},"model":os.path.basename(model_path)}

    worker = _ensure_worker_script()
    # 引数は一旦JSONファイル経由で渡す（Windowsのcmd長制限を回避）
    tmpdir = os.path.join(addon_root(), "_tmp")
    ensure_dir(tmpdir)
    arg_path = os.path.join(tmpdir, f"args_{int(time.time()*1000)}_{random.randint(1000,9999)}.json")
    gen = Generator.instance()
    args = {
        "model_path": model_path,
        "schema": schema,
        "n_ctx": Generator.instance().n_ctx,
        "n_threads": Generator.instance().n_threads,
        "n_gpu_layers": Generator.instance().n_gpu_layers,
        "n_batch": Generator.instance().n_batch,
        "cache_prompt": Generator.instance().cache_prompt,
        "prompt": prompt_text,
    }

    with open(arg_path, "w", encoding="utf-8") as f:
        json.dump(args, f, ensure_ascii=False)

    # 起動（Blender 同梱 Python を優先）
    py = getattr(bpy.app, "binary_path_python", None) or sys.executable
    logger.info(f"HARD mode using interpreter: {py}")

    # 親の sys.path を子プロセスに引き継ぐ（拡張の wheels を可視化）
    env = os.environ.copy()
    parent_paths = [p for p in sys.path if isinstance(p, str)]
    existing_pp = env.get("PYTHONPATH")
    if existing_pp:
        env["PYTHONPATH"] = os.pathsep.join(parent_paths + [existing_pp])
    else:
        env["PYTHONPATH"] = os.pathsep.join(parent_paths)

    proc = subprocess.Popen(
        [py, "-u", worker, arg_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    # 現在のタスクに紐づけ
    task = _get_task()
    if task is not None:
        task.proc = proc

    try:
        # ポーリングしつつキャンセル監視
        while True:
            if cancel_event is not None and cancel_event.is_set():
                try:
                    proc.terminate()
                    time.sleep(0.25)
                    if proc.poll() is None:
                        proc.kill()
                except Exception:
                    pass
                return {"ok":False,"params":None,"elapsed":time.perf_counter()-t0,"confidence":0.0,
                        "raw":None,"clipped":None,"violations":{"error":"canceled"},
                        "model":os.path.basename(model_path)}
            if proc.poll() is not None:
                break
            time.sleep(0.05)

        out, err = proc.communicate(timeout=0.1)
        if not out:
            return {"ok":False,"params":None,"elapsed":time.perf_counter()-t0,"confidence":0.0,
                    "raw":None,"clipped":None,"violations":{"error":f"subproc_no_output", "stderr": (err or '')[-512:]},
                    "model":os.path.basename(model_path)}
        payload = json.loads(out)
        if payload.get("ok"):
            raw = (payload.get("raw") or "").strip()
            if not raw:
                return {"ok":False,"params":None,"elapsed":time.perf_counter()-t0,"confidence":0.0,
                        "raw":None,"clipped":None,"violations":{"error":"empty_response"},
                        "model":os.path.basename(model_path)}
            m = re.search(r"\{.*\}", raw, flags=re.S)
            json_text = m.group(0) if m else raw
            parsed = json.loads(json_text)
            validated, clipped, violations = validate_and_clip(parsed, schema)
            conf = confidence_score(validated, defaults_from_schema(schema), clipped)
            return {"ok":True,"params":validated,"elapsed":payload.get("elapsed", time.perf_counter()-t0),
                    "confidence":conf,"raw":raw,"clipped":clipped or None,"violations":violations or None,
                    "model":os.path.basename(model_path)}
        else:
            return {"ok":False,"params":None,"elapsed":time.perf_counter()-t0,"confidence":0.0,
                    "raw":None,"clipped":None,"violations":payload.get("violations") or {"error":"subproc_failed"},
                    "model":os.path.basename(model_path)}
    except Exception as e:
        return {"ok":False,"params":None,"elapsed":time.perf_counter()-t0,"confidence":0.0,
                "raw":None,"clipped":None,"violations":{"error":f"subproc_error: {type(e).__name__}: {e}"},
                "model":os.path.basename(model_path)}
    finally:
        try:
            if os.path.exists(arg_path):
                os.remove(arg_path)
        except Exception:
            pass

# ------------------------- Operators (Prefs side) -------------------------
class TREE_OT_LoadGenerator(bpy.types.Operator):
    bl_idname="treegen.load_generator"; bl_label="Setup"
    def execute(self,_):
        # ① 進捗表示のため Windows ではシステムコンソールを開く
        _console_open_for_progress()

        gen=Generator.instance()
        ok=gen.ensure_models(auto_download=True)
        if not ok:
            # エラー時はコンソールを開いたままにしてログ確認しやすくする
            _popup_go_prefs("Model download failed.\nOpen Preferences > Add-ons > Tree Gen LLM and press 'Setup'.")
            self.report({'ERROR'},"Model download failed (see console)."); return {'CANCELLED'}
        try: gen.load(gen.default_model_path())
        except Exception as e:
            # ロード失敗時もログ確認のため閉じない
            _popup_go_prefs(f"LLM load failed: {e}\nPlace GGUF in /models and press 'Refresh Model Path'.")
            self.report({'ERROR'},f"LLM load failed: {e}"); return {'CANCELLED'}

        # ② 成功したら自動クローズ（TreeGen が開いた場合のみ）
        _console_close_if_opened_by_us()

        prefs=bpy.context.preferences.addons[__name__].preferences
        prefs.model_path=gen.model_path
        self.report({'INFO'},"Generator loaded."); return {'FINISHED'}

class TREE_OT_OpenModelsFolder(bpy.types.Operator):
    bl_idname="treegen.open_models_folder"; bl_label="Open Models Folder"
    def execute(self,_):
        folder=os.path.join(addon_root(),"models"); ensure_dir(folder)
        try:
            if sys.platform=="win32": os.startfile(folder)  # noqa
            elif sys.platform=="darwin": subprocess.Popen(["open",folder])
            else: subprocess.Popen(["xdg-open",folder])
        except Exception as e:
            _popup_go_prefs(f"Open failed: {e}"); return {'CANCELLED'}
        return {'FINISHED'}

class TREE_OT_RefreshModelPath(bpy.types.Operator):
    bl_idname="treegen.refresh_model_path"; bl_label="Refresh Model Path"
    def execute(self,_):
        gen=Generator.instance(); gen._load_manifest(); gen._list_downloaded_models()
        resolved=gen.default_model_path(); prefs=bpy.context.preferences.addons[__name__].preferences
        if resolved and os.path.exists(resolved):
            prefs.model_path=resolved; self.report({'INFO'},f"Model path set: {os.path.basename(resolved)}")
            return {'FINISHED'}
        _popup_go_prefs("No GGUF found under /models.\nPlace the file and press 'Refresh Model Path' again.")
        return {'CANCELLED'}

class TREE_OT_Cancel(bpy.types.Operator):
    bl_idname="treegen.cancel"; bl_label="Cancel"
    def execute(self, context):
        task=_get_task(); wm=context.window_manager
        if task is not None:
            task.cancel_event.set()
            if task.proc is not None:
                try:
                    if task.proc.poll() is None:
                        task.proc.terminate()
                        time.sleep(0.25)
                        if task.proc.poll() is None:
                            task.proc.kill()
                except Exception:
                    pass
        _end_progress(wm)
        wm.treegen_busy=False
        wm.treegen_engine_busy=True  # stopping...
        self.report({'INFO'}, "Cancel requested. Waiting for the engine to stop.")
        return {'FINISHED'}

# ------------------------- Generate / Reset -------------------------
class TREE_OT_Generate(bpy.types.Operator):
    bl_idname="treegen.generate"
    bl_label="Generate"  # 表示名を「Generate」に統一
    bl_description="Natural language -> Geometry Nodes parameters"

    def execute(self, context):
        wm=context.window_manager
        if wm.treegen_engine_busy or INFER_LOCK.locked():
            self.report({'WARNING'}, "Engine is busy (running or stopping). Please wait.")
            return {'CANCELLED'}

        props=context.scene.treegen_props
        prompt=props.prompt.strip()
        if not prompt:
            self.report({'WARNING'}, "プロンプトが空です"); return {'CANCELLED'}
        if not SC:
            bpy.context.window_manager.popup_menu(
                lambda s,c: (s.layout.label(text="Socket schema (user_socket_schema.py) が読み込まれていません。"),
                             s.layout.label(text="同梱ファイルの配置を確認してください。")),
                title="Schema Missing", icon='ERROR'); return {'CANCELLED'}

        # モデル解決
        prefs=bpy.context.preferences.addons[__name__].preferences
        model_path=bpy.path.abspath(prefs.model_path)
        if (not model_path) or (not os.path.exists(model_path)):
            gen=Generator.instance(); ok=gen.ensure_models(auto_download=True)
            if ok:
                resolved=gen.default_model_path()
                if os.path.exists(resolved):
                    prefs.model_path=resolved; model_path=resolved
        if (not model_path) or (not os.path.exists(model_path)):
            _popup_go_prefs("Qwen2.5-7B GGUF not found.\nOpen Preferences > Add-ons > Tree Gen LLM and press 'Setup'.")
            self.report({'ERROR'}, "Model missing. Go to Preferences to Setup."); return {'CANCELLED'}

        wm.treegen_engine_busy=True
        wm.treegen_busy=True
        _start_continuous_progress(wm)
        t = _new_task()
        wm["treegen_t0"]=time.perf_counter()

        schema_copy = json.loads(json.dumps(SC))
        cancel_mode = prefs.cancel_mode

        threading.Thread(
            target=self._worker,
            args=(prompt, model_path, schema_copy, context.window_manager, t, cancel_mode),
            daemon=True
        ).start()
        self.report({'INFO'}, "Running LLM...")
        return {'FINISHED'}

    def _worker(self, prompt_text: str, model_path: str, schema_copy: dict, wm, task: _Task, cancel_mode: str):
        try:
            t1=time.perf_counter()
            use_hard = (cancel_mode == 'HARD') or (cancel_mode == 'AUTO' and not _supports_abort_callback())
            if use_hard:
                result = run_llm_hard(prompt_text, task.cancel_event, model_path, schema_copy)
            else:
                result = run_llm_soft(prompt_text, task.cancel_event, model_path, schema_copy)
            t2=time.perf_counter()

            def _apply():
                try:
                    if task.cancel_event.is_set():
                        logger.info("Canceled. Skipping apply.")
                        _end_progress(wm); wm.treegen_busy=False; wm.treegen_engine_busy=False
                        _clear_task_if(task); return None
                    ret=_apply_result(prompt_text, result, wm, t1, t2)
                    _clear_task_if(task); return ret
                finally:
                    wm.treegen_engine_busy=False

            bpy.app.timers.register(_apply, first_interval=0.0)
        except Exception as e:
            err=f"{type(e).__name__}: {e}"
            logger.error("worker error: "+err)
            def _err():
                _end_progress(wm); wm.treegen_busy=False; wm.treegen_engine_busy=False
                _clear_task_if(task)
                bpy.context.window_manager.popup_menu(
                    lambda s,c: s.layout.label(text=err), title="TreeGen Error", icon='ERROR'
                ); return None
            bpy.app.timers.register(_err, first_interval=0.0)

class TREE_OT_Reset(bpy.types.Operator):
    bl_idname="treegen.reset"; bl_label="Reset"
    bl_description="Delete active TreeGen object (mesh) and reset properties"
    def execute(self, context):
        wm=context.window_manager
        if wm.treegen_engine_busy or INFER_LOCK.locked():
            self.report({'WARNING'}, "Engine is running/stopping. Cancel first."); return {'CANCELLED'}
        if bpy.ops.object.mode_set.poll():
            try: bpy.ops.object.mode_set(mode='OBJECT')
            except Exception: pass
        obj=bpy.context.active_object; removed=False
        if obj and obj.modifiers.get("TreeGen"):
            name=obj.name
            try: bpy.data.objects.remove(obj, do_unlink=True); removed=True
            except Exception as e: self.report({'ERROR'}, f"Delete failed: {e}")
        p=context.scene.treegen_props; p.generated_text=""
        if not removed: self.report({'INFO'}, "No active TreeGen object. Properties were reset.")
        else: self.report({'INFO'}, f"Deleted '{name}' (TreeGen object).")
        return {'FINISHED'}

# ------------------------- Popup helpers -------------------------
def _popup_go_prefs(message: str):
    def _draw(s,c):
        for line in message.splitlines(): s.layout.label(text=line)
        s.layout.separator()
        r=s.layout.row(align=True)
        try: r.operator("preferences.addon_show", text="Open Preferences", icon='PREFERENCES').module=__name__
        except Exception: r.label(text="Open: Edit > Preferences > Add-ons > Tree Gen LLM")
    bpy.context.window_manager.popup_menu(_draw, title="Setup Required", icon='ERROR')

# ------------------------- Apply result (main thread) -------------------------
def _apply_result(prompt_text, result: dict, wm, t1, t2):
    try:
        ok=result.get("ok",False)
        if not ok:
            _end_progress(wm); wm.treegen_busy=False
            logger.error(f"LLM failed: {result}")
            return None

        # 生成は推論成功後にのみ行う
        obj=spawn_new_object(name_base="TreeGen")

        # GN確保（ensure_gn_modifier が未定義でもフォールバック）
        try:
            mod,ng=ensure_gn_modifier(obj)
        except NameError:
            ng=load_node_group() or try_append_node_group("TreeNodeGen", absolute_path("TreeNodeGen.blend"))
            if not ng:
                raise RuntimeError("Failed to resolve Node Group (TreeNodeGen).")
            mod = obj.modifiers.get("TreeGen") or obj.modifiers.new("TreeGen", type='NODES')
            mod.node_group = ng

        if not mod or not ng:
            raise RuntimeError("Failed to create Geometry Nodes modifier.")

        # デフォルト適用
        for k,v in CUSTOM_DEFAULTS.items():
            try: mod[k]=v
            except Exception: pass

        # LLM出力適用
        params=result.get("params",{})
        cleaned_json_text=json.dumps(params, ensure_ascii=False)
        for k,v in params.items():
            try: mod[k]=v
            except Exception as e: logger.warning(f"Failed to set {k}={v}: {e}")

        # UIのMaterial/Collectionの追従
        props=bpy.context.scene.treegen_props
        if getattr(props,"material",None):
            try: mod["Socket_2"]=props.material
            except Exception: pass
        if getattr(props,"collection",None):
            try: mod["Socket_43"]=props.collection
            except Exception: pass
        props.generated_text=cleaned_json_text

        _end_progress(wm); wm.treegen_busy=False

        t0=bpy.context.window_manager.get("treegen_t0",None)
        t3=time.perf_counter()
        if t0 is not None and t1 is not None and t2 is not None:
            llm_sec=t2-t1; apply_sec=t3-t2; ttv_sec=t3-t0
            logger.info(f"[Metrics] LLM: {llm_sec:.2f}s | Apply: {apply_sec:.2f}s | TTV: {ttv_sec:.2f}s")
            bpy.context.window_manager["treegen_last_ttv"]=ttv_sec
        else:
            bpy.context.window_manager["treegen_last_ttv"]=None

        logger.info(f"OK model={result.get('model')} conf={result.get('confidence'):.2f}")
        if result.get("clipped"): logger.info(f"clipped: {result['clipped']}")
        if result.get("violations"): logger.info(f"violations: {result['violations']}")
    except Exception as e:
        _end_progress(wm); wm.treegen_busy=False
        err=f"{type(e).__name__}: {e}"; logger.error("apply error: "+err)
        bpy.context.window_manager.popup_menu(lambda s,c: s.layout.label(text=err), title="TreeGen Error", icon='ERROR')
    return None

# ------------------------- Panel -------------------------
class TREE_PT_Main(bpy.types.Panel):
    bl_label="Tree Gen LLM"; bl_idname="TREE_PT_main"
    bl_space_type='VIEW_3D'; bl_region_type='UI'; bl_category="Tree Gen LLM"
    def draw(self, context):
        layout=self.layout; wm=context.window_manager
        props=context.scene.treegen_props
        prefs=bpy.context.preferences.addons[__name__].preferences

        box=layout.box(); box.label(text="Model")
        mdl_path=bpy.path.abspath(prefs.model_path)
        box.label(text=f"7B: {os.path.basename(mdl_path) or 'unset'}")
        exists=os.path.exists(mdl_path)
        box.label(text=("7B Model: OK" if exists else "7B Model: Missing"),
                  icon=('CHECKMARK' if exists else 'ERROR'))
        if not exists: box.label(text="Go to Preferences > Add-ons > Tree Gen LLM > Setup", icon='INFO')

        # 縦並び：ステータス行とCancelを直列表示
        if wm.treegen_busy:
            box.label(text="Status: Running...", icon='TIME')
            box.operator("treegen.cancel", text="Cancel", icon='CANCEL')
        elif wm.treegen_engine_busy or INFER_LOCK.locked():
            box.label(text="Status: Stopping...", icon='CANCEL')
        else:
            box.label(text="Status: Idle", icon='CHECKMARK')

        ttv=bpy.context.window_manager.get("treegen_last_ttv",None)
        if ttv is not None: box.label(text=f"TTV(last): {ttv:.2f}s")

        layout.prop(props,"prompt", text="Prompt")
        row=layout.row(align=True)
        row.enabled = not (wm.treegen_engine_busy or INFER_LOCK.locked())
        row.operator("treegen.generate", icon='PLAY')
        row.operator("treegen.reset", icon='TRASH')

        col=layout.column(align=True)
        col.prop(props,"material",  text="Wood Material")  # ラベル明示
        col.prop(props,"collection",text="leaf")           # ラベル明示

        obj=bpy.context.active_object
        if obj:
            mod=obj.modifiers.get("TreeGen")
            if mod:
                layout.separator(); params_box=layout.box(); params_box.label(text="Parameters")
                ng=getattr(mod,"node_group",None)
                if ng:
                    try: ensure_all_input_idprops(mod, ng)
                    except Exception: pass
                    draw_parameters_grouped(params_box, mod, ng)
                else:
                    params_box.label(text="(no Node Group)", icon='ERROR')

# ------------------------- Register -------------------------
classes=(
    TreeGenPreferences, TreeGenProperties,
    TREE_OT_LoadGenerator, TREE_OT_OpenModelsFolder, TREE_OT_RefreshModelPath,
    TREE_OT_Cancel, TREE_OT_Generate, TREE_OT_Reset,
    TREE_PT_Main,
)

def register():
    for c in classes: bpy.utils.register_class(c)
    bpy.types.Scene.treegen_props=bpy.props.PointerProperty(type=TreeGenProperties)
    _wm_props_register()

def unregister():
    _wm_props_unregister()
    del bpy.types.Scene.treegen_props
    for c in reversed(classes): bpy.utils.unregister_class(c)

if __name__=="__main__":
    register()

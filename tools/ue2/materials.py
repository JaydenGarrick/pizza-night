"""Resolve UE2 material graphs (Shader/Combiner/FinalBlend/...) to a base Texture, and cache GLB textures."""
from .props import object_props
from .package import ObjRef
from .texture import load_texture


def resolve_material(ref):
    info = {"alpha": None, "two_sided": False, "emissive": None, "size": None}
    seen = 0
    while ref and seen < 8:
        seen += 1
        p, e = ref.resolve()
        if not e: return None, info
        cls = e.cls.lower()
        props, _, _ = object_props(p, e)
        if cls == "texture":
            if props.get("bMasked"): info["alpha"] = "MASK"
            elif props.get("bAlphaTexture"): info["alpha"] = "BLEND"
            info["size"] = (props.get("USize", 256), props.get("VSize", 256))
            return (p, e), info
        if cls == "shader":
            if props.get("TwoSided"): info["two_sided"] = True
            if props.get("OutputBlending", 0) in (1, 2, 3, 4) and props.get("Opacity"): info["alpha"] = "BLEND"
            si = props.get("SelfIllumination")
            if isinstance(si, ObjRef) and si:
                pp, ee = si.resolve()
                if ee and ee.cls.lower() == "texture": info["emissive"] = (pp, ee)
            ref = props.get("Diffuse")
        elif cls == "combiner":
            ref = props.get("Material1") or props.get("Material2")
        elif cls == "finalblend":
            if props.get("TwoSided"): info["two_sided"] = True
            if props.get("AlphaTest"): info["alpha"] = "MASK"
            elif props.get("FrameBufferBlending", 0) != 0: info["alpha"] = "BLEND"
            ref = props.get("Material")
        elif cls in ("texmodifier", "texpanner", "texscaler", "texrotator", "texoscillator", "texcoordsource", "texenvmap", "materialswitch", "materialsequence", "texmatrix"):
            ref = props.get("Material") or props.get("Materials")
            if hasattr(ref, "objs"): ref = ref.objs()[0]
        elif cls in ("vertexcolor", "constantcolor", "fadecolor", "cubemap", "scriptedtexture", "movietexture"):
            return None, info
        else:
            ref = props.get("Diffuse") or props.get("Material")
    return None, info


class TextureCache:
    def __init__(self, glb, dump_dir=None):
        self.glb = glb; self.cache = {}; self.dump_dir = dump_dir
    def index(self, pe):
        p, e = pe; key = (p.name, e.name)
        if key not in self.cache:
            img, props = load_texture(p, e)
            if self.dump_dir:
                from pathlib import Path
                Path(self.dump_dir).mkdir(parents=True, exist_ok=True); img.save(Path(self.dump_dir) / f"{p.name}.{e.name}.png")
            self.cache[key] = self.glb.image_png(img, f"{p.name}.{e.name}")
        return self.cache[key]

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pure-Python glTF 2.0 (.glb) Optimizer for 4-Floor Architectural Viewer.
Reads raw exported GLBs from Pascal导入/ and writes mobile/desktop-optimized GLBs to models/:
1. Strips KHR_materials_transmission -> fast BLEND glass (eliminates full-scene 2nd FBO pass).
2. Deduplicates & compresses textures (<=1024px baseline JPEG q=82 color, <=512px JPEG q=75 normal/rough,
   compact <=512px PNG only for true alpha-transparent textures).
3. Batches static sub-meshes by (floor/prefix/material) while preserving:
   - CEILING_PREFIXES (for Hide Ceilings toggle)
   - WALL_PREFIXES & _Walls_Manifold (for Hide Walls toggle & initial cutaway)
   - Interactive individual doors, drawers, bevel louvers, stone lions, and hero moon-gate/mural nodes
4. Verifies exact triangle count parity, global bounding-box parity (< 2 mm), and valid glTF 2.0 binary alignment.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import struct
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "Pascal导入"
OUT_DIR = BASE_DIR / "models"
BACKUP_DIR = BASE_DIR / "models_raw"

FLOORS = ["B2", "B1", "1F", "2F"]

CEILING_PREFIXES = (
    "1F_Living_Ceiling_",
    "1F_Kaspar_Ceiling_",
    "B1_Ceiling_",
    "2F_NorthBed_HeadCove_",
    "2F_NorthBed_OppCab_CeilingCove",
    "2F_NorthBed_OppCab_CeilingLED",
    "2F_MBR_OppCab_Soffit",
    "2F_MBR_Vanity_Soffit",
    "2F_MBR_HeadWall_Soffit",
    "2F_WIC_N_Bulkhead_",
    "2F_WIC_S_Bulkhead_",
    "2F_WIC_DispS_Bulkhead",
    "2F_WIC_DispN_Bulkhead",
    "2F_ChildTatami_Soffit",
    "2F_ChildWall_Soffit",
    "2F_ChildWIC_Soffit_",
    "2F_SW_Laundry_Soffit",
    "2F_SW_Utility_Soffit",
    "2F_NorthBed_OppCab_Soffit",
    "2F_NorthBed_Wardrobe_Soffit",
)

WALL_PREFIXES = (
    "B2_Wall_West_Full",
    "B2_Wall_North_Full",
    "B2_Wall_South_Full",
    "B2_Wall_East_",
    "B1_East_Skylight_",
    "B2_East_Skylight_",
    "1F_Living_CurvedWall",
    "1F_Dining_WestReturn_BackWall",
    "1F_Dining_EastReturn_HallWall",
    "1F_Win_",
    "2F_CurvedWall_Parent",
    "2F_WIC_Partition_",
    "2F_Win_",
)

PRESERVE_EXACT = {
    "1F_Living_Fireplace_MoonGateWall",
    "1F_Living_Fireplace_LingnanWallpaper",
}
INTERACTIVE_RE = re.compile(r"(door|leaf|slant|drw|drawer|lion)", re.I)
FROSTED_GLASS_RE = re.compile(r"(frost|flut|changhong|acrylic|mirror|blue_sphere)", re.I)

COMP_NP_DTYPE = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}
TYPE_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


def _quat_to_mat4(q: List[float]) -> np.ndarray:
    x, y, z, w = [float(v) for v in q]
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return np.array(
        [
            [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy), 0.0],
            [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx), 0.0],
            [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy), 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def _node_local_mat4(node: Dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    t = node.get("translation", [0.0, 0.0, 0.0])
    r = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    s = node.get("scale", [1.0, 1.0, 1.0])
    mt = np.eye(4, dtype=np.float64)
    mt[:3, 3] = [float(v) for v in t]
    mr = _quat_to_mat4(r)
    ms = np.diag([float(s[0]), float(s[1]), float(s[2]), 1.0])
    return mt @ mr @ ms


def _read_accessor(gltf: Dict[str, Any], bin_buf: bytes, acc_idx: int) -> np.ndarray:
    acc = gltf["accessors"][acc_idx]
    bv = gltf["bufferViews"][acc["bufferView"]]
    dt = COMP_NP_DTYPE[acc["componentType"]]
    ncomp = TYPE_COUNTS[acc["type"]]
    count = int(acc["count"])
    bv_off = int(bv.get("byteOffset", 0))
    acc_off = int(acc.get("byteOffset", 0))
    elem_bytes = np.dtype(dt).itemsize * ncomp
    stride = int(bv.get("byteStride") or elem_bytes)
    start = bv_off + acc_off
    if stride == elem_bytes:
        arr = np.frombuffer(bin_buf, dtype=dt, count=count * ncomp, offset=start).reshape(count, ncomp)
    else:
        raw = np.frombuffer(bin_buf, dtype=np.uint8, count=count * stride, offset=start).reshape(count, stride)
        arr = np.frombuffer(raw[:, :elem_bytes].tobytes(), dtype=dt).reshape(count, ncomp)
    arr = arr.copy()
    if acc.get("normalized") and acc["componentType"] != 5126:
        if acc["componentType"] == 5121:
            arr = arr.astype(np.float32) / 255.0
        elif acc["componentType"] == 5123:
            arr = arr.astype(np.float32) / 65535.0
        elif acc["componentType"] == 5120:
            arr = np.maximum(arr.astype(np.float32) / 127.0, -1.0)
        elif acc["componentType"] == 5122:
            arr = np.maximum(arr.astype(np.float32) / 32767.0, -1.0)
    return arr[:, 0] if ncomp == 1 else arr


def _classify_node(floor_key: str, name: str, mat_idx: int) -> Tuple[str, str]:
    if name in PRESERVE_EXACT or INTERACTIVE_RE.search(name):
        return ("KEEP", name)
    for pfx in CEILING_PREFIXES:
        if name.startswith(pfx):
            return ("CEIL", f"{pfx}Batch_M{mat_idx}")
    if "_Walls_Manifold" in name or any(name.startswith(pfx) for pfx in WALL_PREFIXES):
        return ("WALL", f"{floor_key}_Walls_Manifold_Batch_M{mat_idx}")
    parts = [p for p in name.split("_") if p]
    pfx2 = "_".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else f"{floor_key}_Static")
    return ("STATIC", f"{pfx2}_Batch_M{mat_idx}")


def _collect_image_roles(gltf: Dict[str, Any]) -> Tuple[set, set]:
    color_imgs, data_imgs = set(), set()
    textures = gltf.get("textures", [])
    for mat in gltf.get("materials", []):
        pbr = mat.get("pbrMetallicRoughness", {})
        if "baseColorTexture" in pbr:
            t_idx = pbr["baseColorTexture"]["index"]
            if t_idx < len(textures) and "source" in textures[t_idx]:
                color_imgs.add(textures[t_idx]["source"])
        if "emissiveTexture" in mat:
            t_idx = mat["emissiveTexture"]["index"]
            if t_idx < len(textures) and "source" in textures[t_idx]:
                color_imgs.add(textures[t_idx]["source"])
        for key in ("normalTexture", "occlusionTexture"):
            if key in mat:
                t_idx = mat[key]["index"]
                if t_idx < len(textures) and "source" in textures[t_idx]:
                    data_imgs.add(textures[t_idx]["source"])
        if "metallicRoughnessTexture" in pbr:
            t_idx = pbr["metallicRoughnessTexture"]["index"]
            if t_idx < len(textures) and "source" in textures[t_idx]:
                data_imgs.add(textures[t_idx]["source"])
    for idx, im in enumerate(gltf.get("images", [])):
        nm = (im.get("name") or "").lower()
        if any(k in nm for k in ("_bump", "_normal", "_rough", "_norm", "normal_")):
            data_imgs.add(idx)
    return color_imgs, data_imgs


def _compress_image(raw_bytes: bytes, mime: str, is_data_only: bool) -> Tuple[bytes, str, Tuple[int, int]]:
    im = Image.open(io.BytesIO(raw_bytes))
    max_edge = 512 if is_data_only else 1024
    has_real_alpha = False
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        alpha_min = rgba.getchannel("A").getextrema()[0]
        if alpha_min < 248:
            has_real_alpha = True
            max_edge = 512
            if max(rgba.size) > max_edge:
                rgba.thumbnail((max_edge, max_edge), Image.LANCZOS)
            buf = io.BytesIO()
            rgba.save(buf, format="PNG", optimize=True)
            out_b = buf.getvalue()
            if len(out_b) < len(raw_bytes) or max(im.size) > max_edge:
                return out_b, "image/png", rgba.size
            return raw_bytes, "image/png", im.size

    rgb = im.convert("RGB")
    if max(rgb.size) > max_edge:
        rgb.thumbnail((max_edge, max_edge), Image.LANCZOS)
    q = 75 if is_data_only else 82
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=q, optimize=True, progressive=False, subsampling=1)
    out_b = buf.getvalue()
    if mime == "image/jpeg" and max(im.size) <= max_edge and len(out_b) >= len(raw_bytes):
        return raw_bytes, "image/jpeg", im.size
    return out_b, "image/jpeg", rgb.size


def optimize_floor_glb(floor_key: str, src_path: Path, dst_path: Path) -> Dict[str, Any]:
    raw = src_path.read_bytes()
    orig_size = len(raw)
    magic, ver, _ = struct.unpack_from("<III", raw, 0)
    assert magic == 0x46546C67 and ver == 2, f"Not GLB v2: {src_path}"
    c0_len, c0_type = struct.unpack_from("<II", raw, 12)
    assert c0_type == 0x4E4F534A
    gltf = json.loads(raw[20 : 20 + c0_len].decode("utf-8"))
    c1_len, c1_type = struct.unpack_from("<II", raw, 20 + c0_len)
    assert c1_type == 0x004E4942
    bin_off = 20 + c0_len + 8
    old_bin = raw[bin_off : bin_off + c1_len]

    # Measure original baseline (triangles + global world bbox)
    old_nodes = gltf.get("nodes", [])
    old_meshes = gltf.get("meshes", [])
    old_bv = gltf.get("bufferViews", [])
    root_indices = gltf.get("scenes", [{}])[0].get("nodes", list(range(len(old_nodes))))

    world_entries: List[Tuple[int, np.ndarray]] = []

    def _walk(ni: int, parent_m: np.ndarray) -> None:
        node = old_nodes[ni]
        m = parent_m @ _node_local_mat4(node)
        if "mesh" in node:
            world_entries.append((ni, m))
        for ch in node.get("children", []):
            _walk(ch, m)

    for rn in root_indices:
        _walk(rn, np.eye(4, dtype=np.float64))

    orig_tris = 0
    orig_prims = 0
    orig_min = np.array([np.inf, np.inf, np.inf], dtype=np.float64)
    orig_max = np.array([-np.inf, -np.inf, -np.inf], dtype=np.float64)

    for ni, wm in world_entries:
        m = old_meshes[old_nodes[ni]["mesh"]]
        for pr in m.get("primitives", []):
            orig_prims += 1
            pos = _read_accessor(gltf, old_bin, pr["attributes"]["POSITION"]).astype(np.float64)
            wpos = (wm[:3, :3] @ pos.T).T + wm[:3, 3]
            orig_min = np.minimum(orig_min, wpos.min(axis=0))
            orig_max = np.maximum(orig_max, wpos.max(axis=0))
            if "indices" in pr:
                orig_tris += gltf["accessors"][pr["indices"]]["count"] // 3
            else:
                orig_tris += len(pos) // 3

    # 1. Strip KHR_materials_transmission -> fast BLEND glass
    materials = gltf.get("materials", [])
    for mat in materials:
        ext = mat.get("extensions")
        if ext and "KHR_materials_transmission" in ext:
            del ext["KHR_materials_transmission"]
            if not ext:
                del mat["extensions"]
            mat["alphaMode"] = "BLEND"
            pbr = mat.setdefault("pbrMetallicRoughness", {})
            bcf = list(pbr.get("baseColorFactor", [0.88, 0.93, 0.95, 1.0]))
            is_frosted = bool(FROSTED_GLASS_RE.search(mat.get("name", "")))
            bcf[3] = 0.54 if is_frosted else 0.26
            pbr["baseColorFactor"] = bcf
            pbr["roughnessFactor"] = 0.32 if is_frosted else 0.08

    for k_ext in ("extensionsUsed", "extensionsRequired"):
        if k_ext in gltf:
            gltf[k_ext] = [e for e in gltf[k_ext] if e != "KHR_materials_transmission"]
            if not gltf[k_ext]:
                del gltf[k_ext]

    # 2. Compress & deduplicate images into new binary builder
    new_bin = bytearray()
    new_bvs: List[Dict[str, Any]] = []
    new_accs: List[Dict[str, Any]] = []
    new_imgs: List[Dict[str, Any]] = []

    def _append_bytes(data: bytes, target: Optional[int] = None) -> int:
        while len(new_bin) % 4 != 0:
            new_bin.append(0)
        off = len(new_bin)
        new_bin.extend(data)
        while len(new_bin) % 4 != 0:
            new_bin.append(0)
        bv_entry: Dict[str, Any] = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target is not None:
            bv_entry["target"] = target
        new_bvs.append(bv_entry)
        return len(new_bvs) - 1

    color_imgs, data_imgs = _collect_image_roles(gltf)
    old_imgs = gltf.get("images", [])
    old_to_new_img: Dict[int, int] = {}
    dedup_raw: Dict[bytes, int] = {}
    orig_img_bytes = 0
    opt_img_bytes = 0
    max_tex_px = 0

    for idx, im in enumerate(old_imgs):
        bvi = im.get("bufferView")
        if bvi is None:
            continue
        v = old_bv[bvi]
        off = int(v.get("byteOffset", 0))
        raw_img = old_bin[off : off + int(v["byteLength"])]
        orig_img_bytes += len(raw_img)
        raw_sha = hashlib.sha256(raw_img).digest()
        if raw_sha in dedup_raw:
            old_to_new_img[idx] = dedup_raw[raw_sha]
            continue
        is_data_only = (idx in data_imgs) and (idx not in color_imgs)
        comp_bytes, out_mime, (iw, ih) = _compress_image(raw_img, im.get("mimeType", ""), is_data_only)
        max_tex_px = max(max_tex_px, iw, ih)
        bv_id = _append_bytes(comp_bytes)
        new_img_entry = {"bufferView": bv_id, "mimeType": out_mime}
        if "name" in im:
            new_img_entry["name"] = im["name"]
        new_imgs.append(new_img_entry)
        new_idx = len(new_imgs) - 1
        old_to_new_img[idx] = new_idx
        dedup_raw[raw_sha] = new_idx
        opt_img_bytes += len(comp_bytes)

    new_textures = gltf.get("textures", [])
    for tx in new_textures:
        if "source" in tx and tx["source"] in old_to_new_img:
            tx["source"] = old_to_new_img[tx["source"]]

    # 3. Classify meshes & batch static sub-meshes while preserving interactive/ceiling/wall semantics
    keep_items: List[Tuple[str, np.ndarray, int, Dict[str, Any]]] = []
    batch_groups: Dict[Tuple[str, str, int, int, Tuple[str, ...]], List[Tuple[np.ndarray, Dict[str, Any]]]] = defaultdict(list)

    for ni, wm in world_entries:
        node = old_nodes[ni]
        nname = node.get("name") or f"Node_{ni}"
        mesh = old_meshes[node["mesh"]]
        for pr in mesh.get("primitives", []):
            mat_idx = int(pr.get("material", 0))
            kind, batch_name = _classify_node(floor_key, nname, mat_idx)
            mode = int(pr.get("mode", 4))
            attr_keys = tuple(sorted(k for k in pr.get("attributes", {}).keys() if k in ("POSITION", "NORMAL", "TEXCOORD_0")))
            if kind == "KEEP" or mode != 4:
                keep_items.append((nname, wm, ni, pr))
            else:
                batch_groups[(kind, batch_name, mat_idx, mode, attr_keys)].append((wm, pr))

    def _emit_primitive(
        pos: np.ndarray,
        nrm: Optional[np.ndarray],
        uv0: Optional[np.ndarray],
        indices: np.ndarray,
        mat_idx: int,
        mode: int = 4,
    ) -> Dict[str, Any]:
        attrs: Dict[str, int] = {}
        pos32 = np.ascontiguousarray(pos, dtype=np.float32)
        bv_p = _append_bytes(pos32.tobytes(), target=34962)
        new_accs.append({
            "bufferView": bv_p,
            "componentType": 5126,
            "count": int(len(pos32)),
            "type": "VEC3",
            "min": [float(v) for v in pos32.min(axis=0)],
            "max": [float(v) for v in pos32.max(axis=0)],
        })
        attrs["POSITION"] = len(new_accs) - 1

        if nrm is not None:
            nrm32 = np.ascontiguousarray(nrm, dtype=np.float32)
            bv_n = _append_bytes(nrm32.tobytes(), target=34962)
            new_accs.append({
                "bufferView": bv_n,
                "componentType": 5126,
                "count": int(len(nrm32)),
                "type": "VEC3",
            })
            attrs["NORMAL"] = len(new_accs) - 1

        if uv0 is not None:
            uv32 = np.ascontiguousarray(uv0, dtype=np.float32)
            bv_u = _append_bytes(uv32.tobytes(), target=34962)
            new_accs.append({
                "bufferView": bv_u,
                "componentType": 5126,
                "count": int(len(uv32)),
                "type": "VEC2",
            })
            attrs["TEXCOORD_0"] = len(new_accs) - 1

        max_idx = int(indices.max()) if len(indices) else 0
        if max_idx <= 65535 and len(pos32) <= 65535:
            idx_arr = np.ascontiguousarray(indices, dtype=np.uint16)
            idx_ct = 5123
        else:
            idx_arr = np.ascontiguousarray(indices, dtype=np.uint32)
            idx_ct = 5125
        bv_i = _append_bytes(idx_arr.tobytes(), target=34963)
        new_accs.append({
            "bufferView": bv_i,
            "componentType": idx_ct,
            "count": int(len(idx_arr)),
            "type": "SCALAR",
        })
        return {
            "attributes": attrs,
            "indices": len(new_accs) - 1,
            "material": mat_idx,
            "mode": mode,
        }

    new_meshes: List[Dict[str, Any]] = []
    new_nodes: List[Dict[str, Any]] = []

    # Emit preserved individual nodes (keeping their exact local coords + world TRS/matrix untouched)
    for nname, wm, orig_ni, pr in keep_items:
        pos = _read_accessor(gltf, old_bin, pr["attributes"]["POSITION"])
        nrm = _read_accessor(gltf, old_bin, pr["attributes"]["NORMAL"]) if "NORMAL" in pr["attributes"] else None
        uv0 = _read_accessor(gltf, old_bin, pr["attributes"]["TEXCOORD_0"]) if "TEXCOORD_0" in pr["attributes"] else None
        if "indices" in pr:
            indices = _read_accessor(gltf, old_bin, pr["indices"])
        else:
            indices = np.arange(len(pos), dtype=np.uint32)
        new_pr = _emit_primitive(pos, nrm, uv0, indices, int(pr.get("material", 0)), int(pr.get("mode", 4)))
        mesh_idx = len(new_meshes)
        new_meshes.append({"name": nname, "primitives": [new_pr]})
        node_out: Dict[str, Any] = {"name": nname, "mesh": mesh_idx}
        if not np.allclose(wm, np.eye(4, dtype=np.float64), atol=1e-7):
            node_out["matrix"] = [float(v) for v in wm.T.flatten()]
        new_nodes.append(node_out)

    # Emit batched static nodes
    for (kind, batch_name, mat_idx, mode, attr_keys), entries in sorted(batch_groups.items()):
        pos_chunks: List[np.ndarray] = []
        nrm_chunks: List[np.ndarray] = []
        uv0_chunks: List[np.ndarray] = []
        idx_chunks: List[np.ndarray] = []
        v_offset = 0
        has_nrm = "NORMAL" in attr_keys
        has_uv0 = "TEXCOORD_0" in attr_keys

        for wm, pr in entries:
            pos = _read_accessor(gltf, old_bin, pr["attributes"]["POSITION"]).astype(np.float64)
            wpos = ((wm[:3, :3] @ pos.T).T + wm[:3, 3]).astype(np.float32)
            pos_chunks.append(wpos)

            if has_nrm:
                nrm = _read_accessor(gltf, old_bin, pr["attributes"]["NORMAL"]).astype(np.float64)
                lin = wm[:3, :3]
                try:
                    nmat = np.linalg.inv(lin).T
                except np.linalg.LinAlgError:
                    nmat = np.eye(3, dtype=np.float64)
                wnrm = (nmat @ nrm.T).T
                lens = np.linalg.norm(wnrm, axis=1, keepdims=True)
                wnrm = np.where(lens > 1e-8, wnrm / np.maximum(lens, 1e-8), np.array([0.0, 1.0, 0.0]))
                nrm_chunks.append(wnrm.astype(np.float32))

            if has_uv0:
                uv0 = _read_accessor(gltf, old_bin, pr["attributes"]["TEXCOORD_0"]).astype(np.float32)
                uv0_chunks.append(uv0)

            if "indices" in pr:
                idx = _read_accessor(gltf, old_bin, pr["indices"]).astype(np.uint32)
            else:
                idx = np.arange(len(pos), dtype=np.uint32)
            if np.linalg.det(wm[:3, :3]) < 0.0:
                tri = idx.reshape(-1, 3)[:, [0, 2, 1]].reshape(-1)
                idx = tri
            idx_chunks.append(idx + v_offset)
            v_offset += len(wpos)

        m_pos = np.concatenate(pos_chunks, axis=0)
        m_nrm = np.concatenate(nrm_chunks, axis=0) if has_nrm else None
        m_uv0 = np.concatenate(uv0_chunks, axis=0) if has_uv0 else None
        m_idx = np.concatenate(idx_chunks, axis=0)

        new_pr = _emit_primitive(m_pos, m_nrm, m_uv0, m_idx, mat_idx, mode)
        mesh_idx = len(new_meshes)
        new_meshes.append({"name": batch_name, "primitives": [new_pr]})
        new_nodes.append({"name": batch_name, "mesh": mesh_idx})

    out_gltf: Dict[str, Any] = {
        "asset": gltf.get("asset", {"version": "2.0", "generator": "optimize_glbs.py"}),
        "scene": 0,
        "scenes": [{"name": floor_key, "nodes": list(range(len(new_nodes)))}],
        "nodes": new_nodes,
        "meshes": new_meshes,
        "materials": materials,
        "accessors": new_accs,
        "bufferViews": new_bvs,
        "buffers": [{"byteLength": len(new_bin)}],
    }
    if new_textures:
        out_gltf["textures"] = new_textures
    if new_imgs:
        out_gltf["images"] = new_imgs
    if gltf.get("samplers"):
        out_gltf["samplers"] = gltf["samplers"]
    for k_ext in ("extensionsUsed", "extensionsRequired"):
        if k_ext in gltf:
            out_gltf[k_ext] = gltf[k_ext]

    # Verify geometry parity BEFORE writing final GLB
    opt_tris = 0
    opt_min = np.array([np.inf, np.inf, np.inf], dtype=np.float64)
    opt_max = np.array([-np.inf, -np.inf, -np.inf], dtype=np.float64)
    out_bin_bytes = bytes(new_bin)
    for node in new_nodes:
        wm = _node_local_mat4(node)
        pr = new_meshes[node["mesh"]]["primitives"][0]
        pos = _read_accessor(out_gltf, out_bin_bytes, pr["attributes"]["POSITION"]).astype(np.float64)
        wpos = (wm[:3, :3] @ pos.T).T + wm[:3, 3]
        opt_min = np.minimum(opt_min, wpos.min(axis=0))
        opt_max = np.maximum(opt_max, wpos.max(axis=0))
        opt_tris += new_accs[pr["indices"]]["count"] // 3

    assert opt_tris == orig_tris, f"{floor_key}: triangle mismatch opt={opt_tris} vs orig={orig_tris}"
    bbox_err = float(max(np.max(np.abs(opt_min - orig_min)), np.max(np.abs(opt_max - orig_max))))
    assert bbox_err < 0.002, f"{floor_key}: bbox drift {bbox_err:.5f}m >= 2mm"
    assert "KHR_materials_transmission" not in out_gltf.get("extensionsUsed", []), f"{floor_key}: transmission left behind!"

    # Write spec-compliant 4-byte-aligned GLB v2
    json_bytes = json.dumps(out_gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    while len(json_bytes) % 4 != 0:
        json_bytes += b" "
    bin_bytes = bytearray(new_bin)
    while len(bin_bytes) % 4 != 0:
        bin_bytes.append(0)
    total_len = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with dst_path.open("wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total_len))
        f.write(struct.pack("<II", len(json_bytes), 0x4E4F534A))
        f.write(json_bytes)
        f.write(struct.pack("<II", len(bin_bytes), 0x004E4942))
        f.write(bin_bytes)

    return {
        "floor": floor_key,
        "orig_mb": orig_size / 1e6,
        "opt_mb": total_len / 1e6,
        "orig_draws": orig_prims,
        "opt_draws": len(new_nodes),
        "tris": opt_tris,
        "orig_img_mb": orig_img_bytes / 1e6,
        "opt_img_mb": opt_img_bytes / 1e6,
        "max_tex_px": max_tex_px,
        "bbox_err_mm": bbox_err * 1000.0,
    }


def main() -> None:
    t0 = time.time()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    # Non-destructive one-time backup of previous models/*.glb if not already present
    if OUT_DIR.is_dir():
        for fk in FLOORS:
            cur = OUT_DIR / f"{fk}.glb"
            bak = BACKUP_DIR / f"{fk}.glb"
            if cur.is_file() and not bak.is_file():
                bak.write_bytes(cur.read_bytes())

    rows = []
    for fk in FLOORS:
        src = RAW_DIR / f"{fk}.glb"
        dst = OUT_DIR / f"{fk}.glb"
        assert src.is_file(), f"Missing raw GLB: {src}"
        rows.append(optimize_floor_glb(fk, src, dst))

    print("\n=== GLB OPTIMIZATION SUMMARY ===")
    tot_o = sum(r["orig_mb"] for r in rows)
    tot_n = sum(r["opt_mb"] for r in rows)
    tot_do = sum(r["orig_draws"] for r in rows)
    tot_dn = sum(r["opt_draws"] for r in rows)
    tot_io = sum(r["orig_img_mb"] for r in rows)
    tot_in = sum(r["opt_img_mb"] for r in rows)
    for r in rows:
        print(
            f"  {r['floor']:2s}: {r['orig_mb']:5.2f}MB -> {r['opt_mb']:5.2f}MB | "
            f"draws {r['orig_draws']:4d} -> {r['opt_draws']:3d} | "
            f"tex {r['orig_img_mb']:5.2f}MB -> {r['opt_img_mb']:4.2f}MB (max {r['max_tex_px']}px) | "
            f"tris={r['tris']:,} | bbox_err={r['bbox_err_mm']:.3f}mm"
        )
    print(
        f"  TOTAL: {tot_o:.2f}MB -> {tot_n:.2f}MB (-{(1-tot_n/tot_o)*100:.1f}%) | "
        f"draws {tot_do} -> {tot_dn} (-{(1-tot_dn/tot_do)*100:.1f}%) | "
        f"tex {tot_io:.2f}MB -> {tot_in:.2f}MB | KHR_materials_transmission=0 | elapsed={time.time()-t0:.2f}s"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build the complete 4-Floor House 3D Model from `4层家装（11.2）.dwg` (converted to DXF).
Uses a 2D rectilinear grid manifold builder for walls to guarantee ZERO coplanar/Z-fighting faces
and crystal-clear window/door openings.
Generates:
  - /Users/muwusah/Documents/AI/Architect/house/4层家装_3D模型/4层家装_11.2.blend
  - /Users/muwusah/Documents/AI/Architect/house/4层家装_3D模型/4层家装_11.2.glb (Stacked 4-floor model)
  - /Users/muwusah/Documents/AI/Architect/house/4层家装_3D模型/4层家装_11.2_展开展示.glb (Side-by-side 4-floor showcase)
  - /Users/muwusah/Documents/AI/Architect/house/4层家装_3D模型/4层家装_11.2.obj & .mtl
  - High-resolution Cycles preview renders:
      * preview_all_4floors_showcase.png
      * preview_stacked_cutaway.png
      * preview_1F_一层.png
      * preview_2F_二层.png
      * preview_B1_B2_地下室.png
"""

import os
import sys
import math
import random
import shutil

sys.path.insert(0, "/Users/muwusah/Documents/AI/Architect/house/家具/lib")
import ezdxf
import numpy as np

import bpy
import bmesh
import mathutils
from mathutils import Vector

DXF_PATH = "/Users/muwusah/.gemini/antigravity/brain/fb2de22a-d6ab-46ee-8c97-9a324f2a5d11/scratch/floor4_11_2.dxf"
OUT_DIR = "/Users/muwusah/Documents/AI/Architect/house/4层家装_3D模型"
os.makedirs(OUT_DIR, exist_ok=True)

PLANS = {
    "B2_Base": {"xr": (32000, 44000),   "yr": (43000, 54000), "orig": (35198.57, 50763.39), "z0": -4.55, "h": 2.35},
    "B1_Mezz": {"xr": (10000, 23000),   "yr": (43000, 54000), "orig": (13489.01, 51199.78), "z0": -2.05, "h": 1.90},
    "1F_Plan": {"xr": (-42000, -24000), "yr": (43000, 54000), "orig": (-33628.55, 49986.37), "z0":  0.00, "h": 3.15},
    "1F_Beam": {"xr": (-42000, -24000), "yr": (68000, 78500), "orig": (-32688.95, 74830.95), "z0":  0.00, "h": 3.15},
    "2F_Plan": {"xr": (-18000, 4000),   "yr": (43000, 54000), "orig": (-4784.94, 49986.37),  "z0":  3.30, "h": 2.83},
    "2F_Beam": {"xr": (-18000, 4000),   "yr": (68000, 78500), "orig": (-7575.51, 75569.02),  "z0":  3.30, "h": 2.83},
}

MM = 0.001  # mm to meters

# ---------------------------------------------------------------------------
# Materials Library
# ---------------------------------------------------------------------------
MATS = {}

def make_mat(name, rgba, metallic=0.0, roughness=0.5, transmission=0.0, alpha=1.0, emission=None, emission_strength=0.0):
    if name in MATS:
        return MATS[name]
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        if "Transmission Weight" in bsdf.inputs:
            bsdf.inputs["Transmission Weight"].default_value = transmission
        elif "Transmission" in bsdf.inputs:
            bsdf.inputs["Transmission"].default_value = transmission
        if transmission > 0.0 and "IOR" in bsdf.inputs:
            bsdf.inputs["IOR"].default_value = 1.05
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = alpha
        if emission is not None:
            if "Emission Color" in bsdf.inputs:
                bsdf.inputs["Emission Color"].default_value = emission
            elif "Emission" in bsdf.inputs:
                bsdf.inputs["Emission"].default_value = emission
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = emission_strength
    if alpha < 1.0 or transmission > 0.0:
        mat.blend_method = 'BLEND'
    MATS[name] = mat
    return mat

def make_img_mat(name, img_path, fallback_rgba=(0.8, 0.8, 0.8, 1.0), metallic=0.0, roughness=0.18, emission_strength=0.0, repeat=False):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = fallback_rgba
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        if os.path.exists(img_path):
            tex_node = nt.nodes.new("ShaderNodeTexImage")
            tex_node.image = bpy.data.images.load(img_path, check_existing=True)
            try:
                tex_node.image.pack()
            except Exception:
                pass
            tex_node.extension = 'REPEAT' if repeat else 'EXTEND'
            nt.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
            if emission_strength > 0.0:
                if "Emission Color" in bsdf.inputs:
                    nt.links.new(tex_node.outputs["Color"], bsdf.inputs["Emission Color"])
                elif "Emission" in bsdf.inputs:
                    nt.links.new(tex_node.outputs["Color"], bsdf.inputs["Emission"])
                if "Emission Strength" in bsdf.inputs:
                    bsdf.inputs["Emission Strength"].default_value = emission_strength
    MATS[name] = mat
    return mat

def init_materials():
    MATS.clear()
    make_mat("Wall_Struct",      (0.92, 0.91, 0.89, 1.0), metallic=0.05, roughness=0.60)  # rev. 2026-10-28: walls white
    make_mat("Wall_New",         (0.88, 0.84, 0.78, 1.0), metallic=0.0,  roughness=0.50)
    make_mat("Beam_Concrete",    (0.78, 0.77, 0.75, 1.0), metallic=0.0,  roughness=0.65)
    make_mat("Slab_Wood",        (0.74, 0.58, 0.42, 1.0), metallic=0.0,  roughness=0.40)
    make_mat("Slab_Stone",       (0.82, 0.81, 0.79, 1.0), metallic=0.0,  roughness=0.32)
    # 1F Floor Material: 浅青色水晶石 (Pale Celadon Crystal Stone with distinct celadon jade-cyan hue & soft satin finish, rev. 2026-11-06)
    _cel_mat = make_mat(
        "Floor_Celadon_White_Marble",
        (0.50, 0.82, 0.74, 1.0),
        metallic=0.0,
        roughness=0.28,
        emission=(0.45, 0.80, 0.72, 1.0),
        emission_strength=0.10
    )
    _cel_nt = _cel_mat.node_tree
    _cel_bsdf = _cel_nt.nodes.get("Principled BSDF")
    if _cel_bsdf is not None:
        for _k, _v in (("Subsurface Weight", 0.10), ("Specular IOR Level", 0.16), ("Coat Weight", 0.0)):
            if _k in _cel_bsdf.inputs:
                _cel_bsdf.inputs[_k].default_value = _v
        try:
            # Eliminate green GI color bleed onto white ceiling & walls while keeping direct floor appearance identical
            _lp = _cel_nt.nodes.new("ShaderNodeLightPath")
            _mix_gi = _cel_nt.nodes.new("ShaderNodeMix")
            _mix_gi.data_type = 'RGBA'
            _mix_gi.inputs[6].default_value = (0.50, 0.82, 0.74, 1.0)
            _mix_gi.inputs[7].default_value = (0.82, 0.81, 0.79, 1.0)
            _cel_nt.links.new(_lp.outputs["Is Diffuse Ray"], _mix_gi.inputs[0])
            _cel_nt.links.new(_mix_gi.outputs[2], _cel_bsdf.inputs["Base Color"])
            _mix_em = _cel_nt.nodes.new("ShaderNodeMix")
            _mix_em.data_type = 'FLOAT'
            _mix_em.inputs[2].default_value = 0.10
            _mix_em.inputs[3].default_value = 0.00
            _cel_nt.links.new(_lp.outputs["Is Diffuse Ray"], _mix_em.inputs[0])
            if "Emission Strength" in _cel_bsdf.inputs:
                _cel_nt.links.new(_mix_em.outputs[0], _cel_bsdf.inputs["Emission Strength"])
        except Exception:
            pass

    # Unified photorealistic matte gypsum plaster material for ALL 1F ceiling & header elements (AO + normal grazing + micro-bevel, zero board seams)
    _ceil_m = make_mat("Pure_White_Ceiling", (0.83, 0.82, 0.79, 1.0), metallic=0.0, roughness=0.68)
    _ceil_nt = _ceil_m.node_tree
    _ceil_bsdf = _ceil_nt.nodes.get("Principled BSDF")
    if _ceil_bsdf is not None:
        if "Specular IOR Level" in _ceil_bsdf.inputs:
            _ceil_bsdf.inputs["Specular IOR Level"].default_value = 0.10
        try:
            _ao = _ceil_nt.nodes.new("ShaderNodeAmbientOcclusion")
            _ao.samples = 16
            _ao.inputs["Distance"].default_value = 0.36
            _gamma_ao = _ceil_nt.nodes.new("ShaderNodeGamma")
            _gamma_ao.inputs["Gamma"].default_value = 1.25
            _ceil_nt.links.new(_ao.outputs["AO"], _gamma_ao.inputs["Color"])

            # Subtle physical grazing & pocket depth response on sculpted wave vaults (continuous 0 at z<=2.570m flat ceiling)
            _geom = _ceil_nt.nodes.new("ShaderNodeNewGeometry")
            _sep_p = _ceil_nt.nodes.new("ShaderNodeSeparateXYZ")
            _sep_n = _ceil_nt.nodes.new("ShaderNodeSeparateXYZ")
            _ceil_nt.links.new(_geom.outputs["Position"], _sep_p.inputs["Vector"])
            _ceil_nt.links.new(_geom.outputs["Normal"], _sep_n.inputs["Vector"])

            # Height factor above flat ceiling plane z=2.570m: 0 on all flat ceilings, 0..1 inside wave vaults (z=2.570..2.785m)
            _map_z = _ceil_nt.nodes.new("ShaderNodeMapRange")
            _map_z.clamp = True
            _map_z.inputs["From Min"].default_value = 2.574
            _map_z.inputs["From Max"].default_value = 2.785
            _map_z.inputs["To Min"].default_value = 0.0
            _map_z.inputs["To Max"].default_value = 1.0
            _ceil_nt.links.new(_sep_p.outputs["Z"], _map_z.inputs["Value"])

            # Slope grazing factor from East window (+X): nx > 0 faces East window, nx < 0 faces away
            _map_nx = _ceil_nt.nodes.new("ShaderNodeMapRange")
            _map_nx.clamp = True
            _map_nx.inputs["From Min"].default_value = -0.36
            _map_nx.inputs["From Max"].default_value = 0.36
            _map_nx.inputs["To Min"].default_value = -0.09
            _map_nx.inputs["To Max"].default_value = 0.07
            _ceil_nt.links.new(_sep_n.outputs["X"], _map_nx.inputs["Value"])

            # Combine pocket depth darkening (-0.06 * map_z) + grazing slope modulation (map_nx * map_z)
            _mul_pocket = _ceil_nt.nodes.new("ShaderNodeMath")
            _mul_pocket.operation = 'MULTIPLY'
            _mul_pocket.inputs[1].default_value = -0.06
            _ceil_nt.links.new(_map_z.outputs["Result"], _mul_pocket.inputs[0])

            _mul_graz = _ceil_nt.nodes.new("ShaderNodeMath")
            _mul_graz.operation = 'MULTIPLY'
            _ceil_nt.links.new(_map_nx.outputs["Result"], _mul_graz.inputs[0])
            _ceil_nt.links.new(_map_z.outputs["Result"], _mul_graz.inputs[1])

            _add_sculpt = _ceil_nt.nodes.new("ShaderNodeMath")
            _add_sculpt.operation = 'ADD'
            _ceil_nt.links.new(_mul_pocket.outputs["Value"], _add_sculpt.inputs[0])
            _ceil_nt.links.new(_mul_graz.outputs["Value"], _add_sculpt.inputs[1])

            _add_ao = _ceil_nt.nodes.new("ShaderNodeMath")
            _add_ao.operation = 'ADD'
            _add_ao.use_clamp = True
            _ceil_nt.links.new(_gamma_ao.outputs["Color"], _add_ao.inputs[0])
            _ceil_nt.links.new(_add_sculpt.outputs["Value"], _add_ao.inputs[1])

            _mix_ao = _ceil_nt.nodes.new("ShaderNodeMix")
            _mix_ao.data_type = 'RGBA'
            _mix_ao.clamp_factor = True
            _mix_ao.inputs[6].default_value = (0.48, 0.47, 0.45, 1.0)  # Deep architectural shadow in tight creases/recesses
            _mix_ao.inputs[7].default_value = (0.85, 0.84, 0.81, 1.0)  # Lit warm-white gypsum plaster
            _ceil_nt.links.new(_add_ao.outputs["Value"], _mix_ao.inputs[0])
            _ceil_nt.links.new(_mix_ao.outputs[2], _ceil_bsdf.inputs["Base Color"])

            _bev = _ceil_nt.nodes.new("ShaderNodeBevel")
            _bev.samples = 4
            _bev.inputs["Radius"].default_value = 0.0025
            _ceil_nt.links.new(_bev.outputs["Normal"], _ceil_bsdf.inputs["Normal"])
        except Exception:
            pass
    MATS["Ceiling_Flat_West"] = _ceil_m
    MATS["Header_Soft_White"] = _ceil_m
    MATS["Header_Shadow_Warm"] = _ceil_m
    MATS["Wave_Sculpted_Ceiling"] = _ceil_m
    make_mat("B1_Oval_Dome_White", (0.96, 0.95, 0.93, 1.0), metallic=0.0, roughness=0.45)
    make_mat("Slab_Tile_Bath",   (0.86, 0.87, 0.88, 1.0), metallic=0.0,  roughness=0.22)
    make_mat("Platform_Oak",     (0.64, 0.46, 0.30, 1.0), metallic=0.0,  roughness=0.36)
    make_mat("Stair_Tread_Oak",  (0.70, 0.52, 0.35, 1.0), metallic=0.0,  roughness=0.35)
    make_mat("Stair_Balustrade", (0.95, 0.93, 0.90, 1.0), metallic=0.05, roughness=0.32)
    make_mat("Stair_Iron",       (0.16, 0.17, 0.19, 1.0), metallic=0.88, roughness=0.30)
    make_mat("Handrail_Bronze",  (0.30, 0.23, 0.17, 1.0), metallic=0.75, roughness=0.28)
    # Handrail steel finish (rev. 2026-10-28): gold velvet art paint 金色天鹅绒艺术漆 – satin gold with soft sheen
    _gv = make_mat("Gold_Velvet_ArtPaint", (0.80, 0.63, 0.36, 1.0), metallic=0.60, roughness=0.50)
    _gv_bsdf = _gv.node_tree.nodes.get("Principled BSDF")
    if _gv_bsdf is not None:
        for _k, _v in (("Sheen Weight", 0.6), ("Sheen", 0.6), ("Sheen Roughness", 0.45), ("Coat Weight", 0.15)):
            if _k in _gv_bsdf.inputs:
                _gv_bsdf.inputs[_k].default_value = _v
    make_mat("Window_Frame",     (0.18, 0.19, 0.21, 1.0), metallic=0.80, roughness=0.25)
    make_mat("Window_Glass",     (0.96, 0.98, 0.99, 0.25), metallic=0.0, roughness=0.04, transmission=0.90, alpha=0.25)
    make_mat("Door_Wood",        (0.48, 0.33, 0.21, 1.0), metallic=0.0,  roughness=0.38)
    make_mat("Door_Frame",       (0.34, 0.24, 0.15, 1.0), metallic=0.1,  roughness=0.42)
    make_mat("Cabinet_Walnut",   (0.42, 0.29, 0.19, 1.0), metallic=0.0,  roughness=0.36)
    make_mat("Cabinet_Cream",    (0.90, 0.87, 0.82, 1.0), metallic=0.0,  roughness=0.34)
    make_mat("Counter_Marble",   (0.94, 0.93, 0.92, 1.0), metallic=0.0,  roughness=0.18)
    make_mat("Sofa_Fabric",      (0.84, 0.81, 0.76, 1.0), metallic=0.0,  roughness=0.78)
    make_mat("Accent_Leather",   (0.62, 0.37, 0.24, 1.0), metallic=0.0,  roughness=0.42)
    make_mat("Bed_Linen",        (0.92, 0.90, 0.87, 1.0), metallic=0.0,  roughness=0.72)
    make_mat("Bed_Throw",        (0.45, 0.52, 0.58, 1.0), metallic=0.0,  roughness=0.75)
    make_mat("Rug_Warm",         (0.78, 0.75, 0.70, 1.0), metallic=0.0,  roughness=0.88)
    make_mat("Sanitary_White",   (0.97, 0.97, 0.98, 1.0), metallic=0.05, roughness=0.12)
    make_mat("Feature_Dark",     (0.22, 0.21, 0.20, 1.0), metallic=0.15, roughness=0.38)
    make_mat("Fireplace_Glow",   (0.98, 0.48, 0.14, 1.0), roughness=0.3, emission=(1.0, 0.45, 0.1, 1.0), emission_strength=3.5)
    make_mat("CAD_Line_Dark",    (0.16, 0.17, 0.19, 1.0), metallic=0.0,  roughness=0.50)
    # OLO Kitchen & Foyer Custom Materials (matching reference front rendering)
    make_mat("OLO_Cab_White",    (0.92, 0.91, 0.89, 1.0), metallic=0.0,  roughness=0.28)
    make_mat("OLO_Cab_Greige",   (0.76, 0.75, 0.73, 1.0), metallic=0.0,  roughness=0.34)
    make_mat("OLO_Black_Backsplash", (0.04, 0.04, 0.05, 1.0), metallic=0.10, roughness=0.14)
    make_mat("OLO_Oven_DarkGlass",   (0.18, 0.19, 0.20, 1.0), metallic=0.25, roughness=0.16)
    make_mat("OLO_ToeKick_Black",    (0.08, 0.08, 0.09, 1.0), metallic=0.10, roughness=0.42)
    make_mat("OLO_Niche_Frame",      (0.19, 0.14, 0.11, 1.0), metallic=0.15, roughness=0.30)
    make_mat("Plant_Bamboo_Green",   (0.20, 0.36, 0.18, 1.0), metallic=0.0,  roughness=0.45)
    # 1F Living Room TV Cabinet 8 Folding Doors & Dark-Green Marble Hearth Textures
    make_img_mat("TV_Green_Luxury_Stone", os.path.join(OUT_DIR, "tex_green_luxury_doors.png"), (0.68, 0.76, 0.70, 1.0), roughness=0.16)
    make_img_mat("TV_Dark_Green_Hearth",  os.path.join(OUT_DIR, "tex_dark_green_hearth.png"),  (0.18, 0.25, 0.21, 1.0), roughness=0.15)
    make_img_mat("TV_Ocean_Mural", os.path.join(OUT_DIR, "tex_tv_ocean_mural.jpg"), (0.55, 0.72, 0.70, 1.0), roughness=0.35)
    make_mat("Glass_Grid_Bronze", (0.50, 0.45, 0.36, 1.0), metallic=0.80, roughness=0.35)  # rev. 2026-10-29 foyer niche grid
    make_mat("Plant_Leaf_Deep", (0.16, 0.30, 0.15, 1.0), metallic=0.0, roughness=0.55)
    make_mat("Plant_Leaf_Light", (0.36, 0.52, 0.26, 1.0), metallic=0.0, roughness=0.50)
    make_mat("Plant_Blossom_Pink", (0.86, 0.66, 0.64, 1.0), metallic=0.0, roughness=0.60)
    make_img_mat("Dining_Marble_Veined", os.path.join(OUT_DIR, "tex_marble_dining.jpg"), (0.94, 0.93, 0.91, 1.0), roughness=0.2, repeat=True)  # rev. 2026-10-31
    make_img_mat("Door_CNC_Ripple_White", os.path.join(OUT_DIR, "tex_door_cnc_ripple.jpg"), (0.96, 0.96, 0.95, 1.0), roughness=0.45, repeat=True)  # rev. 2026-10-31 v5
    make_img_mat("Travertine_White", os.path.join(OUT_DIR, "tex_travertine_white.jpg"), (0.93, 0.91, 0.86, 1.0), roughness=0.55, repeat=True)
    make_img_mat("Plaster_Shell_White", os.path.join(OUT_DIR, "tex_plaster_shell.jpg"), (0.96, 0.96, 0.95, 1.0), roughness=0.8, repeat=True)
    make_img_mat("Door_CNC_Woven_White", os.path.join(OUT_DIR, "tex_door_cnc_woven.jpg"), (0.96, 0.96, 0.95, 1.0), roughness=0.45, repeat=True)  # rev. 2026-10-31 V5
    make_img_mat("Marble_Fishbelly", os.path.join(OUT_DIR, "tex_marble_fishbelly.jpg"), (0.95, 0.94, 0.92, 1.0), roughness=0.3, repeat=True)
    make_img_mat("Marble_Fishbelly_Bookmatch", os.path.join(OUT_DIR, "tex_marble_fishbelly_bookmatch.jpg"), (0.95, 0.94, 0.92, 1.0), roughness=0.3, repeat=False)
    _rg = make_img_mat("Glass_Ripple_Art", os.path.join(OUT_DIR, "tex_ripple_glass.png"), (0.82, 0.86, 0.76, 1.0), roughness=0.15, repeat=True)
    try:  # water-ripple art glass: drive alpha from the texture
        _tn = [n for n in _rg.node_tree.nodes if n.type == "TEX_IMAGE"]
        _bs = _rg.node_tree.nodes.get("Principled BSDF")
        if _tn and _bs: _rg.node_tree.links.new(_tn[0].outputs["Alpha"], _bs.inputs["Alpha"])
        _rg.blend_method = "BLEND"
    except Exception:
        pass
    # 1F Kaspar Foyer Partition & Living Room Custom Materials
    make_img_mat("Kaspar_Center_Stone",   os.path.join(OUT_DIR, "tex_kaspar_center_stone.png"), (0.72, 0.70, 0.65, 1.0), roughness=0.14)
    make_mat("Kaspar_Cream_Stone",        (0.91, 0.89, 0.85, 1.0), metallic=0.0,  roughness=0.35)
    make_mat("Kaspar_Black_Leather",      (0.08, 0.08, 0.09, 1.0), metallic=0.05, roughness=0.36)
    make_mat("Kaspar_Burgundy_Lacquer",   (0.36, 0.08, 0.07, 1.0), metallic=0.08, roughness=0.18)
    # Double-Height Basement (B2 & B1) Custom Materials
    _b2_tile_path = os.path.join(OUT_DIR, "tex_b2_marble_tile.jpg")
    if not os.path.exists(_b2_tile_path):
        _b2_tile_path = os.path.join(OUT_DIR, "tex_b2_marble_white_grey.jpg")
    make_img_mat("B2_Marble_Floor",       _b2_tile_path, (0.93, 0.94, 0.95, 1.0), roughness=0.10, repeat=True)
    make_img_mat("B2_TV_WaterRipple",     os.path.join(OUT_DIR, "tex_b2_water_ripple.png"), (0.91, 0.92, 0.94, 1.0), roughness=0.20, emission_strength=0.14, repeat=True)
    make_mat("StoneLion_Grey",            (0.76, 0.75, 0.73, 1.0), metallic=0.0, roughness=0.52)
    make_img_mat("B2_TV_Screen",          os.path.join(OUT_DIR, "tex_b2_tv_831.png"),          (0.05, 0.05, 0.05, 1.0), roughness=0.08, emission_strength=0.65)
    make_img_mat("B2_Wine_Cabinet",       os.path.join(OUT_DIR, "tex_b2_wine_cabinet.png"),    (0.35, 0.28, 0.20, 1.0), roughness=0.22, emission_strength=0.55)
    make_img_mat("B2_East_Win_Upper",     os.path.join(OUT_DIR, "tex_b2_east_win_upper.png"),  (0.25, 0.55, 0.65, 1.0), roughness=0.10, emission_strength=1.40)
    make_img_mat("B1_East_Win_Lower",     os.path.join(OUT_DIR, "tex_b1_east_win_lower.png"),  (0.75, 0.72, 0.58, 1.0), roughness=0.10, emission_strength=1.20)
    make_mat("Basement_Warm_Plaster",     (0.90, 0.87, 0.82, 1.0), metallic=0.0,  roughness=0.42)
    make_mat("Stair_Bronze_Iron",         (0.18, 0.15, 0.13, 1.0), metallic=0.82, roughness=0.28)
    make_mat("Warm_LED_Glow",             (1.00, 0.88, 0.68, 1.0), roughness=0.20, emission=(1.0, 0.85, 0.60, 1.0), emission_strength=1.8)
    make_mat("Warm_LED_Amber",            (1.00, 0.80, 0.45, 1.0), roughness=0.18, emission=(1.0, 0.76, 0.38, 1.0), emission_strength=2.2)
    make_mat("B1_Slant_TranslucentWood",  (0.96, 0.87, 0.72, 1.0), metallic=0.0, roughness=0.34, emission=(1.00, 0.82, 0.50, 1.0), emission_strength=0.68)
    make_mat("Gym_Bike_Red",              (0.76, 0.045, 0.055, 1.0), metallic=0.35, roughness=0.22)
    make_mat("East_Win_Sunlight_Sky",     (1.00, 0.95, 0.84, 1.0), roughness=0.20, emission=(1.0, 0.94, 0.80, 1.0), emission_strength=2.2)
    make_mat("Gold_Brass",                (0.78, 0.62, 0.35, 1.0), metallic=0.88, roughness=0.22)
    make_mat("Mirror_Silver",             (0.95, 0.95, 0.95, 1.0), metallic=1.0,  roughness=0.02)
    make_mat("Glass_Balustrade_Clear",    (0.88, 0.93, 0.94, 0.32), metallic=0.05, roughness=0.03, transmission=0.86, alpha=0.32)
    make_mat("B2_Backlit_Cream", (0.98, 0.93, 0.84, 1.0), metallic=0.0, roughness=0.35, emission=(1.0, 0.92, 0.78, 1.0), emission_strength=1.3)
    # 图 1 B2 Wine Cabinet Cool Ice-White Backlit Alabaster + Chrome Silver + Cool White LED + Crystal Glass
    _alab_mat = make_img_mat("B2_Backlit_Alabaster", os.path.join(OUT_DIR, "textures", "tex_b2_alabaster_back.png"), (0.90, 0.95, 0.98, 1.0), roughness=0.22)
    try:
        _al_nt = _alab_mat.node_tree
        _al_bsdf = _al_nt.nodes.get("Principled BSDF")
        _al_ep = os.path.join(OUT_DIR, "textures", "tex_b2_alabaster_emit.png")
        if _al_bsdf is not None and os.path.exists(_al_ep):
            _al_et = _al_nt.nodes.new("ShaderNodeTexImage")
            _al_et.image = bpy.data.images.load(_al_ep, check_existing=True)
            try:
                _al_et.image.pack()
            except Exception:
                pass
            _al_et.extension = 'EXTEND'
            if "Emission Color" in _al_bsdf.inputs:
                _al_nt.links.new(_al_et.outputs["Color"], _al_bsdf.inputs["Emission Color"])
            elif "Emission" in _al_bsdf.inputs:
                _al_nt.links.new(_al_et.outputs["Color"], _al_bsdf.inputs["Emission"])
            if "Emission Strength" in _al_bsdf.inputs:
                _al_bsdf.inputs["Emission Strength"].default_value = 1.65
    except Exception:
        pass
    make_mat("B2_Chrome_Silver",          (0.86, 0.89, 0.92, 1.0), metallic=0.98, roughness=0.08)
    make_mat("B2_CoolWhite_LED",          (0.94, 0.98, 1.00, 1.0), roughness=0.18, emission=(0.94, 0.98, 1.00, 1.0), emission_strength=3.6)
    make_mat("B2_Crystal_Glass",          (0.88, 0.95, 0.97, 0.34), metallic=0.05, roughness=0.04, transmission=0.88, alpha=0.34)
    # 图 4 B2 Tall Tea Cabinet (Beige Leather + Anodized Gunmetal + Cream Shelves)
    make_mat("B2_TallCab_BeigeLeather",   (0.79, 0.75, 0.68, 1.0), metallic=0.0,  roughness=0.52)
    make_mat("B2_TallCab_Gunmetal",       (0.20, 0.19, 0.18, 1.0), metallic=0.86, roughness=0.26)
    make_mat("B2_TallCab_CreamShelf",     (0.91, 0.89, 0.85, 1.0), metallic=0.0,  roughness=0.28)
    # 1F Living Room Radial B&W Contemporary Rug + Song Dining Wood + 图 5 Metallic Wire-Mesh Glass
    _bw_rug = make_img_mat("Living_Radial_BW_Rug", os.path.join(OUT_DIR, "textures", "tex_living_radial_bw_rug.png"), (0.76, 0.75, 0.72, 1.0), roughness=0.82)
    try:
        _rw_nt = _bw_rug.node_tree
        _rw_bsdf = _rw_nt.nodes.get("Principled BSDF")
        if _rw_bsdf is not None:
            for _rk, _rv in (("Sheen Weight", 0.45), ("Sheen Roughness", 0.65)):
                if _rk in _rw_bsdf.inputs:
                    _rw_bsdf.inputs[_rk].default_value = _rv
            _rw_bp = os.path.join(OUT_DIR, "textures", "tex_living_radial_bw_rug_bump.png")
            if os.path.exists(_rw_bp):
                _rw_bt = _rw_nt.nodes.new("ShaderNodeTexImage")
                _rw_bt.image = bpy.data.images.load(_rw_bp, check_existing=True)
                _rw_bt.image.colorspace_settings.name = 'Non-Color'
                try:
                    _rw_bt.image.pack()
                except Exception:
                    pass
                _rw_bmp = _rw_nt.nodes.new("ShaderNodeBump")
                _rw_bmp.inputs["Strength"].default_value = 0.25
                _rw_bmp.inputs["Distance"].default_value = 0.004
                _rw_nt.links.new(_rw_bt.outputs["Color"], _rw_bmp.inputs["Height"])
                _rw_nt.links.new(_rw_bmp.outputs["Normal"], _rw_bsdf.inputs["Normal"])
    except Exception:
        pass
    _sw_mat = make_mat("Dining_Song_Wood", (0.17, 0.10, 0.065, 1.0), metallic=0.0, roughness=0.26)
    try:
        _sw_bsdf = _sw_mat.node_tree.nodes.get("Principled BSDF")
        if _sw_bsdf is not None and "Coat Weight" in _sw_bsdf.inputs:
            _sw_bsdf.inputs["Coat Weight"].default_value = 0.18
            _sw_bsdf.inputs["Coat Roughness"].default_value = 0.16
    except Exception:
        pass
    _ob_mat = make_mat("Toshiba_Obsidian_Black", (0.018, 0.019, 0.022, 1.0), metallic=0.18, roughness=0.07)
    try:
        _ob_bsdf = _ob_mat.node_tree.nodes.get("Principled BSDF")
        if _ob_bsdf is not None and "Coat Weight" in _ob_bsdf.inputs:
            _ob_bsdf.inputs["Coat Weight"].default_value = 0.95
            _ob_bsdf.inputs["Coat Roughness"].default_value = 0.04
    except Exception:
        pass
    make_mat("Toshiba_Obsidian_Trim",       (0.05, 0.052, 0.058, 1.0), metallic=0.82, roughness=0.22)
    make_mat("VentShaft_Clear_White_Glass", (1.00, 1.00, 1.00, 0.22),  metallic=0.0,  roughness=0.05, transmission=0.0, alpha=0.22)
    make_mat("Kaspar_Pure_White",           (0.97, 0.97, 0.965, 1.0),  metallic=0.0,  roughness=0.36)
    _wm_mat = make_img_mat("Dining_WireMesh_Glass", os.path.join(OUT_DIR, "textures", "tex_wiremesh_glass_color.png"), (0.74, 0.70, 0.63, 1.0), metallic=0.48, roughness=0.22, repeat=True)
    try:
        _wm_nt = _wm_mat.node_tree
        _wm_bsdf = _wm_nt.nodes.get("Principled BSDF")
        if _wm_bsdf is not None:
            if "Coat Weight" in _wm_bsdf.inputs:
                _wm_bsdf.inputs["Coat Weight"].default_value = 0.65
                _wm_bsdf.inputs["Coat Roughness"].default_value = 0.05
            _wm_ap = os.path.join(OUT_DIR, "textures", "tex_wiremesh_glass_alpha.png")
            _wm_bp = os.path.join(OUT_DIR, "textures", "tex_wiremesh_glass_bump.png")
            if os.path.exists(_wm_ap):
                _wm_at = _wm_nt.nodes.new("ShaderNodeTexImage")
                _wm_at.image = bpy.data.images.load(_wm_ap, check_existing=True)
                _wm_at.image.colorspace_settings.name = 'Non-Color'
                try:
                    _wm_at.image.pack()
                except Exception:
                    pass
                _wm_at.extension = 'REPEAT'
                _wm_nt.links.new(_wm_at.outputs["Color"], _wm_bsdf.inputs["Alpha"])
                _wm_mat.blend_method = 'BLEND'
            if os.path.exists(_wm_bp):
                _wm_bt = _wm_nt.nodes.new("ShaderNodeTexImage")
                _wm_bt.image = bpy.data.images.load(_wm_bp, check_existing=True)
                _wm_bt.image.colorspace_settings.name = 'Non-Color'
                try:
                    _wm_bt.image.pack()
                except Exception:
                    pass
                _wm_bt.extension = 'REPEAT'
                _wm_bmp = _wm_nt.nodes.new("ShaderNodeBump")
                _wm_bmp.inputs["Strength"].default_value = 0.22
                _wm_bmp.inputs["Distance"].default_value = 0.002
                _wm_nt.links.new(_wm_bt.outputs["Color"], _wm_bmp.inputs["Height"])
                _wm_nt.links.new(_wm_bmp.outputs["Normal"], _wm_bsdf.inputs["Normal"])
    except Exception:
        pass
    # 图 2 2F North Bedroom Bedside Wardrobe Materials
    _ng_mat = make_mat("NorthBed_Wardrobe_GlossCream", (0.88, 0.85, 0.81, 1.0), metallic=0.0, roughness=0.10)
    try:
        _ng_bsdf = _ng_mat.node_tree.nodes.get("Principled BSDF")
        if _ng_bsdf is not None and "Coat Weight" in _ng_bsdf.inputs:
            _ng_bsdf.inputs["Coat Weight"].default_value = 0.65
            _ng_bsdf.inputs["Coat Roughness"].default_value = 0.05
    except Exception:
        pass
    make_mat("NorthBed_Smoked_Mirror",    (0.09, 0.085, 0.085, 1.0), metallic=0.88, roughness=0.05)
    make_mat("NorthBed_JadeBlack_Pull",   (0.09, 0.13, 0.11, 1.0), metallic=0.35, roughness=0.16)
    make_mat("Wine_Bottle_Red", (0.22, 0.03, 0.04, 1.0), metallic=0.1, roughness=0.12)
    make_mat("Shelf_Back_Linen", (0.86, 0.82, 0.75, 1.0), metallic=0.0, roughness=0.55)
    make_mat("Cabinet_Charcoal", (0.1, 0.1, 0.11, 1.0), metallic=0.1, roughness=0.4)
    make_mat("Book_Cream", (0.92, 0.9, 0.85, 1.0), metallic=0.0, roughness=0.6)
    make_mat("Wall_Panel_White", (0.93, 0.92, 0.9, 1.0), metallic=0.0, roughness=0.4)
    make_mat("Oak_Veneer", (0.55, 0.42, 0.31, 1.0), metallic=0.0, roughness=0.55)
    make_mat("Linen_Cushion", (0.84, 0.79, 0.7, 1.0), metallic=0.0, roughness=0.9)
    make_mat("Mirror_Bronze", (0.55, 0.47, 0.41, 1.0), metallic=1.0, roughness=0.06)
    make_mat("Wardrobe_WaveGrain", (0.86, 0.84, 0.8, 1.0), metallic=0.0, roughness=0.7)
    make_mat("RoseGold_Metal", (0.8, 0.58, 0.48, 1.0), metallic=0.9, roughness=0.25)
    make_mat("Glass_Smoked_Bronze", (0.46, 0.38, 0.32, 0.55), metallic=0.1, roughness=0.05, alpha=0.55)
    make_mat("Wall_Panel_Cream", (0.89, 0.87, 0.83, 1.0), metallic=0.0, roughness=0.6)
    make_mat("Wallcover_Grey", (0.6, 0.61, 0.6, 1.0), metallic=0.0, roughness=0.9)
    make_mat("Mirror_Silver", (0.86, 0.88, 0.9, 1.0), metallic=1.0, roughness=0.05)
    make_mat("Sconce_Alabaster", (0.97, 0.95, 0.91, 1.0), metallic=0.0, roughness=0.5, emission=(1.0, 0.93, 0.82, 1.0), emission_strength=1.2)
    make_mat("Marble_Green_Pedestal", (0.6, 0.7, 0.64, 1.0), metallic=0.0, roughness=0.18)
    # New user reference materials (rev. 2026-11-03):
    make_img_mat("Wisteria_Bed_Wall",     os.path.join(OUT_DIR, "textures", "tex_wisteria_bedwall.png"), (0.85, 0.82, 0.78, 1.0), roughness=0.6)
    make_img_mat("Wisteria_Wardrobe",     os.path.join(OUT_DIR, "textures", "tex_wisteria_wardrobe.png"), (0.90, 0.88, 0.85, 1.0), roughness=0.5)
    make_img_mat("Tatami_Mat",             os.path.join(OUT_DIR, "textures", "tex_tatami_mat.png"), (0.82, 0.78, 0.65, 1.0), roughness=0.8, repeat=True)
    make_img_mat("B2_Pedestal_Marble",    os.path.join(OUT_DIR, "textures", "tex_b2_pedestal_marble.png"), (0.45, 0.45, 0.44, 1.0), roughness=0.15)
    make_img_mat("B2_Tea_Leaf_Art",       os.path.join(OUT_DIR, "textures", "tex_tea_art_leaf.png"), (0.72, 0.65, 0.50, 1.0), roughness=0.7)
    make_mat("Sofa_Sage_Velvet",         (0.48, 0.58, 0.52, 1.0), metallic=0.0,  roughness=0.68)
    make_mat("Glass_Blue_Sphere",        (0.15, 0.42, 0.75, 0.85), metallic=0.05, roughness=0.08, transmission=0.92, alpha=0.85)
    make_mat("Coffee_Pale_Marble",       (0.88, 0.90, 0.87, 1.0), metallic=0.0,  roughness=0.18)
    make_mat("SideTable_Green_Marble",   (0.22, 0.40, 0.32, 1.0), metallic=0.0,  roughness=0.16)
    make_mat("Travertine_Stone", (0.86, 0.82, 0.74, 1.0), metallic=0.0, roughness=0.85)
    make_mat("Rock_Egg_Glow", (1.0, 0.95, 0.86, 1.0), metallic=0.0, roughness=0.4, emission=(1.0, 0.9, 0.72, 1.0), emission_strength=2.0)
    # Materials for Travertine Beige Kaspar Foyer, Dining Dougong Canopy & Carved Wood Pillars (rev. 2026-11-04):
    make_img_mat("Travertine_Beige",     os.path.join(OUT_DIR, "textures", "tex_travertine_beige.jpg"), (0.85, 0.82, 0.77, 1.0), roughness=0.62, repeat=True)
    # Sculptural Flying Bird Art Chandelier (rev. 2026-11-06: warm pearl-ivory frosted wing contrast against pure white ceiling):
    _bird_mat = make_mat("Frosted_Acrylic_Bird", (0.84, 0.79, 0.69, 1.0), roughness=0.28, transmission=0.16, alpha=1.0)
    _bird_bsdf = _bird_mat.node_tree.nodes.get("Principled BSDF")
    if _bird_bsdf is not None:
        try:
            _bird_bsdf.inputs["Subsurface Weight"].default_value = 0.25
            _bird_bsdf.inputs["Emission Color"].default_value = (1.0, 0.88, 0.68, 1.0)
            _bird_bsdf.inputs["Emission Strength"].default_value = 0.04
        except Exception:
            pass
    make_mat("Bird_LED_Glow", (1.0, 0.92, 0.75, 1.0), emission=(1.0, 0.92, 0.75, 1.0), emission_strength=5.5)
    make_img_mat("Carved_Wood_Pillar",   os.path.join(OUT_DIR, "textures", "tex_carved_wood_pillar.png"), (0.48, 0.28, 0.16, 1.0), roughness=0.45)
    make_mat("Chinese_Eave_Wood",        (0.42, 0.22, 0.12, 1.0), metallic=0.0,  roughness=0.35)
    make_mat("Marble_Gold_Vein",         (0.92, 0.89, 0.84, 1.0), metallic=0.0,  roughness=0.18)
    make_img_mat("Stair_Ink_Marble",     os.path.join(OUT_DIR, "textures", "tex_stair_ink_marble.jpg"), (0.92, 0.92, 0.90, 1.0), roughness=0.18, repeat=True)
    make_img_mat("Child_Alcove_Art",     os.path.join(OUT_DIR, "textures", "tex_child_alcove_art.png"), (0.55, 0.74, 0.78, 1.0), roughness=0.45)
    make_img_mat("NorthBed_Head_Art",    os.path.join(OUT_DIR, "textures", "tex_northbed_head_art.png"), (0.68, 0.76, 0.72, 1.0), roughness=0.50)
    # 2F Secondary Bedroom Headboard Smooth Scalloped Wave Grille Lacquer (matching media_1795360791524_91ddc8e4.jpg)
    _wg_mat = make_mat("NorthBed_WaveGrille_Lacquer", (0.76, 0.72, 0.66, 1.0), metallic=0.0, roughness=0.25)
    _wg_nt = _wg_mat.node_tree
    _wg_bsdf = _wg_nt.nodes.get("Principled BSDF")
    if _wg_bsdf is not None:
        for _k, _v in (("Specular IOR Level", 0.45), ("Coat Weight", 0.22), ("Coat Roughness", 0.16)):
            if _k in _wg_bsdf.inputs:
                _wg_bsdf.inputs[_k].default_value = _v
        try:
            _wg_ao = _wg_nt.nodes.new("ShaderNodeAmbientOcclusion")
            _wg_ao.samples = 16
            _wg_ao.inputs["Distance"].default_value = 0.045
            _wg_gam = _wg_nt.nodes.new("ShaderNodeGamma")
            _wg_gam.inputs["Gamma"].default_value = 1.85
            _wg_nt.links.new(_wg_ao.outputs["AO"], _wg_gam.inputs["Color"])
            _wg_mix = _wg_nt.nodes.new("ShaderNodeMix")
            _wg_mix.data_type = 'RGBA'
            _wg_mix.blend_type = 'MULTIPLY'
            _wg_mix.clamp_factor = True
            _wg_mix.inputs[0].default_value = 0.44
            _wg_mix.inputs[6].default_value = (0.76, 0.72, 0.66, 1.0)
            _wg_nt.links.new(_wg_gam.outputs["Color"], _wg_mix.inputs[7])
            _wg_nt.links.new(_wg_mix.outputs[2], _wg_bsdf.inputs["Base Color"])
        except Exception:
            pass
    # 2F Master Bedroom Vanity Doors: Optical Wood Shadow (光学木影系列, matching media_1795360830608_cbd4993c.jpg)
    _ows_mat = make_img_mat("Optical_Wood_Shadow", os.path.join(OUT_DIR, "textures", "tex_optical_wood_shadow.png"), (0.73, 0.69, 0.64, 1.0), metallic=0.20, roughness=0.28, repeat=True)
    _ows_nt = _ows_mat.node_tree
    _ows_bsdf = _ows_nt.nodes.get("Principled BSDF")
    if _ows_bsdf is not None:
        for _k, _v in (("Specular IOR Level", 0.50), ("Coat Weight", 0.25), ("Coat Roughness", 0.16)):
            if _k in _ows_bsdf.inputs:
                _ows_bsdf.inputs[_k].default_value = _v
        try:
            _ows_bump_path = os.path.join(OUT_DIR, "textures", "tex_optical_wood_shadow_bump.png")
            if os.path.exists(_ows_bump_path):
                _btex = _ows_nt.nodes.new("ShaderNodeTexImage")
                _btex.image = bpy.data.images.load(_ows_bump_path, check_existing=True)
                _btex.image.colorspace_settings.name = 'Non-Color'
                _btex.extension = 'REPEAT'
                _rmap = _ows_nt.nodes.new("ShaderNodeMapRange")
                _rmap.clamp = True
                _rmap.inputs["From Min"].default_value = 0.0
                _rmap.inputs["From Max"].default_value = 1.0
                _rmap.inputs["To Min"].default_value = 0.16
                _rmap.inputs["To Max"].default_value = 0.46
                _ows_nt.links.new(_btex.outputs["Color"], _rmap.inputs["Value"])
                _ows_nt.links.new(_rmap.outputs["Result"], _ows_bsdf.inputs["Roughness"])
                _bmp = _ows_nt.nodes.new("ShaderNodeBump")
                _bmp.inputs["Strength"].default_value = 0.32
                _bmp.inputs["Distance"].default_value = 0.003
                _ows_nt.links.new(_btex.outputs["Color"], _bmp.inputs["Height"])
                _ows_nt.links.new(_bmp.outputs["Normal"], _ows_bsdf.inputs["Normal"])
        except Exception:
            pass
    make_mat("Optical_Wood_Shadow_Base", (0.66, 0.62, 0.57, 1.0), metallic=0.14, roughness=0.32)
    # Frosted Fluted Changhong Glass & Diffuser for 2F North Bedroom Opposite-Bed Cabinet
    _chg_mat = make_mat("Fluted_Changhong_Glass", (0.85, 0.82, 0.76, 1.0), metallic=0.04, roughness=0.26, transmission=0.58, alpha=0.74)
    _chg_bsdf = _chg_mat.node_tree.nodes.get("Principled BSDF")
    if _chg_bsdf is not None:
        for _k, _v in (("Coat Weight", 0.35), ("Coat Roughness", 0.08), ("IOR", 1.52)):
            if _k in _chg_bsdf.inputs:
                _chg_bsdf.inputs[_k].default_value = _v
    _chg_mat.blend_method = 'BLEND'
    _cfd_mat = make_mat("Changhong_Frost_Diffuser", (0.88, 0.85, 0.79, 1.0), metallic=0.0, roughness=0.50, transmission=0.45, alpha=0.58)
    _cfd_bsdf = _cfd_mat.node_tree.nodes.get("Principled BSDF")
    if _cfd_bsdf is not None and "Subsurface Weight" in _cfd_bsdf.inputs:
        _cfd_bsdf.inputs["Subsurface Weight"].default_value = 0.25
    _cfd_mat.blend_method = 'BLEND'
    # White Shadow Wood Veneer (白影木饰面, matching media_1795363611658_b58bdbf2.jpg)
    _wsw_mat = make_img_mat("White_Shadow_Wood", os.path.join(OUT_DIR, "textures", "tex_white_shadow_wood.png"), (0.74, 0.70, 0.62, 1.0), metallic=0.05, roughness=0.26, repeat=True)
    _wsw_nt = _wsw_mat.node_tree
    _wsw_bsdf = _wsw_nt.nodes.get("Principled BSDF")
    if _wsw_bsdf is not None:
        for _k, _v in (("Specular IOR Level", 0.50), ("Coat Weight", 0.28), ("Coat Roughness", 0.16)):
            if _k in _wsw_bsdf.inputs:
                _wsw_bsdf.inputs[_k].default_value = _v
        try:
            _wsw_bump_path = os.path.join(OUT_DIR, "textures", "tex_white_shadow_wood_bump.png")
            if os.path.exists(_wsw_bump_path):
                _wbtex = _wsw_nt.nodes.new("ShaderNodeTexImage")
                _wbtex.image = bpy.data.images.load(_wsw_bump_path, check_existing=True)
                _wbtex.image.colorspace_settings.name = 'Non-Color'
                _wbtex.extension = 'REPEAT'
                _wrmap = _wsw_nt.nodes.new("ShaderNodeMapRange")
                _wrmap.clamp = True
                _wrmap.inputs["From Min"].default_value = 0.0
                _wrmap.inputs["From Max"].default_value = 1.0
                _wrmap.inputs["To Min"].default_value = 0.18
                _wrmap.inputs["To Max"].default_value = 0.34
                _wsw_nt.links.new(_wbtex.outputs["Color"], _wrmap.inputs["Value"])
                _wsw_nt.links.new(_wrmap.outputs["Result"], _wsw_bsdf.inputs["Roughness"])
                _wbmp = _wsw_nt.nodes.new("ShaderNodeBump")
                _wbmp.inputs["Strength"].default_value = 0.14
                _wbmp.inputs["Distance"].default_value = 0.002
                _wsw_nt.links.new(_wbtex.outputs["Color"], _wbmp.inputs["Height"])
                _wsw_nt.links.new(_wbmp.outputs["Normal"], _wsw_bsdf.inputs["Normal"])
        except Exception:
            pass
    make_mat("White_Shadow_Wood_Base", (0.72, 0.68, 0.60, 1.0), metallic=0.04, roughness=0.28)
    # Tucson Semi-Transparent Champagne Mirror Glass (matching media_1795363749551_e6762315.jpg)
    _tmg_mat = make_mat("Tucson_Mirror_Glass", (0.78, 0.76, 0.72, 1.0), metallic=0.42, roughness=0.04, transmission=0.54, alpha=0.52)
    _tmg_bsdf = _tmg_mat.node_tree.nodes.get("Principled BSDF")
    if _tmg_bsdf is not None:
        for _k, _v in (("IOR", 1.54), ("Coat Weight", 0.85), ("Coat Roughness", 0.02)):
            if _k in _tmg_bsdf.inputs:
                _tmg_bsdf.inputs[_k].default_value = _v
    _tmg_mat.blend_method = 'BLEND'
    # Sculpted Foot-of-Bed Trim & Golden Silk Nanmu Alcove Materials (matching media_1795365146947_f38fb470.jpg + media_1795365208513_e4d7eed5.jpg)
    make_mat("Antique_Champagne_Brass", (0.58, 0.47, 0.30, 1.0), metallic=0.88, roughness=0.24)
    make_mat("Dark_Bronze_Recess", (0.16, 0.13, 0.10, 1.0), metallic=0.72, roughness=0.30)
    make_mat("Handle_Amber_Glow", (1.0, 0.88, 0.66, 1.0), metallic=0.0, roughness=0.22, emission=(1.0, 0.84, 0.56, 1.0), emission_strength=3.2)
    _nmu_mat = make_img_mat("Golden_Silk_Nanmu", os.path.join(OUT_DIR, "textures", "tex_golden_silk_nanmu.png"), (0.74, 0.57, 0.30, 1.0), metallic=0.22, roughness=0.24, repeat=True)
    _nmu_nt = _nmu_mat.node_tree
    _nmu_bsdf = _nmu_nt.nodes.get("Principled BSDF")
    if _nmu_bsdf is not None:
        for _k, _v in (("Specular IOR Level", 0.58), ("Coat Weight", 0.42), ("Coat Roughness", 0.12), ("Anisotropic", 0.45)):
            if _k in _nmu_bsdf.inputs:
                _nmu_bsdf.inputs[_k].default_value = _v
        try:
            _nmu_bump_path = os.path.join(OUT_DIR, "textures", "tex_golden_silk_nanmu_bump.png")
            if os.path.exists(_nmu_bump_path):
                _nbtex = _nmu_nt.nodes.new("ShaderNodeTexImage")
                _nbtex.image = bpy.data.images.load(_nmu_bump_path, check_existing=True)
                _nbtex.image.colorspace_settings.name = 'Non-Color'
                _nbtex.extension = 'REPEAT'
                _nrmap = _nmu_nt.nodes.new("ShaderNodeMapRange")
                _nrmap.clamp = True
                _nrmap.inputs["From Min"].default_value = 0.0
                _nrmap.inputs["From Max"].default_value = 1.0
                _nrmap.inputs["To Min"].default_value = 0.18
                _nrmap.inputs["To Max"].default_value = 0.38
                _nmu_nt.links.new(_nbtex.outputs["Color"], _nrmap.inputs["Value"])
                _nmu_nt.links.new(_nrmap.outputs["Result"], _nmu_bsdf.inputs["Roughness"])
                _nbmp = _nmu_nt.nodes.new("ShaderNodeBump")
                _nbmp.inputs["Strength"].default_value = 0.24
                _nbmp.inputs["Distance"].default_value = 0.0025
                _nmu_nt.links.new(_nbtex.outputs["Color"], _nbmp.inputs["Height"])
                _nmu_nt.links.new(_nbmp.outputs["Normal"], _nmu_bsdf.inputs["Normal"])
        except Exception:
            pass
    # Ultra-Clear Fine Silk-Brushed Frosted Privacy Glass (超白微细拉丝磨砂隐私玻璃, matching media_1795365804469_fd0e584f.jpg SL-3553)
    _tfg_mat = make_img_mat(
        "Toilet_Frosted_Silk_Glass",
        os.path.join(OUT_DIR, "textures", "tex_toilet_frosted_glass.png"),
        (0.91, 0.88, 0.84, 1.0),
        metallic=0.0,
        roughness=0.40,
        repeat=True
    )
    _tfg_nt = _tfg_mat.node_tree
    _tfg_bsdf = _tfg_nt.nodes.get("Principled BSDF")
    if _tfg_bsdf is not None:
        for _k, _v in (
            ("Transmission Weight", 0.76),
            ("Transmission", 0.76),
            ("IOR", 1.50),
            ("Alpha", 0.84),
            ("Subsurface Weight", 0.16),
            ("Coat Weight", 0.20),
            ("Coat Roughness", 0.22),
        ):
            if _k in _tfg_bsdf.inputs:
                _tfg_bsdf.inputs[_k].default_value = _v
        try:
            _tfg_bump_path = os.path.join(OUT_DIR, "textures", "tex_toilet_frosted_glass_bump.png")
            if os.path.exists(_tfg_bump_path):
                _gbtex = _tfg_nt.nodes.new("ShaderNodeTexImage")
                _gbtex.image = bpy.data.images.load(_tfg_bump_path, check_existing=True)
                _gbtex.image.colorspace_settings.name = 'Non-Color'
                _gbtex.extension = 'REPEAT'
                _grmap = _tfg_nt.nodes.new("ShaderNodeMapRange")
                _grmap.clamp = True
                _grmap.inputs["From Min"].default_value = 0.0
                _grmap.inputs["From Max"].default_value = 1.0
                _grmap.inputs["To Min"].default_value = 0.34
                _grmap.inputs["To Max"].default_value = 0.48
                _tfg_nt.links.new(_gbtex.outputs["Color"], _grmap.inputs["Value"])
                _tfg_nt.links.new(_grmap.outputs["Result"], _tfg_bsdf.inputs["Roughness"])
                _gbmp = _tfg_nt.nodes.new("ShaderNodeBump")
                _gbmp.inputs["Strength"].default_value = 0.22
                _gbmp.inputs["Distance"].default_value = 0.0018
                _tfg_nt.links.new(_gbtex.outputs["Color"], _gbmp.inputs["Height"])
                _tfg_nt.links.new(_gbmp.outputs["Normal"], _tfg_bsdf.inputs["Normal"])
        except Exception:
            pass
    _tfg_mat.blend_method = 'BLEND'
    # 1F Living Room Sculptural Linear Fireplace Wall Materials (rev. 2026-11-22)
    _fp_wall = make_mat("Fireplace_Wall_Plaster", (0.87, 0.84, 0.79, 1.0), metallic=0.0, roughness=0.58)
    _fpw_bsdf = _fp_wall.node_tree.nodes.get("Principled BSDF")
    if _fpw_bsdf is not None and "Specular IOR Level" in _fpw_bsdf.inputs:
        _fpw_bsdf.inputs["Specular IOR Level"].default_value = 0.18
    _fp_brz = make_mat("Fireplace_Bronze_Dark", (0.13, 0.095, 0.075, 1.0), metallic=0.76, roughness=0.34)
    _fpb_bsdf = _fp_brz.node_tree.nodes.get("Principled BSDF")
    if _fpb_bsdf is not None and "Coat Weight" in _fpb_bsdf.inputs:
        _fpb_bsdf.inputs["Coat Weight"].default_value = 0.15
    make_mat("Fireplace_Ember_Bed", (0.08, 0.05, 0.04, 1.0), metallic=0.05, roughness=0.65, emission=(1.0, 0.38, 0.08, 1.0), emission_strength=0.9)
    _fp_flm = make_img_mat("Fireplace_Flame_Card", os.path.join(OUT_DIR, "textures", "tex_fireplace_flames.png"), (1.0, 0.65, 0.18, 1.0), metallic=0.0, roughness=0.50, emission_strength=8.5, repeat=False)
    _flm_nt = _fp_flm.node_tree
    _flm_bsdf = _flm_nt.nodes.get("Principled BSDF")
    _flm_tex = [n for n in _flm_nt.nodes if n.type == "TEX_IMAGE"]
    if _flm_bsdf is not None and _flm_tex:
        try:
            _flm_nt.links.new(_flm_tex[0].outputs["Alpha"], _flm_bsdf.inputs["Alpha"])
        except Exception:
            pass
    _fp_flm.blend_method = 'BLEND'
    if hasattr(_fp_flm, "shadow_method"):
        try:
            _fp_flm.shadow_method = 'NONE'
        except Exception:
            pass
    # 2F WIC South Optical Wood Shadow (珍珠白光学木影系列, matching media_1795369092980_4876d114.jpg)
    _ows_w = make_img_mat(
        "Optical_Wood_Shadow_WIC",
        os.path.join(OUT_DIR, "textures", "tex_optical_wood_shadow_wic.png"),
        (0.85, 0.80, 0.75, 1.0),
        metallic=0.10,
        roughness=0.26,
        repeat=True
    )
    _oww_nt = _ows_w.node_tree
    _oww_bsdf = _oww_nt.nodes.get("Principled BSDF")
    if _oww_bsdf is not None:
        for _k, _v in (("Specular IOR Level", 0.52), ("Coat Weight", 0.38), ("Coat Roughness", 0.10)):
            if _k in _oww_bsdf.inputs:
                _oww_bsdf.inputs[_k].default_value = _v
        try:
            _oww_bump = os.path.join(OUT_DIR, "textures", "tex_optical_wood_shadow_wic_bump.png")
            if os.path.exists(_oww_bump):
                _btx = _oww_nt.nodes.new("ShaderNodeTexImage")
                _btx.image = bpy.data.images.load(_oww_bump, check_existing=True)
                _btx.image.colorspace_settings.name = 'Non-Color'
                _btx.extension = 'REPEAT'
                _rmp = _oww_nt.nodes.new("ShaderNodeMapRange")
                _rmp.clamp = True
                _rmp.inputs["From Min"].default_value = 0.0
                _rmp.inputs["From Max"].default_value = 1.0
                _rmp.inputs["To Min"].default_value = 0.16
                _rmp.inputs["To Max"].default_value = 0.38
                _oww_nt.links.new(_btx.outputs["Color"], _rmp.inputs["Value"])
                _oww_nt.links.new(_rmp.outputs["Result"], _oww_bsdf.inputs["Roughness"])
                _bmp = _oww_nt.nodes.new("ShaderNodeBump")
                _bmp.inputs["Strength"].default_value = 0.16
                _bmp.inputs["Distance"].default_value = 0.002
                _oww_nt.links.new(_btx.outputs["Color"], _bmp.inputs["Height"])
                _oww_nt.links.new(_bmp.outputs["Normal"], _oww_bsdf.inputs["Normal"])
        except Exception:
            pass
    # 1F Living Room Curved Antique Gold-Leaf Lingnan Ink-Wash Screen (matching media_1795370003891_bafd46c4.jpg & media_1795371185700_1b4af2ee.jpg)
    _fp_scr = make_img_mat(
        "Fireplace_Gold_Lingnan_Screen",
        os.path.join(OUT_DIR, "textures", "tex_fireplace_gold_lingnan_screen.png"),
        (0.76, 0.58, 0.24, 1.0),
        metallic=0.56,
        roughness=0.34,
        repeat=False
    )
    _fps_nt = _fp_scr.node_tree
    _fps_bsdf = _fps_nt.nodes.get("Principled BSDF")
    if _fps_bsdf is not None:
        for _k, _v in (("Specular IOR Level", 0.55), ("Coat Weight", 0.25), ("Coat Roughness", 0.14)):
            if _k in _fps_bsdf.inputs:
                _fps_bsdf.inputs[_k].default_value = _v
        try:
            _fps_bump = os.path.join(OUT_DIR, "textures", "tex_fireplace_gold_leaf_bump.png")
            if os.path.exists(_fps_bump):
                _fbt = _fps_nt.nodes.new("ShaderNodeTexImage")
                _fbt.image = bpy.data.images.load(_fps_bump, check_existing=True)
                _fbt.image.colorspace_settings.name = 'Non-Color'
                _fbt.extension = 'EXTEND'
                _fbmp = _fps_nt.nodes.new("ShaderNodeBump")
                _fbmp.inputs["Strength"].default_value = 0.08
                _fbmp.inputs["Distance"].default_value = 0.0015
                _fps_nt.links.new(_fbt.outputs["Color"], _fbmp.inputs["Height"])
                _fps_nt.links.new(_fbmp.outputs["Normal"], _fps_bsdf.inputs["Normal"])
        except Exception:
            pass
    # 1F Living Room Moon-Gate Gold Fireplace Liner & Hand-Painted Gold-Foil Lingnan Wallpaper (rev. 2026-11-22)
    _fp_gold_bp = make_mat("Fireplace_Gold_Backplate", (0.84, 0.65, 0.28, 1.0), metallic=0.90, roughness=0.22)
    _fgp_bsdf = _fp_gold_bp.node_tree.nodes.get("Principled BSDF")
    if _fgp_bsdf is not None:
        for _k, _v in (("Coat Weight", 0.20), ("Coat Roughness", 0.14), ("Specular IOR Level", 0.65)):
            if _k in _fgp_bsdf.inputs:
                _fgp_bsdf.inputs[_k].default_value = _v
    _fp_wp = make_img_mat(
        "Fireplace_Lingnan_Wallpaper",
        os.path.join(OUT_DIR, "textures", "tex_fireplace_lingnan_wallpaper.png"),
        (0.70, 0.64, 0.50, 1.0),
        metallic=0.28,
        roughness=0.32,
        repeat=False
    )
    _fpw2_nt = _fp_wp.node_tree
    _fpw2_bsdf = _fpw2_nt.nodes.get("Principled BSDF")
    if _fpw2_bsdf is not None:
        for _k, _v in (("Specular IOR Level", 0.65), ("Coat Weight", 0.16), ("Coat Roughness", 0.20)):
            if _k in _fpw2_bsdf.inputs:
                _fpw2_bsdf.inputs[_k].default_value = _v
        try:
            _fpw_norm = os.path.join(OUT_DIR, "textures", "tex_fireplace_lingnan_wallpaper_normal.png")
            if os.path.exists(_fpw_norm):
                _wnt = _fpw2_nt.nodes.new("ShaderNodeTexImage")
                _wnt.image = bpy.data.images.load(_fpw_norm, check_existing=True)
                _wnt.image.colorspace_settings.name = 'Non-Color'
                _wnt.extension = 'EXTEND'
                _wnmap = _fpw2_nt.nodes.new("ShaderNodeNormalMap")
                _wnmap.space = 'TANGENT'
                _wnmap.inputs["Strength"].default_value = 0.18
                _fpw2_nt.links.new(_wnt.outputs["Color"], _wnmap.inputs["Color"])
                _fpw2_nt.links.new(_wnmap.outputs["Normal"], _fpw2_bsdf.inputs["Normal"])
        except Exception:
            pass
    # 1F Living Room Circular White Boucle Sofa & Indoor Bonsai Pine Island Materials
    _sbou = make_mat("Sofa_White_Boucle", (0.95, 0.94, 0.91, 1.0), metallic=0.0, roughness=0.84)
    _sbou_bsdf = _sbou.node_tree.nodes.get("Principled BSDF")
    if _sbou_bsdf is not None:
        for _k, _v in (("Sheen Weight", 0.55), ("Sheen", 0.55), ("Sheen Roughness", 0.60)):
            if _k in _sbou_bsdf.inputs:
                _sbou_bsdf.inputs[_k].default_value = _v
    make_mat("Planter_Moss_Green", (0.18, 0.28, 0.11, 1.0), metallic=0.0, roughness=0.92)
    make_mat("Planter_Rock_Dark",  (0.14, 0.15, 0.16, 1.0), metallic=0.02, roughness=0.62)
    make_mat("Pine_Bark_Dark",     (0.24, 0.17, 0.12, 1.0), metallic=0.0, roughness=0.78)
    make_mat("Pine_Needle_Green",  (0.13, 0.24, 0.14, 1.0), metallic=0.0, roughness=0.68)

    # 1F Living Room Sculptural Golden-Leaf & Translucent Porcelain Magnolia Cascade Chandelier Materials
    _cg_mat = make_mat("Chandelier_Antique_Gold", (0.86, 0.71, 0.36, 1.0), metallic=0.80, roughness=0.24)
    _cg_mat.use_backface_culling = False
    _cg_bsdf = _cg_mat.node_tree.nodes.get("Principled BSDF")
    if _cg_bsdf is not None:
        for _k, _v in (("Specular IOR Level", 0.68), ("Coat Weight", 0.18), ("Coat Roughness", 0.16)):
            if _k in _cg_bsdf.inputs:
                _cg_bsdf.inputs[_k].default_value = _v

    _cm_mat = make_mat(
        "Chandelier_Magnolia_Porcelain",
        (0.99, 0.96, 0.90, 1.0),
        metallic=0.0,
        roughness=0.24,
        emission=(1.0, 0.92, 0.78, 1.0),
        emission_strength=0.75,
    )
    _cm_mat.use_backface_culling = False
    _cm_mat.cycles.emission_sampling = 'NONE'
    _cm_bsdf = _cm_mat.node_tree.nodes.get("Principled BSDF")
    if _cm_bsdf is not None:
        for _k, _v in (("Coat Weight", 0.25), ("Coat Roughness", 0.12)):
            if _k in _cm_bsdf.inputs:
                _cm_bsdf.inputs[_k].default_value = _v

    _cb_mat = make_mat(
        "Chandelier_Bulb_Glow",
        (1.0, 0.95, 0.84, 1.0),
        metallic=0.0,
        roughness=0.15,
        emission=(1.0, 0.92, 0.75, 1.0),
        emission_strength=4.5,
    )
    _cb_mat.cycles.emission_sampling = 'NONE'


# ---------------------------------------------------------------------------
# Geometry & BMesh Helpers
# ---------------------------------------------------------------------------
def link_obj(obj, col):
    col.objects.link(obj)
    return obj

def add_prism(name, pts_2d_mm, z0, z1, mat, col):
    if len(pts_2d_mm) < 3 or abs(z1 - z0) < 1e-4:
        return None
    # Deduplicate consecutive close vertices
    clean_pts = []
    for p in pts_2d_mm:
        if not clean_pts or math.hypot(p[0] - clean_pts[-1][0], p[1] - clean_pts[-1][1]) > 1.0:
            clean_pts.append(p)
    if len(clean_pts) >= 2 and math.hypot(clean_pts[0][0] - clean_pts[-1][0], clean_pts[0][1] - clean_pts[-1][1]) <= 1.0:
        clean_pts.pop()
    if len(clean_pts) < 3:
        return None

    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    verts_bot = [bm.verts.new((p[0]*MM, p[1]*MM, z0)) for p in clean_pts]
    verts_top = [bm.verts.new((p[0]*MM, p[1]*MM, z1)) for p in clean_pts]
    n = len(clean_pts)
    area = 0.0
    for i in range(n):
        x1, y1 = clean_pts[i]
        x2, y2 = clean_pts[(i+1)%n]
        area += (x1*y2 - x2*y1)
    if area < 0:
        verts_bot.reverse()
        verts_top.reverse()
        clean_pts.reverse()
    f_bot = None
    f_top = None
    side_faces = []
    try:
        f_bot = bm.faces.new(verts_bot[::-1])
        f_top = bm.faces.new(verts_top)
        for i in range(n):
            side_faces.append(bm.faces.new([verts_bot[i], verts_bot[(i+1)%n], verts_top[(i+1)%n], verts_top[i]]))
    except ValueError:
        pass

    # Generate aspect-preserving world-space UVs (1.0m per tile, no stretching/squashing)
    uv_layer = bm.loops.layers.uv.verify()
    tile_m = 1.0

    if f_top:
        for loop in f_top.loops:
            vx, vy = loop.vert.co.x, loop.vert.co.y
            loop[uv_layer].uv = (vx / tile_m, vy / tile_m)
    if f_bot:
        for loop in f_bot.loops:
            vx, vy = loop.vert.co.x, loop.vert.co.y
            loop[uv_layer].uv = (vx / tile_m, vy / tile_m)

    cum_len = 0.0
    for i, sf in enumerate(side_faces):
        p1 = clean_pts[i]
        p2 = clean_pts[(i + 1) % n]
        seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) * MM
        u0 = cum_len / tile_m
        u1 = (cum_len + seg_len) / tile_m
        cum_len += seg_len
        for loop in sf.loops:
            z_val = loop.vert.co.z
            v = (z_val - z0) / tile_m
            u = u0 if math.hypot(loop.vert.co.x - p1[0]*MM, loop.vert.co.y - p1[1]*MM) < math.hypot(loop.vert.co.x - p2[0]*MM, loop.vert.co.y - p2[1]*MM) else u1
            loop[uv_layer].uv = (u, v)

    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    link_obj(obj, col)
    return obj

def add_stair_step_textured(name, pl_a, pr_a, pr_b, pl_b, z_bot, z_top, mat, col, step_idx=0, total_steps=13):
    """Creates a high-precision stair step with smooth continuous flowing ink-wash landscape marble UVs on all 6 faces."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()

    pts = [pl_a, pr_a, pr_b, pl_b]
    vb = [bm.verts.new((p[0]*MM, p[1]*MM, z_bot)) for p in pts]
    vt = [bm.verts.new((p[0]*MM, p[1]*MM, z_top)) for p in pts]

    f_bot = bm.faces.new(vb[::-1])
    f_top = bm.faces.new(vt)
    f_front = bm.faces.new([vb[0], vb[1], vt[1], vt[0]])
    f_right = bm.faces.new([vb[1], vb[2], vt[2], vt[1]])
    f_back  = bm.faces.new([vb[2], vb[3], vt[3], vt[2]])
    f_left  = bm.faces.new([vb[3], vb[0], vt[0], vt[3]])

    uv_layer = bm.loops.layers.uv.verify()
    # Continuous flowing UV slice progressing monotonically up the staircase
    n_tot = max(1, int(total_steps))
    v0 = (step_idx / float(n_tot)) * 0.78
    v1 = ((step_idx + 1) / float(n_tot)) * 0.78
    u_shift = 0.06 * math.sin(step_idx * 0.45)
    u0 = 0.08 + u_shift
    u1 = 0.92 + u_shift

    for loop, uv in zip(f_top.loops, [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]):
        loop[uv_layer].uv = uv
    for loop, uv in zip(f_bot.loops, [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]):
        loop[uv_layer].uv = uv
    for loop, uv in zip(f_front.loops, [(u0, v0), (u1, v0), (u1, v0 + 0.045), (u0, v0 + 0.045)]):
        loop[uv_layer].uv = uv
    for loop, uv in zip(f_back.loops, [(u1, v1), (u0, v1), (u0, v1 + 0.045), (u1, v1 + 0.045)]):
        loop[uv_layer].uv = uv
    for loop, uv in zip(f_right.loops, [(u1, v0), (u1, v1), (u1 - 0.035, v1), (u1 - 0.035, v0)]):
        loop[uv_layer].uv = uv
    for loop, uv in zip(f_left.loops, [(u0, v1), (u0, v0), (u0 + 0.035, v0), (u0 + 0.035, v1)]):
        loop[uv_layer].uv = uv

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    link_obj(obj, col)
    return obj

def add_box_mm(name, x1, x2, y1, y2, z0, z1, mat, col, r_corner=0.0):
    xa, xb = min(x1, x2), max(x1, x2)
    ya, yb = min(y1, y2), max(y1, y2)
    if r_corner > 0.0 and (xb - xa) > 2.2*r_corner and (yb - ya) > 2.2*r_corner:
        pts = []
        corners = [
            (xb - r_corner, yb - r_corner, 0.0, 90.0),
            (xa + r_corner, yb - r_corner, 90.0, 180.0),
            (xa + r_corner, ya + r_corner, 180.0, 270.0),
            (xb - r_corner, ya + r_corner, 270.0, 360.0),
        ]
        for cx, cy, a1, a2 in corners:
            for k in range(5):
                a = math.radians(a1 + (a2 - a1)*k/4.0)
                pts.append((cx + r_corner*math.cos(a), cy + r_corner*math.sin(a)))
        return add_prism(name, pts, z0, z1, mat, col)
    pts = [(xa, ya), (xb, ya), (xb, yb), (xa, yb)]
    return add_prism(name, pts, z0, z1, mat, col)

def add_uv_front_box_mm(name, x1, x2, y1, y2, z0, z1, u0, u1, v0, v1, mat, col):
    xa, xb = min(x1, x2) * MM, max(x1, x2) * MM
    ya, yb = min(y1, y2) * MM, max(y1, y2) * MM
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    v000 = bm.verts.new((xa, ya, z0))
    v100 = bm.verts.new((xb, ya, z0))
    v110 = bm.verts.new((xb, yb, z0))
    v010 = bm.verts.new((xa, yb, z0))
    v001 = bm.verts.new((xa, ya, z1))
    v101 = bm.verts.new((xb, ya, z1))
    v111 = bm.verts.new((xb, yb, z1))
    v011 = bm.verts.new((xa, yb, z1))
    uv_layer = bm.loops.layers.uv.new("UVMap")
    faces_uvs = [
        # Front (-Y) face: visible from living room
        ([v000, v100, v101, v001], [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]),
        # Back (+Y) face
        ([v110, v010, v011, v111], [(u1, v0), (u0, v0), (u0, v1), (u1, v1)]),
        # Top (+Z) face
        ([v001, v101, v111, v011], [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]),
        # Bottom (-Z) face
        ([v010, v110, v100, v000], [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]),
        # Left (-X) face
        ([v010, v000, v001, v011], [(u0, v0), (u0, v0), (u0, v1), (u0, v1)]),
        # Right (+X) face
        ([v100, v110, v111, v101], [(u1, v0), (u1, v0), (u1, v1), (u1, v1)]),
    ]
    for fverts, fuvs in faces_uvs:
        f = bm.faces.new(fverts)
        for loop, uv in zip(f.loops, fuvs):
            loop[uv_layer].uv = uv
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    link_obj(obj, col)
    return obj

def add_uv_side_box_mm(name, x1, x2, y1, y2, z0, z1, u0, u1, v0, v1, mat, col):
    xa, xb = min(x1, x2) * MM, max(x1, x2) * MM
    ya, yb = min(y1, y2) * MM, max(y1, y2) * MM
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    v000 = bm.verts.new((xa, ya, z0))
    v100 = bm.verts.new((xb, ya, z0))
    v110 = bm.verts.new((xb, yb, z0))
    v010 = bm.verts.new((xa, yb, z0))
    v001 = bm.verts.new((xa, ya, z1))
    v101 = bm.verts.new((xb, ya, z1))
    v111 = bm.verts.new((xb, yb, z1))
    v011 = bm.verts.new((xa, yb, z1))
    uv_layer = bm.loops.layers.uv.new("UVMap")
    faces_uvs = [
        # Right (+X) face (looking from +X toward -X: ya is left, yb is right)
        ([v100, v110, v111, v101], [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]),
        # Left (-X) face (looking from -X toward +X: ya is right, yb is left)
        ([v010, v000, v001, v011], [(u1, v0), (u0, v0), (u0, v1), (u1, v1)]),
        # Top (+Z) face
        ([v001, v101, v111, v011], [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]),
        # Bottom (-Z) face
        ([v010, v110, v100, v000], [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]),
        # Front (-Y) face
        ([v000, v100, v101, v001], [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]),
        # Back (+Y) face
        ([v110, v010, v011, v111], [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]),
    ]
    for fverts, fuvs in faces_uvs:
        f = bm.faces.new(fverts)
        for loop, uv in zip(f.loops, fuvs):
            loop[uv_layer].uv = uv
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    link_obj(obj, col)
    return obj

def add_cyl_mm(name, cx_mm, cy_mm, r_mm, z0, z1, mat, col, segs=36):
    pts = []
    for k in range(segs):
        a = 2.0 * math.pi * k / segs
        pts.append((cx_mm + r_mm*math.cos(a), cy_mm + r_mm*math.sin(a)))
    return add_prism(name, pts, z0, z1, mat, col)

def arc_band_poly(cx1, cy1, r1, cx2, cy2, r2, a1_deg, a2_deg, n=28):
    pts = []
    for k in range(n+1):
        a = math.radians(a1_deg + (a2_deg - a1_deg)*k/n)
        pts.append((cx1 + r1*math.cos(a), cy1 + r1*math.sin(a)))
    for k in range(n, -1, -1):
        a = math.radians(a1_deg + (a2_deg - a1_deg)*k/n)
        pts.append((cx2 + r2*math.cos(a), cy2 + r2*math.sin(a)))
    return pts


# ---------------------------------------------------------------------------
# Manifold 2D Grid Wall Extraction & Builder (Zero Z-Fighting!)
# ---------------------------------------------------------------------------
def subtract_intervals(a, b, blocks):
    res = [(a, b)]
    for ba, bb in blocks:
        new_res = []
        for x1, x2 in res:
            if bb <= x1 + 5.0 or ba >= x2 - 5.0:
                new_res.append((x1, x2))
            else:
                if ba - x1 > 30.0:
                    new_res.append((x1, ba))
                if x2 - bb > 30.0:
                    new_res.append((bb, x2))
        res = new_res
    return res


def build_manifold_walls(msp, name, xr, yr, ox, oy, z0, h_wall, cutout_boxes, col, extra_rects=None, override_rects=None):
    """
    Extract all axis-aligned wall rectangles on `name`, subtract `cutout_boxes` (windows & doors),
    rasterize onto an exact rectilinear coordinate grid `(xs, ys)`, and emit a single
    100% manifold, zero-overlap 3D mesh with `Wall_Struct` and `Wall_New` materials!
    Also builds curved/angled wall segments cleanly without overlapping the axis-aligned grid.
    """
    rects = []  # (xa, xb, ya, yb, mat_id) where mat_id: 1=struct, 2=new
    h_segs = []
    v_segs = []

    if override_rects is not None:
        rects.extend(override_rects)
    else:
        for e in msp:
            lay = e.dxf.layer
            if lay not in ("1建筑墙体", "2新建墙体", "2新建墙体[填充]", "2新建墙体完成面"):
                continue
            mat_id = 1 if lay == "1建筑墙体" else 2
            t = e.dxftype()
            if t == "HATCH":
                if name == "B2_Base" and lay == "2新建墙体[填充]":
                    continue
                for path in e.paths:
                    pts = []
                    if hasattr(path, "vertices") and len(path.vertices) > 0:
                        pts = [(v[0]-ox, v[1]-oy) for v in path.vertices]
                    elif hasattr(path, "edges"):
                        for edge in path.edges:
                            if type(edge).__name__ == "LineEdge":
                                pts.append((edge.start[0]-ox, edge.start[1]-oy))
                    if len(pts) == 4:
                        wx, wy = pts[0][0]+ox, pts[0][1]+oy
                        if xr[0] <= wx <= xr[1] and yr[0] <= wy <= yr[1]:
                            xs_p = [p[0] for p in pts]
                            ys_p = [p[1] for p in pts]
                            rects.append((min(xs_p), max(xs_p), min(ys_p), max(ys_p), mat_id))
            elif t == "LINE" and lay != "2新建墙体[填充]":
                sx, sy = e.dxf.start.x, e.dxf.start.y
                ex, ey = e.dxf.end.x, e.dxf.end.y
                if xr[0] <= sx <= xr[1] and yr[0] <= sy <= yr[1]:
                    rx1, ry1 = sx-ox, sy-oy
                    rx2, ry2 = ex-ox, ey-oy
                    if abs(ry1 - ry2) < 1.5 and abs(rx1 - rx2) > 5.0:
                        h_segs.append((0.5*(ry1+ry2), min(rx1, rx2), max(rx1, rx2), mat_id))
                    elif abs(rx1 - rx2) < 1.5 and abs(ry1 - ry2) > 5.0:
                        v_segs.append((0.5*(rx1+rx2), min(ry1, ry2), max(ry1, ry2), mat_id))
            elif t == "LWPOLYLINE" and lay != "2新建墙体[填充]":
                pts = list(e.get_points())
                if pts and xr[0] <= pts[0][0] <= xr[1] and yr[0] <= pts[0][1] <= yr[1]:
                    n = len(pts)
                    for i in range(n - (0 if e.closed else 1)):
                        rx1, ry1 = pts[i][0]-ox, pts[i][1]-oy
                        rx2, ry2 = pts[(i+1)%n][0]-ox, pts[(i+1)%n][1]-oy
                        if abs(pts[i][4]) < 1e-3:
                            if abs(ry1 - ry2) < 1.5 and abs(rx1 - rx2) > 5.0:
                                h_segs.append((0.5*(ry1+ry2), min(rx1, rx2), max(rx1, rx2), mat_id))
                            elif abs(rx1 - rx2) < 1.5 and abs(ry1 - ry2) > 5.0:
                                v_segs.append((0.5*(rx1+rx2), min(ry1, ry2), max(ry1, ry2), mat_id))

        # Pair H segments
        for i in range(len(h_segs)):
            y1, x1a, x1b, m1 = h_segs[i]
            for j in range(i+1, len(h_segs)):
                y2, x2a, x2b, m2 = h_segs[j]
                dy = abs(y2 - y1)
                if 55.0 <= dy <= 360.0:
                    xa, xb = max(x1a, x2a), min(x1b, x2b)
                    if xb - xa > 40.0:
                        ymid_lo, ymid_hi = min(y1, y2) + 45.0, max(y1, y2) - 45.0
                        blocks = [(xka, xkb) for (yk, xka, xkb, _) in h_segs if ymid_lo < yk < ymid_hi]
                        mid = 1 if (m1 == 1 and m2 == 1) else 2
                        for sa, sb in subtract_intervals(xa, xb, blocks):
                            rects.append((sa, sb, min(y1, y2), max(y1, y2), mid))

        # Pair V segments
        for i in range(len(v_segs)):
            x1, y1a, y1b, m1 = v_segs[i]
            for j in range(i+1, len(v_segs)):
                x2, y2a, y2b, m2 = v_segs[j]
                dx = abs(x2 - x1)
                if 55.0 <= dx <= 360.0:
                    ya, yb = max(y1a, y2a), min(y1b, y2b)
                    if yb - ya > 40.0:
                        xmid_lo, xmid_hi = min(x1, x2) + 45.0, max(x1, x2) - 45.0
                        blocks = [(yka, ykb) for (xk, yka, ykb, _) in v_segs if xmid_lo < xk < xmid_hi]
                        mid = 1 if (m1 == 1 and m2 == 1) else 2
                        for sa, sb in subtract_intervals(ya, yb, blocks):
                            rects.append((min(x1, x2), max(x1, x2), sa, sb, mid))

    if extra_rects:
        rects.extend(extra_rects)

    # Build exact rectilinear grid coordinates (snapped to 2mm)
    raw_xs = set()
    raw_ys = set()
    for xa, xb, ya, yb, _ in rects:
        raw_xs.add(round(xa / 2.0) * 2.0)
        raw_xs.add(round(xb / 2.0) * 2.0)
        raw_ys.add(round(ya / 2.0) * 2.0)
        raw_ys.add(round(yb / 2.0) * 2.0)
    for cxa, cxb, cya, cyb in cutout_boxes:
        raw_xs.add(round(cxa / 2.0) * 2.0)
        raw_xs.add(round(cxb / 2.0) * 2.0)
        raw_ys.add(round(cya / 2.0) * 2.0)
        raw_ys.add(round(cyb / 2.0) * 2.0)

    xs = sorted(raw_xs)
    ys = sorted(raw_ys)
    nx = len(xs) - 1
    ny = len(ys) - 1
    grid = np.zeros((nx, ny), dtype=np.int32)

    for i in range(nx):
        xm = 0.5 * (xs[i] + xs[i+1])
        if xs[i+1] - xs[i] < 1.0:
            continue
        for j in range(ny):
            ym = 0.5 * (ys[j] + ys[j+1])
            if ys[j+1] - ys[j] < 1.0:
                continue
            # Check if inside any cutout box (window or door opening)
            in_cutout = False
            for cxa, cxb, cya, cyb in cutout_boxes:
                if (cxa - 5.0) <= xm <= (cxb + 5.0) and (cya - 5.0) <= ym <= (cyb + 5.0):
                    in_cutout = True
                    break
            if in_cutout:
                continue
            # Check wall rects (struct=1 takes priority over new=2)
            cell_val = 0
            for xa, xb, ya, yb, mid in rects:
                if xa <= xm <= xb and ya <= ym <= yb:
                    if mid == 1:
                        cell_val = 1
                        break
                    elif cell_val == 0:
                        cell_val = 2
            grid[i, j] = cell_val

    # Emit single manifold BMesh from grid
    mesh = bpy.data.meshes.new(f"{name}_Walls_Manifold")
    bm = bmesh.new()
    z1 = z0 + h_wall

    # Vertex cache: (ix, iy, is_top) -> BMVert
    vcache = {}
    def get_v(ix, iy, is_top):
        key = (ix, iy, is_top)
        if key not in vcache:
            vcache[key] = bm.verts.new((xs[ix]*MM, ys[iy]*MM, z1 if is_top else z0))
        return vcache[key]

    for i in range(nx):
        for j in range(ny):
            val = int(grid[i, j])
            if val == 0:
                continue
            mat_idx = 0 if val == 1 else 1
            # Bottom face (normal -Z)
            f_bot = bm.faces.new([get_v(i, j, False), get_v(i, j+1, False), get_v(i+1, j+1, False), get_v(i+1, j, False)])
            f_bot.material_index = mat_idx
            # Top face (normal +Z)
            f_top = bm.faces.new([get_v(i, j, True), get_v(i+1, j, True), get_v(i+1, j+1, True), get_v(i, j+1, True)])
            f_top.material_index = mat_idx
            # West face (-X)
            if i == 0 or grid[i-1, j] == 0:
                f_w = bm.faces.new([get_v(i, j, False), get_v(i, j, True), get_v(i, j+1, True), get_v(i, j+1, False)])
                f_w.material_index = mat_idx
            # East face (+X)
            if i == nx - 1 or grid[i+1, j] == 0:
                f_e = bm.faces.new([get_v(i+1, j, False), get_v(i+1, j+1, False), get_v(i+1, j+1, True), get_v(i+1, j, True)])
                f_e.material_index = mat_idx
            # South face (-Y)
            if j == 0 or grid[i, j-1] == 0:
                f_s = bm.faces.new([get_v(i, j, False), get_v(i+1, j, False), get_v(i+1, j, True), get_v(i, j, True)])
                f_s.material_index = mat_idx
            # North face (+Y)
            if j == ny - 1 or grid[i, j+1] == 0:
                f_n = bm.faces.new([get_v(i, j+1, False), get_v(i, j+1, True), get_v(i+1, j+1, True), get_v(i+1, j+1, False)])
                f_n.material_index = mat_idx

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(f"{name}_Walls_Manifold", mesh)
    obj.data.materials.append(MATS["Wall_Struct"])
    obj.data.materials.append(MATS["Wall_New"])
    link_obj(obj, col)

    # Add curved & angled walls trimmed by 1deg / 5mm so they never overlap grid faces
    if name == "2F_Plan":
        pts_p = arc_band_poly(2731.0, -260.0, 100.0, 2731.0, -260.0, 230.0, 272.0, 358.0)
        add_prism("2F_CurvedWall_Parent", pts_p, z0, z1, MATS["Wall_New"], col)


def add_cad_linework_curve(msp, name, xr, yr, ox, oy, z_level, col):
    """Embed the exact 2D CAD floor plan lines as crisp 3D architectural curve ribbons on the floor."""
    curve_data = bpy.data.curves.new(name=f"{name}_CAD_Lines", type='CURVE')
    curve_data.dimensions = '3D'
    curve_data.bevel_depth = 0.007
    curve_data.bevel_resolution = 1

    target_layers = {"3固定家具布置", "3活动家具布置", "0-108厨卫", "0-106活动家具", "3楼梯", "3门", "1原始窗", "4地面填充"}

    def add_poly_spline(pts_xy):
        if len(pts_xy) < 2:
            return
        if name == "1F":
            # On calibrated 1F, keep only spiral stair and living center linework so shifted West/Toilet/Shaft CAD lines do not ghost
            for px, py in pts_xy:
                if px < -1450.0 or px > 4650.0 or (px < 800.0 and py < -1650.0):
                    return
        sp = curve_data.splines.new('POLY')
        sp.points.add(len(pts_xy) - 1)
        for idx, (px, py) in enumerate(pts_xy):
            sp.points[idx].co = (px * MM, py * MM, z_level, 1.0)

    def process_ent(ent):
        t = ent.dxftype()
        if t == "LINE":
            sx, sy = ent.dxf.start.x, ent.dxf.start.y
            ex, ey = ent.dxf.end.x, ent.dxf.end.y
            if xr[0] <= sx <= xr[1] and yr[0] <= sy <= yr[1]:
                add_poly_spline([(sx - ox, sy - oy), (ex - ox, ey - oy)])
        elif t == "LWPOLYLINE":
            pts = list(ent.get_points())
            if pts and xr[0] <= pts[0][0] <= xr[1] and yr[0] <= pts[0][1] <= yr[1]:
                sampled = []
                n = len(pts)
                cnt = n if ent.closed else n - 1
                for i in range(cnt):
                    x1, y1, _, _, b = pts[i]
                    x2, y2, _, _, _ = pts[(i+1)%n]
                    x1 -= ox; y1 -= oy; x2 -= ox; y2 -= oy
                    if abs(b) < 1e-4:
                        sampled.append((x1, y1))
                    else:
                        theta = 4.0 * math.atan(b)
                        chord = math.hypot(x2 - x1, y2 - y1)
                        if chord > 1e-3:
                            r = chord / (2.0 * math.sin(abs(theta) / 2.0))
                            mx, my = 0.5*(x1+x2), 0.5*(y1+y2)
                            dx, dy = (x2-x1)/chord, (y2-y1)/chord
                            nx, ny = (-dy, dx) if b > 0 else (dy, -dx)
                            d = r * math.cos(theta / 2.0)
                            cx, cy = mx + nx*d, my + ny*d
                            a1 = math.atan2(y1 - cy, x1 - cx)
                            for k in range(8):
                                a = a1 + theta * k / 8
                                sampled.append((cx + r*math.cos(a), cy + r*math.sin(a)))
                if ent.closed and sampled:
                    sampled.append(sampled[0])
                elif not ent.closed and pts:
                    sampled.append((pts[-1][0] - ox, pts[-1][1] - oy))
                add_poly_spline(sampled)
        elif t == "ARC":
            cx, cy = ent.dxf.center.x, ent.dxf.center.y
            if xr[0] <= cx <= xr[1] and yr[0] <= cy <= yr[1]:
                r = ent.dxf.radius
                if r < 5000:
                    a1, a2 = ent.dxf.start_angle, ent.dxf.end_angle
                    if a2 < a1:
                        a2 += 360.0
                    pts = []
                    for k in range(19):
                        a = math.radians(a1 + (a2 - a1)*k/18.0)
                        pts.append((cx + r*math.cos(a) - ox, cy + r*math.sin(a) - oy))
                    add_poly_spline(pts)
        elif t == "CIRCLE":
            cx, cy = ent.dxf.center.x, ent.dxf.center.y
            if xr[0] <= cx <= xr[1] and yr[0] <= cy <= yr[1]:
                r = ent.dxf.radius
                if r < 3000:
                    pts = []
                    for k in range(25):
                        a = 2.0 * math.pi * k / 24.0
                        pts.append((cx + r*math.cos(a) - ox, cy + r*math.sin(a) - oy))
                    add_poly_spline(pts)
        elif t == "INSERT":
            ix, iy = ent.dxf.insert.x, ent.dxf.insert.y
            if xr[0] <= ix <= xr[1] and yr[0] <= iy <= yr[1]:
                for ve in ent.virtual_entities():
                    process_ent(ve)

    for e in msp:
        if e.dxf.layer in target_layers:
            process_ent(e)

    obj = bpy.data.objects.new(f"{name}_CAD_Overlay", curve_data)
    obj.data.materials.append(MATS["CAD_Line_Dark"])
    link_obj(obj, col)
    return obj


# ---------------------------------------------------------------------------
# Architectural Components Builder (Windows, Doors, Stairs, Furniture)
# ---------------------------------------------------------------------------
def build_window(name, x1, x2, y1, y2, z_floor, h_wall, h1_sill, h2_win, col):
    """Build window sill wall, 3D frame + glass, and lintel wall above inside a clean cutout."""
    xa, xb = min(x1, x2) + 2.0, max(x1, x2) - 2.0
    ya, yb = min(y1, y2) + 2.0, max(y1, y2) - 2.0
    if h1_sill > 0.02:
        add_box_mm(f"{name}_Sill", xa, xb, ya, yb, z_floor, z_floor + h1_sill, MATS["Wall_Struct"], col)
    z_top = min(z_floor + h1_sill + h2_win, z_floor + h_wall - 0.05)
    if z_floor + h_wall - z_top > 0.02:
        add_box_mm(f"{name}_Lintel", xa, xb, ya, yb, z_top, z_floor + h_wall, MATS["Wall_Struct"], col)
    ft = 42.0
    w_x = xb - xa
    w_y = yb - ya
    z_a, z_b = z_floor + h1_sill + 0.002, z_top - 0.002
    add_box_mm(f"{name}_FrameBot", xa, xb, ya, yb, z_a, z_a + 0.042, MATS["Window_Frame"], col)
    add_box_mm(f"{name}_FrameTop", xa, xb, ya, yb, z_b - 0.042, z_b, MATS["Window_Frame"], col)
    if w_y > w_x:
        xm = 0.5*(xa + xb)
        fxa, fxb = xm - 22.0, xm + 22.0
        add_box_mm(f"{name}_FrameL", fxa, fxb, ya, ya + ft, z_a + 0.042, z_b - 0.042, MATS["Window_Frame"], col)
        add_box_mm(f"{name}_FrameR", fxa, fxb, yb - ft, yb, z_a + 0.042, z_b - 0.042, MATS["Window_Frame"], col)
        n_mull = max(1, int((yb - ya) / 1100.0))
        for k in range(1, n_mull):
            yk = ya + (yb - ya) * k / n_mull
            add_box_mm(f"{name}_Mull_{k}", xm - 20, xm + 20, yk - 16, yk + 16, z_a + 0.042, z_b - 0.042, MATS["Window_Frame"], col)
        add_box_mm(f"{name}_Glass", xm - 8, xm + 8, ya + ft, yb - ft, z_a + 0.042, z_b - 0.042, MATS["Window_Glass"], col)
    else:
        ym = 0.5*(ya + yb)
        add_box_mm(f"{name}_FrameL", xa, xa + ft, ya, yb, z_a + 0.042, z_b - 0.042, MATS["Window_Frame"], col)
        add_box_mm(f"{name}_FrameR", xb - ft, xb, ya, yb, z_a + 0.042, z_b - 0.042, MATS["Window_Frame"], col)
        n_mull = max(1, int((xb - xa) / 1100.0))
        for k in range(1, n_mull):
            xk = xa + (xb - xa) * k / n_mull
            add_box_mm(f"{name}_Mull_{k}", xk - 18, xk + 18, ym - 28, ym + 28, z_a + 0.042, z_b - 0.042, MATS["Window_Frame"], col)
        add_box_mm(f"{name}_Glass", xa + ft, xb - ft, ym - 10, ym + 10, z_a + 0.042, z_b - 0.042, MATS["Window_Glass"], col)


def build_door(name, x1, x2, y1, y2, z_floor, h_wall, h_door, col, is_glass=False, is_toilet_glass=False, skip_header=False):
    """Build 3D door frame, door leaf, and header wall above inside a clean cutout."""
    xa, xb = min(x1, x2) + 2.0, max(x1, x2) - 2.0
    ya, yb = min(y1, y2) + 2.0, max(y1, y2) - 2.0
    z_top = z_floor + h_door
    if not skip_header and z_floor + h_wall - z_top > 0.02:
        add_box_mm(f"{name}_Header", xa, xb, ya, yb, z_top, z_floor + h_wall, MATS["Wall_New"], col)
    w_x = xb - xa
    w_y = yb - ya
    if is_toilet_glass:
        frame_mat = MATS["Stair_Bronze_Iron"]
        glass_mat = MATS["Toilet_Frosted_Silk_Glass"]
        jf = 30.0
        st = 26.0
        add_box_mm(f"{name}_TopFrame", xa, xb, ya, yb, z_top - 0.030, z_top - 0.002, frame_mat, col)
        z_in0 = z_floor + 0.005
        z_in1 = z_top - 0.030
        if w_y > w_x:
            xm = 0.5 * (xa + xb)
            add_box_mm(f"{name}_Jamb1", xa, xb, ya, ya + jf, z_in0, z_in1, frame_mat, col)
            add_box_mm(f"{name}_Jamb2", xa, xb, yb - jf, yb, z_in0, z_in1, frame_mat, col)
            ly0, ly1 = ya + jf + 2.0, yb - jf - 2.0
            lz0, lz1 = z_floor + 0.010, z_in1 - 0.002
            add_box_mm(f"{name}_LeafStile1", xm - 19.0, xm + 19.0, ly0, ly0 + st, lz0, lz1, frame_mat, col)
            add_box_mm(f"{name}_LeafStile2", xm - 19.0, xm + 19.0, ly1 - st, ly1, lz0, lz1, frame_mat, col)
            add_box_mm(f"{name}_LeafBotRail", xm - 19.0, xm + 19.0, ly0 + st, ly1 - st, lz0, lz0 + 0.028, frame_mat, col)
            add_box_mm(f"{name}_LeafTopRail", xm - 19.0, xm + 19.0, ly0 + st, ly1 - st, lz1 - 0.026, lz1, frame_mat, col)
            pane_w_m = max(0.20, (ly1 - ly0 - 2.0 * st) * MM)
            pane_h_m = max(0.40, (lz1 - lz0 - 0.054))
            add_uv_side_box_mm(
                f"{name}_Leaf", xm - 7.0, xm + 7.0, ly0 + st, ly1 - st, lz0 + 0.028, lz1 - 0.026,
                0.0, pane_w_m / 0.45, 0.0, pane_h_m / 0.90, glass_mat, col
            )
            hy = ly1 - st - 54.0
            add_box_mm(f"{name}_Handle_A", xm - 34.0, xm - 20.0, hy - 9.0, hy + 9.0, z_floor + 0.94, z_floor + 1.26, frame_mat, col)
            add_box_mm(f"{name}_Handle_B", xm + 20.0, xm + 34.0, hy - 9.0, hy + 9.0, z_floor + 0.94, z_floor + 1.26, frame_mat, col)
            for sgn_i, (sx0, sx1) in enumerate(((xm - 20.0, xm - 7.0), (xm + 7.0, xm + 20.0)), 1):
                for pk, pz in enumerate((z_floor + 0.97, z_floor + 1.23), 1):
                    add_box_mm(f"{name}_HandlePost_{sgn_i}_{pk}", sx0, sx1, hy - 5.0, hy + 5.0, pz - 0.005, pz + 0.005, frame_mat, col)
        else:
            ym = 0.5 * (ya + yb)
            add_box_mm(f"{name}_Jamb1", xa, xa + jf, ya, yb, z_in0, z_in1, frame_mat, col)
            add_box_mm(f"{name}_Jamb2", xb - jf, xb, ya, yb, z_in0, z_in1, frame_mat, col)
            lx0, lx1 = xa + jf + 2.0, xb - jf - 2.0
            lz0, lz1 = z_floor + 0.010, z_in1 - 0.002
            add_box_mm(f"{name}_LeafStile1", lx0, lx0 + st, ym - 19.0, ym + 19.0, lz0, lz1, frame_mat, col)
            add_box_mm(f"{name}_LeafStile2", lx1 - st, lx1, ym - 19.0, ym + 19.0, lz0, lz1, frame_mat, col)
            add_box_mm(f"{name}_LeafBotRail", lx0 + st, lx1 - st, ym - 19.0, ym + 19.0, lz0, lz0 + 0.028, frame_mat, col)
            add_box_mm(f"{name}_LeafTopRail", lx0 + st, lx1 - st, ym - 19.0, ym + 19.0, lz1 - 0.026, lz1, frame_mat, col)
            pane_w_m = max(0.20, (lx1 - lx0 - 2.0 * st) * MM)
            pane_h_m = max(0.40, (lz1 - lz0 - 0.054))
            add_uv_front_box_mm(
                f"{name}_Leaf", lx0 + st, lx1 - st, ym - 7.0, ym + 7.0, lz0 + 0.028, lz1 - 0.026,
                0.0, pane_w_m / 0.45, 0.0, pane_h_m / 0.90, glass_mat, col
            )
            hx = lx1 - st - 54.0
            add_box_mm(f"{name}_Handle_A", hx - 9.0, hx + 9.0, ym - 34.0, ym - 20.0, z_floor + 0.94, z_floor + 1.26, frame_mat, col)
            add_box_mm(f"{name}_Handle_B", hx - 9.0, hx + 9.0, ym + 20.0, ym + 34.0, z_floor + 0.94, z_floor + 1.26, frame_mat, col)
            for sgn_i, (sy0, sy1) in enumerate(((ym - 20.0, ym - 7.0), (ym + 7.0, ym + 20.0)), 1):
                for pk, pz in enumerate((z_floor + 0.97, z_floor + 1.23), 1):
                    add_box_mm(f"{name}_HandlePost_{sgn_i}_{pk}", hx - 5.0, hx + 5.0, sy0, sy1, pz - 0.005, pz + 0.005, frame_mat, col)
        return

    leaf_mat = MATS["Window_Glass"] if is_glass else MATS["Door_Wood"]
    frame_mat = MATS["Window_Frame"] if is_glass else MATS["Door_Frame"]
    add_box_mm(f"{name}_TopFrame", xa, xb, ya, yb, z_top - 0.04, z_top - 0.002, frame_mat, col)
    if w_y > w_x:
        xm = 0.5*(xa + xb)
        add_box_mm(f"{name}_Jamb1", xa, xb, ya, ya + 38, z_floor + 0.005, z_top - 0.04, frame_mat, col)
        add_box_mm(f"{name}_Jamb2", xa, xb, yb - 38, yb, z_floor + 0.005, z_top - 0.04, frame_mat, col)
        add_box_mm(f"{name}_Leaf", xm - 20, xm + 20, ya + 38, yb - 38, z_floor + 0.01, z_top - 0.04, leaf_mat, col)
    else:
        ym = 0.5*(ya + yb)
        add_box_mm(f"{name}_Jamb1", xa, xa + 38, ya, yb, z_floor + 0.005, z_top - 0.04, frame_mat, col)
        add_box_mm(f"{name}_Jamb2", xb - 38, xb, ya, yb, z_floor + 0.005, z_top - 0.04, frame_mat, col)
        add_box_mm(f"{name}_Leaf", xa + 38, xb - 38, ym - 20, ym + 20, z_floor + 0.01, z_top - 0.04, leaf_mat, col)


def build_spiral_stair_flight(name, cx_mm, cy_mm, r_in_mm, r_out_mm, deg_start, deg_end, z_start, z_end, n_steps, col):
    d_deg = (deg_end - deg_start) / n_steps
    dz = (z_end - z_start) / n_steps
    sign_dir = 1.0 if d_deg >= 0 else -1.0
    for i in range(n_steps):
        a1 = deg_start + i * d_deg
        a2 = deg_start + (i + 1.03) * d_deg
        zt = z_start + (i + 1) * dz
        zb = z_start + i * dz
        ri_m, ro_m = r_in_mm + 2.0, r_out_mm - 2.0
        n_arc = 6
        u_shift = 0.06 * math.sin(i * 0.45)
        u_in, u_out = 0.08 + u_shift, 0.92 + u_shift
        v0 = (i / float(max(1, n_steps))) * 0.78
        v1 = ((i + 1) / float(max(1, n_steps))) * 0.78
        mesh_tr = bpy.data.meshes.new(f"{name}_Tread_{i+1}")
        bm_tr = bmesh.new()
        uv_tr = bm_tr.loops.layers.uv.verify()
        vin_b, vin_t, vout_b, vout_t = [], [], [], []
        angs_tr = [math.radians(a1 + (a2 - a1) * k / float(n_arc)) for k in range(n_arc + 1)]
        for ar in angs_tr:
            ca, sa = math.cos(ar), math.sin(ar)
            vin_b.append(bm_tr.verts.new(((cx_mm + ri_m * ca) * MM, (cy_mm + ri_m * sa) * MM, zt - 0.048)))
            vin_t.append(bm_tr.verts.new(((cx_mm + ri_m * ca) * MM, (cy_mm + ri_m * sa) * MM, zt)))
            vout_b.append(bm_tr.verts.new(((cx_mm + ro_m * ca) * MM, (cy_mm + ro_m * sa) * MM, zt - 0.048)))
            vout_t.append(bm_tr.verts.new(((cx_mm + ro_m * ca) * MM, (cy_mm + ro_m * sa) * MM, zt)))
        for k in range(n_arc):
            fa = v0 + (v1 - v0) * (k / float(n_arc))
            fb = v0 + (v1 - v0) * ((k + 1) / float(n_arc))
            ft = bm_tr.faces.new([vin_t[k], vout_t[k], vout_t[k + 1], vin_t[k + 1]])
            for lp, uv in zip(ft.loops, [(u_in, fa), (u_out, fa), (u_out, fb), (u_in, fb)]):
                lp[uv_tr].uv = uv
            fd = bm_tr.faces.new([vin_b[k + 1], vout_b[k + 1], vout_b[k], vin_b[k]])
            for lp, uv in zip(fd.loops, [(u_in, fb), (u_out, fb), (u_out, fa), (u_in, fa)]):
                lp[uv_tr].uv = uv
            fi = bm_tr.faces.new([vin_b[k], vin_t[k], vin_t[k + 1], vin_b[k + 1]])
            for lp, uv in zip(fi.loops, [(u_in + 0.03, fa), (u_in, fa), (u_in, fb), (u_in + 0.03, fb)]):
                lp[uv_tr].uv = uv
            fo = bm_tr.faces.new([vout_b[k + 1], vout_t[k + 1], vout_t[k], vout_b[k]])
            for lp, uv in zip(fo.loops, [(u_out - 0.03, fb), (u_out, fb), (u_out, fa), (u_out - 0.03, fa)]):
                lp[uv_tr].uv = uv
        f_st = bm_tr.faces.new([vin_b[0], vout_b[0], vout_t[0], vin_t[0]])
        for lp, uv in zip(f_st.loops, [(u_in, v0), (u_out, v0), (u_out, v0 + 0.04), (u_in, v0 + 0.04)]):
            lp[uv_tr].uv = uv
        f_en = bm_tr.faces.new([vin_b[-1], vin_t[-1], vout_t[-1], vout_b[-1]])
        for lp, uv in zip(f_en.loops, [(u_in, v1), (u_in, v1 + 0.04), (u_out, v1 + 0.04), (u_out, v1)]):
            lp[uv_tr].uv = uv
        bmesh.ops.recalc_face_normals(bm_tr, faces=bm_tr.faces[:])
        bm_tr.to_mesh(mesh_tr)
        bm_tr.free()
        obj_tr = bpy.data.objects.new(f"{name}_Tread_{i+1}", mesh_tr)
        obj_tr.data.materials.append(MATS["Stair_Ink_Marble"])
        link_obj(obj_tr, col)
        a_riser_end = a1 + sign_dir * 1.4
        pts_riser = arc_band_poly(cx_mm, cy_mm, r_in_mm + 4.0, cx_mm, cy_mm, r_out_mm - 4.0, min(a1, a_riser_end), max(a1, a_riser_end), n=2)
        add_prism(f"{name}_Riser_{i+1}", pts_riser, zb + 0.002, zt - 0.048, MATS["Stair_Balustrade"], col)

    for btype, r_a, r_b in [("OuterBal", r_out_mm, r_out_mm + 40.0), ("InnerBal", r_in_mm - 40.0, r_in_mm)]:
        segs = n_steps * 3
        is_inner_iron = (btype == "InnerBal")
        # 1) Slim helical bottom stringer / base
        mesh_str = bpy.data.meshes.new(f"{name}_{btype}_Stringer")
        bm_str = bmesh.new()
        rings_str = []
        for k in range(segs + 1):
            t = k / segs
            ang = math.radians(deg_start + (deg_end - deg_start) * t)
            zk = z_start + (z_end - z_start) * t
            z_bot = zk - 0.14
            z_top = zk + 0.02
            v0 = bm_str.verts.new(((cx_mm + r_a*math.cos(ang))*MM, (cy_mm + r_a*math.sin(ang))*MM, z_bot))
            v1 = bm_str.verts.new(((cx_mm + r_b*math.cos(ang))*MM, (cy_mm + r_b*math.sin(ang))*MM, z_bot))
            v2 = bm_str.verts.new(((cx_mm + r_b*math.cos(ang))*MM, (cy_mm + r_b*math.sin(ang))*MM, z_top))
            v3 = bm_str.verts.new(((cx_mm + r_a*math.cos(ang))*MM, (cy_mm + r_a*math.sin(ang))*MM, z_top))
            rings_str.append((v0, v1, v2, v3))
        for k in range(segs):
            r0, r1 = rings_str[k], rings_str[k+1]
            for s in range(4):
                bm_str.faces.new([r0[s], r0[(s+1)%4], r1[(s+1)%4], r1[s]])
        bm_str.faces.new(list(rings_str[0])[::-1])
        bm_str.faces.new(list(rings_str[-1]))
        bmesh.ops.recalc_face_normals(bm_str, faces=bm_str.faces[:])
        bm_str.to_mesh(mesh_str)
        bm_str.free()
        obj_str = bpy.data.objects.new(f"{name}_{btype}_Stringer", mesh_str)
        obj_str.data.materials.append(MATS["Gold_Velvet_ArtPaint"] if is_inner_iron else MATS["Stair_Balustrade"])
        link_obj(obj_str, col)

        # 2) Outer enclosure is transparent glass; Inner (center) balustrade is solid wrought/cast iron (楼梯外包围是玻璃，中间扶手是铁质的)
        b_suffix = "Iron" if is_inner_iron else "Glass"
        mesh = bpy.data.meshes.new(f"{name}_{btype}_{b_suffix}")
        bm = bmesh.new()
        rings = []
        r_ga = 0.5 * (r_a + r_b) - (14.0 if is_inner_iron else 10.0)
        r_gb = 0.5 * (r_a + r_b) + (14.0 if is_inner_iron else 10.0)
        for k in range(segs + 1):
            t = k / segs
            ang = math.radians(deg_start + (deg_end - deg_start) * t)
            zk = z_start + (z_end - z_start) * t
            z_bot = zk + 0.022
            z_top = zk + 0.90
            v0 = bm.verts.new(((cx_mm + r_ga*math.cos(ang))*MM, (cy_mm + r_ga*math.sin(ang))*MM, z_bot))
            v1 = bm.verts.new(((cx_mm + r_gb*math.cos(ang))*MM, (cy_mm + r_gb*math.sin(ang))*MM, z_bot))
            v2 = bm.verts.new(((cx_mm + r_gb*math.cos(ang))*MM, (cy_mm + r_gb*math.sin(ang))*MM, z_top))
            v3 = bm.verts.new(((cx_mm + r_ga*math.cos(ang))*MM, (cy_mm + r_ga*math.sin(ang))*MM, z_top))
            rings.append((v0, v1, v2, v3))
        for k in range(segs):
            r0, r1 = rings[k], rings[k+1]
            for s in range(4):
                bm.faces.new([r0[s], r0[(s+1)%4], r1[(s+1)%4], r1[s]])
        bm.faces.new(list(rings[0])[::-1])
        bm.faces.new(list(rings[-1]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(f"{name}_{btype}_{b_suffix}", mesh)
        obj.data.materials.append(MATS["Gold_Velvet_ArtPaint"] if is_inner_iron else MATS["Window_Glass"])
        link_obj(obj, col)

        # 3) Helical top handrail cap ONLY on inner iron balustrade (玻璃上没有扶手，只是简单的平白玻璃)
        if is_inner_iron:
            mesh_hr = bpy.data.meshes.new(f"{name}_{btype}_Handrail")
            bm_hr = bmesh.new()
            rings_hr = []
            r_ha, r_hb = r_a - 4.0, r_b + 4.0
            for k in range(segs + 1):
                t = k / segs
                ang = math.radians(deg_start + (deg_end - deg_start) * t)
                zk = z_start + (z_end - z_start) * t
                z_bot = zk + 0.902
                z_top = zk + 0.945
                v0 = bm_hr.verts.new(((cx_mm + r_ha*math.cos(ang))*MM, (cy_mm + r_ha*math.sin(ang))*MM, z_bot))
                v1 = bm_hr.verts.new(((cx_mm + r_hb*math.cos(ang))*MM, (cy_mm + r_hb*math.sin(ang))*MM, z_bot))
                v2 = bm_hr.verts.new(((cx_mm + r_hb*math.cos(ang))*MM, (cy_mm + r_hb*math.sin(ang))*MM, z_top))
                v3 = bm_hr.verts.new(((cx_mm + r_ha*math.cos(ang))*MM, (cy_mm + r_ha*math.sin(ang))*MM, z_top))
                rings_hr.append((v0, v1, v2, v3))
            for k in range(segs):
                r0, r1 = rings_hr[k], rings_hr[k+1]
                for s in range(4):
                    bm_hr.faces.new([r0[s], r0[(s+1)%4], r1[(s+1)%4], r1[s]])
            bm_hr.faces.new(list(rings_hr[0])[::-1])
            bm_hr.faces.new(list(rings_hr[-1]))
            bmesh.ops.recalc_face_normals(bm_hr, faces=bm_hr.faces[:])
            bm_hr.to_mesh(mesh_hr)
            bm_hr.free()
            obj_hr = bpy.data.objects.new(f"{name}_{btype}_Handrail", mesh_hr)
            obj_hr.data.materials.append(MATS["Gold_Velvet_ArtPaint"])
            link_obj(obj_hr, col)


def build_bed(name, x1, x2, y1, y2, z_floor, head_side, col):
    z0 = z_floor + 0.005
    add_box_mm(f"{name}_Base", x1, x2, y1, y2, z0, z0 + 0.25, MATS["Cabinet_Walnut"], col, r_corner=30.0)
    add_box_mm(f"{name}_Mattress", x1 + 40, x2 - 40, y1 + 40, y2 - 40, z0 + 0.25, z0 + 0.48, MATS["Bed_Linen"], col, r_corner=60.0)
    xm = 0.5*(x1 + x2)
    if head_side == "bottom":
        add_box_mm(f"{name}_Headboard", x1 - 30, x2 + 30, y1, y1 + 110, z0 + 0.25, z0 + 1.06, MATS["Accent_Leather"], col, r_corner=25.0)
        add_box_mm(f"{name}_Throw", x1 + 35, x2 - 35, y1 + 650, y2 - 35, z0 + 0.48, z0 + 0.52, MATS["Bed_Throw"], col, r_corner=50.0)
        add_box_mm(f"{name}_Pillow1", x1 + 140, xm - 40, y1 + 140, y1 + 520, z0 + 0.48, z0 + 0.60, MATS["Bed_Linen"], col, r_corner=60.0)
        add_box_mm(f"{name}_Pillow2", xm + 40, x2 - 140, y1 + 140, y1 + 520, z0 + 0.48, z0 + 0.60, MATS["Bed_Linen"], col, r_corner=60.0)
    else:
        add_box_mm(f"{name}_Headboard", x1 - 30, x2 + 30, y2 - 110, y2, z0 + 0.25, z0 + 1.06, MATS["Accent_Leather"], col, r_corner=25.0)
        add_box_mm(f"{name}_Throw", x1 + 35, x2 - 35, y1 + 35, y2 - 650, z0 + 0.48, z0 + 0.52, MATS["Bed_Throw"], col, r_corner=50.0)
        add_box_mm(f"{name}_Pillow1", x1 + 140, xm - 40, y2 - 520, y2 - 140, z0 + 0.48, z0 + 0.60, MATS["Bed_Linen"], col, r_corner=60.0)
        add_box_mm(f"{name}_Pillow2", xm + 40, x2 - 140, y2 - 520, y2 - 140, z0 + 0.48, z0 + 0.60, MATS["Bed_Linen"], col, r_corner=60.0)


# ---------------------------------------------------------------------------
# Infinito Single-Pedestal Dining Table (无限单脚桌) Generator
# ---------------------------------------------------------------------------
def build_infinito_pedestal_bm(height=0.690, scale_xy=1.0):
    """
    Constructs the exact Poltrona Frau Infinito 3-fin sculptural marble pedestal
    (matching /Users/muwusah/Documents/AI/Architect/house/家具/桌子/无限单脚/3D模型/无限单脚桌.blend).
    """
    bm = bmesh.new()

    r_nose = 0.0135 * scale_xy
    z_bot = 0.006
    z_sad = 0.420 * (height / 0.690)
    z_shld = 0.466 * (height / 0.690)
    z_top = height

    S_bot = np.array([
        [-0.2615, +0.0600],
        [+0.1765, -0.3175],
        [+0.3675, +0.3175],
    ]) * scale_xy

    S_top = np.array([
        [-0.3780, -0.0990],
        [+0.2865, -0.2575],
        [+0.1560, +0.2540],
    ]) * scale_xy

    M_bot = np.array([
        [+0.0280, -0.0620],
        [+0.1480, -0.0050],
        [+0.0320, +0.0920],
    ]) * scale_xy

    M_top = np.array([
        [+0.0420, -0.1080],
        [+0.1450, -0.0120],
        [-0.0120, +0.0780],
    ]) * scale_xy

    d_tan_list = [0.082 * scale_xy, 0.078 * scale_xy, 0.068 * scale_xy]
    f_top = [0.46, 0.22, 0.25]

    def get_section_2d(z):
        t = z / z_top
        S = (1.0 - t) * S_bot + t * S_top
        M = (1.0 - t) * M_bot + t * M_top
        C = M.mean(axis=0)

        P = np.zeros_like(S)
        for i in range(3):
            u = S[i] - C
            u = u / np.linalg.norm(u)
            P[i] = S[i] - r_nose * u

        nose_data = []
        for i in range(3):
            m_prev = M[(i - 1) % 3]
            m_next = M[i]
            d1 = P[i] - m_prev
            u1 = d1 / np.linalg.norm(d1)
            n1 = np.array([u1[1], -u1[0]])
            tp_in = P[i] + r_nose * n1

            d2 = P[i] - m_next
            u2 = d2 / np.linalg.norm(d2)
            n2 = np.array([-u2[1], u2[0]])
            tp_out = P[i] + r_nose * n2

            ang1 = math.atan2(n1[1], n1[0])
            ang2 = math.atan2(n2[1], n2[0])
            da = (ang2 - ang1) % (2.0 * math.pi)
            if da > math.pi:
                da -= 2.0 * math.pi
            nose_pts = []
            for k in range(5):
                ang = ang1 + (k / 4.0) * da
                pt = P[i] + r_nose * np.array([math.cos(ang), math.sin(ang)])
                nose_pts.append(pt)
            nose_data.append((tp_in, tp_out, nose_pts, P[i]))

        val_data = []
        for i in range(3):
            d_tan = d_tan_list[i]
            j = (i + 1) % 3
            A = nose_data[i][1]
            B = M[i]
            C_pt = nose_data[j][0]
            u1 = (A - B) / np.linalg.norm(A - B)
            u2 = (C_pt - B) / np.linalg.norm(C_pt - B)
            tv1 = B + d_tan * u1
            tv2 = B + d_tan * u2
            cos_th = np.clip(np.dot(u1, u2), -0.999, 0.999)
            half_ang = 0.5 * math.acos(cos_th)
            R_v = d_tan * math.tan(half_ang)
            bis = (u1 + u2) / np.linalg.norm(u1 + u2)
            arc_c = B + (R_v / math.sin(half_ang)) * bis

            a1 = math.atan2(tv1[1] - arc_c[1], tv1[0] - arc_c[0])
            a2 = math.atan2(tv2[1] - arc_c[1], tv2[0] - arc_c[0])
            da = (a2 - a1) % (2.0 * math.pi)
            if da > math.pi:
                da -= 2.0 * math.pi

            def sample_arc(w, a1=a1, da=da, arc_c=arc_c, R_v=R_v):
                ang = a1 + w * da
                return arc_c + R_v * np.array([math.cos(ang), math.sin(ang)])

            val_data.append((tv1, tv2, sample_arc, abs(da) * R_v))

        return nose_data, val_data, C, S

    def sample_right_wall(nd_i, vd_i, s_end):
        tp_out = nd_i[1]
        tv1, _, arc_fn, _ = vd_i
        s_tv = 0.70

        def eval_s(s):
            if s <= s_tv:
                u = s / s_tv
                return (1.0 - u) * tp_out + u * tv1
            else:
                w = 0.50 * (s - s_tv) / (1.0 - s_tv)
                return arc_fn(w)

        return [eval_s(0.25 * s_end), eval_s(0.50 * s_end), eval_s(0.75 * s_end), eval_s(s_end)]

    def sample_left_wall(nd_i, vd_prev, s_end):
        tp_in = nd_i[0]
        _, tv2_prev, arc_prev, _ = vd_prev
        s_tv = 0.70

        def eval_s(s):
            if s <= s_tv:
                u = s / s_tv
                return (1.0 - u) * tp_in + u * tv2_prev
            else:
                w = 1.0 - 0.50 * (s - s_tv) / (1.0 - s_tv)
                return arc_prev(w)

        return [eval_s(s_end), eval_s(0.75 * s_end), eval_s(0.50 * s_end), eval_s(0.25 * s_end)]

    zs_trunk = [
        z_bot,
        z_bot + 0.004,
        0.060,
        0.140,
        0.220,
        0.300,
        0.365,
        0.400,
        z_sad - 0.006,
        z_sad,
    ]

    trunk_loops = []
    for z in zs_trunk:
        nd, vd, C, S = get_section_2d(z)
        loop_verts = []
        for i in range(3):
            i_prev = (i - 1) % 3
            _, _, nose_pts, _ = nd[i]
            p12, p13, p14, p15 = sample_left_wall(nd[i], vd[i_prev], 1.0)
            p5, p6, p7, p8 = sample_right_wall(nd[i], vd[i], 1.0)

            pts_12 = [
                p13, p14, p15,
                nose_pts[0], nose_pts[1], nose_pts[2], nose_pts[3], nose_pts[4],
                p5, p6, p7, p8,
            ]
            for p in pts_12:
                loop_verts.append(bm.verts.new((p[0], p[1], z)))
        trunk_loops.append(loop_verts)

    for k in range(len(trunk_loops) - 1):
        L0 = trunk_loops[k]
        L1 = trunk_loops[k + 1]
        for m in range(36):
            nm = (m + 1) % 36
            bm.faces.new([L0[m], L0[nm], L1[nm], L1[m]])

    _, _, C_bot, _ = get_section_2d(z_bot)
    v_bot_center = bm.verts.new((C_bot[0], C_bot[1], z_bot))
    for m in range(36):
        nm = (m + 1) % 36
        bm.faces.new([trunk_loops[0][nm], trunk_loops[0][m], v_bot_center])

    nd_sad, vd_sad, C_sad, S_sad = get_section_2d(z_sad)
    z_c_dome = z_sad + 0.024 * (height / 0.690)
    z_m_dome = z_sad + 0.014 * (height / 0.690)
    v_sad_center = bm.verts.new((C_sad[0], C_sad[1], z_c_dome))

    v_sad_mid = []
    for i in range(3):
        arc_mid_pt = vd_sad[i][2](0.50)
        mid_xy = 0.52 * arc_mid_pt + 0.48 * C_sad
        v_sad_mid.append(bm.verts.new((mid_xy[0], mid_xy[1], z_m_dome)))

    top_trunk = trunk_loops[-1]
    branch_loops = [[], [], []]
    for i in range(3):
        i_prev = (i - 1) % 3
        base = 12 * i
        loop_0 = [
            top_trunk[base + 3], top_trunk[base + 4], top_trunk[base + 5],
            top_trunk[base + 6], top_trunk[base + 7], top_trunk[base + 8],
            top_trunk[base + 9], top_trunk[base + 10], top_trunk[base + 11],
            v_sad_mid[i], v_sad_center, v_sad_mid[i_prev],
            top_trunk[(base - 1) % 36],
            top_trunk[base + 0], top_trunk[base + 1], top_trunk[base + 2],
        ]
        branch_loops[i].append(loop_0)

    alphas = [0.20 * math.pi, 0.35 * math.pi, 0.50 * math.pi]
    us_upper = [0.10, 0.25, 0.44, 0.64, 0.84, 0.96, 1.00]

    upper_steps = []
    for a in alphas:
        z_val = z_shld - (z_shld - z_sad) * math.cos(a)
        upper_steps.append(("u_curve", a, z_val))
    for u in us_upper:
        z_val = z_shld + u * (z_top - z_shld)
        upper_steps.append(("v_slope", u, z_val))

    for mode, param, z in upper_steps:
        nd, vd, C, S = get_section_2d(z)
        for i in range(3):
            i_prev = (i - 1) % 3
            _, _, nose_pts, _ = nd[i]

            if mode == "u_curve":
                a = param
                sa = math.sin(a)
                s_end = 1.0 - 0.30 * sa
                p5, p6, p7, p8 = sample_right_wall(nd[i], vd[i], s_end)
                p12, p13, p14, p15 = sample_left_wall(nd[i], vd[i_prev], s_end)

                u_in = C - S[i]
                u_in = u_in / np.linalg.norm(u_in)
                mid_in = 0.5 * (p8 + p12)
                half_chord = 0.5 * (p8 - p12)
                d_bull = 0.032 * scale_xy

                bull_9 = mid_in + math.cos(math.pi / 4.0) * half_chord + d_bull * math.sin(math.pi / 4.0) * u_in
                bull_10 = mid_in + d_bull * u_in
                bull_11 = mid_in + math.cos(3.0 * math.pi / 4.0) * half_chord + d_bull * math.sin(3.0 * math.pi / 4.0) * u_in

                sad_9 = 0.52 * vd[i][2](0.50) + 0.48 * C
                sad_10 = C
                sad_11 = 0.52 * vd[i_prev][2](0.50) + 0.48 * C

                w_blend = sa ** 0.85
                p9 = (1.0 - w_blend) * sad_9 + w_blend * bull_9
                p10 = (1.0 - w_blend) * sad_10 + w_blend * bull_10
                p11 = (1.0 - w_blend) * sad_11 + w_blend * bull_11

                z_inner_10 = z + (1.0 - sa * 0.55) * 0.022 * (height / 0.690)
                z_inner_9 = z + (1.0 - sa * 0.65) * 0.013 * (height / 0.690)
            else:
                u = param
                s_end = 0.70 * (1.0 - f_top[i] * u)
                p5, p6, p7, p8 = sample_right_wall(nd[i], vd[i], s_end)
                p12, p13, p14, p15 = sample_left_wall(nd[i], vd[i_prev], s_end)

                u_in = C - S[i]
                u_in = u_in / np.linalg.norm(u_in)
                mid_in = 0.5 * (p8 + p12)
                half_chord = 0.5 * (p8 - p12)
                d_bull = (0.032 - 0.006 * u) * scale_xy

                p9 = mid_in + math.cos(math.pi / 4.0) * half_chord + d_bull * math.sin(math.pi / 4.0) * u_in
                p10 = mid_in + d_bull * u_in
                p11 = mid_in + math.cos(3.0 * math.pi / 4.0) * half_chord + d_bull * math.sin(3.0 * math.pi / 4.0) * u_in

                flat_w = max(0.0, 1.0 - (u / 0.94) ** 2) if u < 0.94 else 0.0
                z_inner_10 = z + flat_w * 0.010 * (height / 0.690)
                z_inner_9 = z + flat_w * 0.005 * (height / 0.690)

            pts_xy_z = [
                (nose_pts[0], z), (nose_pts[1], z), (nose_pts[2], z), (nose_pts[3], z), (nose_pts[4], z),
                (p5, z), (p6, z), (p7, z), (p8, z),
                (p9, z_inner_9), (p10, z_inner_10), (p11, z_inner_9),
                (p12, z), (p13, z), (p14, z), (p15, z),
            ]
            loop_verts = [bm.verts.new((pt[0], pt[1], zv)) for pt, zv in pts_xy_z]
            branch_loops[i].append(loop_verts)

    for i in range(3):
        B_loops = branch_loops[i]
        for k in range(len(B_loops) - 1):
            L0 = B_loops[k]
            L1 = B_loops[k + 1]
            for m in range(16):
                nm = (m + 1) % 16
                bm.faces.new([L0[m], L0[nm], L1[nm], L1[m]])

        top_L = B_loops[-1]
        c_xy = np.mean([[v.co.x, v.co.y] for v in top_L], axis=0)
        v_top_c = bm.verts.new((c_xy[0], c_xy[1], z_top))
        for m in range(16):
            nm = (m + 1) % 16
            bm.faces.new([top_L[m], top_L[nm], v_top_c])

    nd_0, _, C_0, S_0 = get_section_2d(0.0)
    r_glide = 0.024 * scale_xy
    for i in range(3):
        u_dir = S_0[i] - C_0
        u_dir = u_dir / np.linalg.norm(u_dir)
        g_center = S_0[i] - 0.042 * scale_xy * u_dir
        g_bot = []
        g_top = []
        for k in range(12):
            ang = k * (2.0 * math.pi / 12.0)
            gx = g_center[0] + r_glide * math.cos(ang)
            gy = g_center[1] + r_glide * math.sin(ang)
            g_bot.append(bm.verts.new((gx, gy, 0.0)))
            g_top.append(bm.verts.new((gx, gy, z_bot)))
        v_gb_c = bm.verts.new((g_center[0], g_center[1], 0.0))
        v_gt_c = bm.verts.new((g_center[0], g_center[1], z_bot))
        for k in range(12):
            nk = (k + 1) % 12
            bm.faces.new([g_bot[k], g_bot[nk], g_top[nk], g_top[k]])
            bm.faces.new([g_bot[nk], g_bot[k], v_gb_c])
            bm.faces.new([g_top[k], g_top[nk], v_gt_c])

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def build_single_tabletop_mesh(length=2.20, width=1.24, z_top=0.74, z_bot=0.69, z_chamfer=0.718):
    from mathutils.geometry import tessellate_polygon
    bm = bmesh.new()
    n_pts = 64
    a = length / 2.0
    b = width / 2.0
    m_exp = 2.45

    outer_pts = []
    for i in range(n_pts):
        th = i * 2.0 * math.pi / n_pts
        c = math.cos(th)
        s = math.sin(th)
        x = a * math.copysign(abs(c) ** (2.0 / m_exp), c)
        y = b * math.copysign(abs(s) ** (2.0 / m_exp), s)
        outer_pts.append((x, y))

    inset = 0.042
    inner_pts = []
    for x, y in outer_pts:
        nx = x / a
        ny = y / b
        norm = math.hypot(nx, ny)
        ix = x - inset * (nx / norm) if norm > 1e-6 else x
        iy = y - inset * (ny / norm) if norm > 1e-6 else y
        inner_pts.append((ix, iy))

    r_top = [bm.verts.new((x, y, z_top)) for x, y in outer_pts]
    r_mid = [bm.verts.new((x, y, z_chamfer)) for x, y in outer_pts]
    r_bot = [bm.verts.new((x, y, z_bot)) for x, y in inner_pts]

    poly2d = [Vector((x, y, 0)) for x, y in outer_pts]
    tris = tessellate_polygon([poly2d])

    for tr in tris:
        p0, p1, p2 = outer_pts[tr[0]], outer_pts[tr[1]], outer_pts[tr[2]]
        cross_z = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0])
        if cross_z < 0:
            bm.faces.new([r_top[tr[2]], r_top[tr[1]], r_top[tr[0]]])
        else:
            bm.faces.new([r_top[tr[0]], r_top[tr[1]], r_top[tr[2]]])

    for i in range(n_pts):
        ni = (i + 1) % n_pts
        bm.faces.new([r_top[i], r_top[ni], r_mid[ni], r_mid[i]])

    for i in range(n_pts):
        ni = (i + 1) % n_pts
        bm.faces.new([r_mid[i], r_mid[ni], r_bot[ni], r_bot[i]])

    for tr in tris:
        p0, p1, p2 = inner_pts[tr[0]], inner_pts[tr[1]], inner_pts[tr[2]]
        cross_z = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0])
        if cross_z > 0:
            bm.faces.new([r_bot[tr[2]], r_bot[tr[1]], r_bot[tr[0]]])
        else:
            bm.faces.new([r_bot[tr[0]], r_bot[tr[1]], r_bot[tr[2]]])

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def get_white_marble_material():
    mat = bpy.data.materials.get("PBR_White_Carrara_Marble")
    if mat:
        return mat
    mat = bpy.data.materials.new("PBR_White_Carrara_Marble")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")

    tex_noise = nt.nodes.new("ShaderNodeTexNoise")
    tex_noise.inputs["Scale"].default_value = 3.5
    tex_noise.inputs["Detail"].default_value = 6.0
    tex_noise.inputs["Roughness"].default_value = 0.55
    tex_noise.inputs["Distortion"].default_value = 2.2

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = (0.60, 0.60, 0.59, 1.0)
    ramp.color_ramp.elements[1].position = 0.50
    ramp.color_ramp.elements[1].color = (0.96, 0.95, 0.94, 1.0)

    nt.links.new(tex_noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.18
    if "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = 1.54
    return mat


def add_infinito_single_table(name, cx_mm, cy_mm, z0, col):
    """Place the generated 3D Infinito Single-Pedestal Dining Table (无限单脚桌) in the scene."""
    white_mat = get_white_marble_material()
    loc = Vector((cx_mm * MM, cy_mm * MM, z0))

    bm_ped = build_infinito_pedestal_bm(height=0.690, scale_xy=1.0)
    m_ped = bpy.data.meshes.new(f"{name}_Pedestal_Mesh")
    bm_ped.to_mesh(m_ped)
    bm_ped.free()
    o_ped = bpy.data.objects.new(f"{name}_Sculpted_Pedestal", m_ped)
    o_ped.location = loc
    link_obj(o_ped, col)
    for p in m_ped.polygons:
        p.use_smooth = True
    sub = o_ped.modifiers.new("Subsurf", "SUBSURF")
    sub.levels = 2
    sub.render_levels = 2
    o_ped.data.materials.append(white_mat)
    o_ped["designer"] = "Poltrona Frau Infinito Collection"
    o_ped["dimensions_mm"] = "2200 x 1240 x 740"

    bm_top = build_single_tabletop_mesh(length=2.20, width=1.24, z_top=0.74, z_bot=0.69, z_chamfer=0.718)
    m_top = bpy.data.meshes.new(f"{name}_Tabletop_Mesh")
    bm_top.to_mesh(m_top)
    bm_top.free()
    o_top = bpy.data.objects.new(f"{name}_Marble_Tabletop", m_top)
    o_top.location = loc
    link_obj(o_top, col)
    for p in m_top.polygons:
        p.use_smooth = True
    bev = o_top.modifiers.new("Bevel", "BEVEL")
    bev.width = 0.003
    bev.segments = 3
    o_top.data.materials.append(white_mat)
    o_top["designer"] = "Poltrona Frau Infinito Collection"
    o_top["dimensions_mm"] = "2200 x 1240 x 740"



# ---------------------------------------------------------------------------
# Build the 4 Floors in Blender
# ---------------------------------------------------------------------------
def build_house_floors(msp, floor_offsets_xy=None, include_beams=True):
    if floor_offsets_xy is None:
        floor_offsets_xy = {k: (0.0, 0.0, 0.0) for k in ["B2_Base", "B1_Mezz", "1F_Plan", "2F_Plan"]}

    cols = {}

    # =========================================================================
    # FLOOR 1 & 2: B2_负二层 (z0 = -4.55m) & B1_负一层_夹层 (z0 = -2.40m)
    # Calibrated to match the Double-Height Basement Reference Rendering (media_1793051728146_c18c89c6.jpg):
    # - Glossy veined grey-white marble floor
    # - Double-height West sculpted white TV wall with flared bottom lip, "8:31 PM" screen & black marble linear fireplace
    # - West wall dark wood entry door
    # - Full-height white cylindrical structural column rising from B2 floor through B1 mezzanine to 1F ceiling beams
    # - B1 mezzanine with rounded white bullnose slab edge, frameless curved clear glass balustrade, circular LED cove ceiling, modern desk & lounge seating
    # - Under B1 mezzanine on B2 (rev. 2026-10-28): north-wall wine corner – grid wine rack niche + drawers, 3-bay backlit display wall (bar removed)
    # - East wall art/underwater lightwell windows & 3-wire sculptural ribbon chandelier in double-height void
    # - Sweeping S-Curve / Helical Staircase (B2 -> B1 -> 1F) with smooth white soffit, marble treads + LED strips,
    #   and ONE SIDE handrail in Frameless Clear Glass (外侧平白玻璃扶手) + ONE SIDE in Dark Bronze/Iron (内侧深色铁质扶手)!
    # =========================================================================
    col_b2 = bpy.data.collections.new("B2_负二层_地下室底层")
    bpy.context.scene.collection.children.link(col_b2)
    cols["B2_Base"] = col_b2
    p_b2 = PLANS["B2_Base"]
    z_b2, h_b2 = p_b2["z0"], p_b2["h"]
    zf_b2 = z_b2 + 0.005

    # UV-mapped grey-white fish-belly porcelain marble tile floor across B2 (aspect-preserving 1.6m x 1.6m 2x2 tiles)
    add_uv_front_box_mm("B2_Floor_Slab", -1622, 6802, -5690, 1660, z_b2 - 0.15, z_b2, 0.0, 8.424 / 1.6, 0.0, 7.350 / 1.6, MATS["B2_Marble_Floor"], col_b2)

    b2_cutouts = [
        (-1630, -1350, -1180, -320),  # West Dark Wood Door
        ( 3150,  6020, -2080, 1415),  # Open Mahjong / Bar area
    ]
    build_manifold_walls(msp, "B2_Base", p_b2["xr"], p_b2["yr"], *p_b2["orig"], z_b2 + 0.002, h_b2, b2_cutouts, col_b2)

    # Full-height Double-Height Perimeter Plaster Cladding (z: -4.55..0.00m) for clean interior walls
    plaster_mat = MATS["Basement_Warm_Plaster"]
    add_box_mm("B2_Wall_West_Full",  -1520, -1375, -5690,  1620, z_b2, 0.00, plaster_mat, col_b2)
    add_box_mm("B2_Wall_North_Full", -1520,  6450,  1410,  1620, z_b2, 0.00, plaster_mat, col_b2)
    # Pierced East wall (x: 6340..6600, 260mm deep reveal) + enclosed outer backing (6600..6640, recessed behind fish-pond tank!)
    # Opening 1 (Left / North Mezzanine Horizontal Window): y=-1150..+900 (W=2050mm), z=-1.16..-0.58m (H=580mm)
    # Opening 2 (Right / South Side Fish-Pond Window): SAME width 2050mm (y=-4375..-2325), +20cm taller H=780mm (z=-1.26..-0.48m)
    add_box_mm("B2_Wall_East_Lower",       6340, 6600, -5690,  1620, z_b2,  -1.26, plaster_mat, col_b2)
    add_box_mm("B2_Wall_East_Sill_North",  6340, 6600, -1590,  1620, -1.26, -1.16, plaster_mat, col_b2)
    add_box_mm("B2_Wall_East_Upper_North", 6340, 6600, -1590,  1620, -0.58,  0.00, plaster_mat, col_b2)
    add_box_mm("B2_Wall_East_Upper_South", 6340, 6600, -5690, -1590, -0.48,  0.00, plaster_mat, col_b2)
    add_box_mm("B2_Wall_East_Pier_North",  6340, 6600,   900,  1620, -1.16, -0.58, plaster_mat, col_b2)
    add_box_mm("B2_Wall_East_Pier_Mid_N",  6340, 6600, -1590, -1150, -1.16, -0.58, plaster_mat, col_b2)
    add_box_mm("B2_Wall_East_Pier_Mid_S",  6340, 6600, -2325, -1590, -1.26, -0.48, plaster_mat, col_b2)
    add_box_mm("B2_Wall_East_Pier_South",  6340, 6600, -5690, -4375, -1.26, -0.48, plaster_mat, col_b2)
    add_box_mm("B2_Wall_East_OuterBack_N", 6600, 6640, -2325,  1620, z_b2,   0.00, plaster_mat, col_b2)
    add_box_mm("B2_Wall_East_OuterBack_S", 6600, 6640, -5690, -4375, z_b2,   0.00, plaster_mat, col_b2)
    add_box_mm("B2_Wall_East_OuterBack_B", 6600, 6640, -4375, -2325, z_b2,  -1.26, plaster_mat, col_b2)
    add_box_mm("B2_Wall_East_OuterBack_T", 6600, 6640, -4375, -2325, -0.48,  0.00, plaster_mat, col_b2)

    def _add_hcyl_mm(hname, cx, y1, y2, cz, r, mat, segs=20):
        pts = [(r * math.cos(2 * math.pi * k / segs), r * math.sin(2 * math.pi * k / segs)) for k in range(segs)]
        o = add_prism(hname, pts, -(y2 - y1) * MM / 2.0, (y2 - y1) * MM / 2.0, mat, col_b2)
        if o is not None:
            o.rotation_euler = (math.radians(90.0), 0.0, 0.0)
            o.location = (cx * MM, (y1 + y2) * MM / 2.0, cz)
        return o

    def _add_xcyl_mm(xname, x1, x2, cy, cz, r, mat, segs=12):
        pts = [(r * math.cos(2 * math.pi * k / segs), r * math.sin(2 * math.pi * k / segs)) for k in range(segs)]
        o = add_prism(xname, pts, -(x2 - x1) * MM / 2.0, (x2 - x1) * MM / 2.0, mat, col_b2)
        if o is not None:
            o.rotation_euler = (0.0, math.radians(90.0), 0.0)
            o.location = ((x1 + x2) * MM / 2.0, cy * MM, cz)
        return o

    # 1. West Wall Dark Wood Door (x: -1380..-1320, y: -1150..-350, z: -4.55..-2.35m)
    add_box_mm("B2_West_DarkDoor_Frame", -1385, -1325, -1180, -320, zf_b2, z_b2 + 2.18, MATS["OLO_ToeKick_Black"], col_b2)
    add_box_mm("B2_West_DarkDoor_Leaf",  -1378, -1338, -1140, -360, zf_b2, z_b2 + 2.14, MATS["OLO_Niche_Frame"], col_b2)
    add_box_mm("B2_West_DarkDoor_Handle",-1338, -1318, -1080, -1050, z_b2 + 1.02, z_b2 + 1.05, MATS["Gold_Brass"], col_b2)

    # 1b. B2 Entrance Right Recessed Niche Shoe Cabinet & Luxury Stone Pedestal with Dripping Figurine (matching media_1793052808781_e2ecafeb.jpg)
    add_box_mm("B2_Entry_Niche_Back", -1375, -1355, -280, 1180, zf_b2, z_b2 + 2.42, MATS["Basement_Warm_Plaster"], col_b2)
    add_box_mm("B2_Entry_Niche_Head", -1375, -1020, -280, 1180, z_b2 + 2.40, z_b2 + 2.45, MATS["Basement_Warm_Plaster"], col_b2)
    # Luxury Marble Pedestal on the left (x: -1340..-1060, y: -250..+50, H: 850mm)
    add_box_mm("B2_Entry_Pedestal", -1340, -1060, -250, 50, zf_b2, z_b2 + 0.85, MATS["B2_Pedestal_Marble"], col_b2)
    # Contemporary Chinese Sculpted Stone Lion on Pedestal (当代中式石狮子摆件)
    _lion_mat = MATS["StoneLion_Grey"]
    add_box_mm("B2_Entry_StoneLion_Plinth1", -1290, -1110, -195, -5, z_b2 + 0.850, z_b2 + 0.895, _lion_mat, col_b2, r_corner=12.0)
    add_box_mm("B2_Entry_StoneLion_Plinth2", -1272, -1128, -178, -22, z_b2 + 0.895, z_b2 + 0.925, _lion_mat, col_b2, r_corner=8.0)
    # Seated haunches, arched chest, front pillar legs & paws
    add_box_mm("B2_Entry_StoneLion_Haunch", -1262, -1158, -158, -42, z_b2 + 0.925, z_b2 + 1.045, _lion_mat, col_b2, r_corner=26.0)
    add_box_mm("B2_Entry_StoneLion_Chest",  -1220, -1134, -148, -52, z_b2 + 0.960, z_b2 + 1.135, _lion_mat, col_b2, r_corner=28.0)
    add_cyl_mm("B2_Entry_StoneLion_LegL", -1148, -138, 17.0, z_b2 + 0.925, z_b2 + 1.075, _lion_mat, col_b2, segs=16)
    add_cyl_mm("B2_Entry_StoneLion_LegR", -1148, -62,  17.0, z_b2 + 0.925, z_b2 + 1.075, _lion_mat, col_b2, segs=16)
    add_box_mm("B2_Entry_StoneLion_Collar", -1210, -1136, -138, -62, z_b2 + 1.115, z_b2 + 1.142, MATS["Gold_Brass"], col_b2, r_corner=10.0)
    # Sculpted head, mane crown, ears & snout facing East (+X)
    add_box_mm("B2_Entry_StoneLion_Head",   -1215, -1128, -142, -58, z_b2 + 1.135, z_b2 + 1.245, _lion_mat, col_b2, r_corner=26.0)
    add_box_mm("B2_Entry_StoneLion_Snout",  -1142, -1106, -124, -76, z_b2 + 1.145, z_b2 + 1.198, _lion_mat, col_b2, r_corner=14.0)
    add_box_mm("B2_Entry_StoneLion_EarL",   -1195, -1168, -148, -126, z_b2 + 1.235, z_b2 + 1.272, _lion_mat, col_b2, r_corner=6.0)
    add_box_mm("B2_Entry_StoneLion_EarR",   -1195, -1168,  -74,  -52, z_b2 + 1.235, z_b2 + 1.272, _lion_mat, col_b2, r_corner=6.0)
    add_box_mm("B2_Entry_StoneLion_Tail",   -1276, -1248, -116,  -84, z_b2 + 0.945, z_b2 + 1.120, _lion_mat, col_b2, r_corner=10.0)
    # Floating Double-Door Shoe Cabinet lowered by half (0.175m off B2 floor) with higher horizontal LED forming a Cross (十字架)
    add_box_mm("B2_Entry_Cab_Halo",         -1355, -1345, 110, 1150, z_b2 + 0.155, z_b2 + 2.105, MATS["Warm_LED_Glow"], col_b2)
    add_box_mm("B2_Entry_Cab_Carcass",      -1345, -1045, 120, 1140, z_b2 + 0.175, z_b2 + 2.075, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_Entry_Cab_DoorL_Bot",    -1345, -1025, 130, 620, z_b2 + 0.180, z_b2 + 1.380, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_Entry_Cab_DoorL_Top",    -1345, -1025, 130, 620, z_b2 + 1.405, z_b2 + 2.070, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_Entry_Cab_LEDChannel",   -1042, -1028, 620, 645, z_b2 + 0.180, z_b2 + 2.070, MATS["Warm_LED_Glow"], col_b2)
    add_box_mm("B2_Entry_Cab_LEDChannel_H", -1042, -1028, 130, 1130, z_b2 + 1.380, z_b2 + 1.405, MATS["Warm_LED_Glow"], col_b2)
    add_box_mm("B2_Entry_Cab_DoorR_Bot",    -1345, -1025, 645, 1130, z_b2 + 0.180, z_b2 + 1.380, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_Entry_Cab_DoorR_Top",    -1345, -1025, 645, 1130, z_b2 + 1.405, z_b2 + 2.070, MATS["OLO_Cab_White"], col_b2)

    # 2. Double-Height West Wall Sculpted TV Feature Wall (15cm proud body + hollow straight-out flared bottom lip + splayed sides + water-ripple shimmer + level 80" TV)
    def build_b2_sculpted_tv_wall(wname, y_start, y_end, col):
        n_y = 48
        n_arc = 18
        shell_t = 28.0  # 28mm hollow shell thickness (底部弯出部分里面是空心的)
        x_back = -1375.0
        x_front = -1225.0  # 150mm (15cm) proud of -1375mm West wall
        x_hem_lip = -1045.0  # straight forward-curving bottom lip
        z_hem = -4.02
        z_arc_top = -3.52
        z_wall_top = -0.16

        # Build front/outer shell + inner hollow cavity surface cleanly as a continuous closed cross-section ring
        rings = []
        for iy in range(n_y + 1):
            u_y = iy / float(n_y)
            y_base = y_start + u_y * (y_end - y_start)
            side_sign = 2.0 * u_y - 1.0
            # Outer profile: starts at back wall upper, runs down 15cm proud face, curves straight forward to hollow bottom lip, returns inside (hollow!)
            pts_outer = [
                (x_back, y_base, z_wall_top),
                (x_front, y_base, z_wall_top),
                (x_front, y_base, z_arc_top),
            ]
            for i in range(1, n_arc + 1):
                s = i / float(n_arc)
                ang = math.radians(180.0 + 90.0 * s)  # 180 -> 270 deg: smooth concave sweep out to x_hem_lip
                px = x_hem_lip + (x_front - x_hem_lip) * (1.0 - math.sin(0.5 * math.pi * s))
                pz = z_arc_top + (z_hem - z_arc_top) * math.sin(0.5 * math.pi * s)
                flare = (s ** 1.35)
                py = y_base + side_sign * 115.0 * flare  # sides slowly splay outward
                pts_outer.append((px, py, pz))
            # Lip thickness + hollow underside return back toward wall (leaving underside genuinely hollow!)
            y_lip = y_base + side_sign * 115.0
            pts_outer.append((x_hem_lip, y_lip, z_hem - shell_t * MM))
            for i in range(n_arc - 1, 0, -1):
                s = i / float(n_arc)
                px = x_hem_lip + (x_front - x_hem_lip) * (1.0 - math.sin(0.5 * math.pi * s))
                pz = z_arc_top + (z_hem - z_arc_top) * math.sin(0.5 * math.pi * s) - shell_t * MM
                flare = (s ** 1.35)
                py = y_base + side_sign * 115.0 * flare
                pts_outer.append((px, py, pz))
            pts_outer.append((x_back, y_base, z_arc_top - shell_t * MM))
            rings.append(pts_outer)

        mesh = bpy.data.meshes.new(wname)
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.verify()
        bm_rings = [[bm.verts.new((px * MM, py * MM, pz)) for (px, py, pz) in r] for r in rings]
        n_p = len(rings[0])
        for iy in range(n_y):
            r0, r1 = bm_rings[iy], bm_rings[iy + 1]
            for i in range(n_p):
                ni = (i + 1) % n_p
                fc = bm.faces.new([r0[i], r0[ni], r1[ni], r1[i]])
                fc.smooth = (2 <= i <= n_p - 3)
                for lp in fc.loops:
                    lp[uv_layer].uv = (lp.vert.co.y / 1.4, lp.vert.co.z / 1.4)
        for end_face in (bm_rings[0][::-1], bm_rings[-1]):
            fe = bm.faces.new(end_face)
            for lp in fe.loops:
                lp[uv_layer].uv = (lp.vert.co.x / 1.4, lp.vert.co.z / 1.4)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(wname, mesh)
        obj.data.materials.append(MATS["B2_TV_WaterRipple"])
        link_obj(obj, col)
        return obj

    build_b2_sculpted_tv_wall("B2_TV_Wall_Sculpted", -4680.0, -1850.0, col_b2)
    # Overhead Water-Ripple Light Fixture casting sparkling water-light down the TV wall
    add_box_mm("B2_TV_WaterLight_Housing", -1255.0, -1155.0, -4450.0, -2080.0, -0.260, -0.160, MATS["OLO_ToeKick_Black"], col_b2)
    add_box_mm("B2_TV_WaterLight_Glow",    -1240.0, -1170.0, -4420.0, -2110.0, -0.268, -0.258, MATS["B2_CoolWhite_LED"], col_b2)
    add_box_mm("B2_TV_Wall_UnderLED", -1120.0, -1085.0, -4580.0, -1950.0, -4.048, -4.032, MATS["Warm_LED_Glow"], col_b2)
    # Horizontal 80-inch 16:9 TV Frame flush to 15cm proud TV wall (x = -1225..-1204)
    add_box_mm("B2_TV_Frame_Top", -1226, -1204, -4159, -2371, -2.378, -2.366, MATS["Toshiba_Obsidian_Trim"], col_b2)
    add_box_mm("B2_TV_Frame_Bot", -1226, -1204, -4159, -2371, -3.380, -3.368, MATS["Toshiba_Obsidian_Trim"], col_b2)
    add_box_mm("B2_TV_Frame_S",   -1226, -1204, -4159, -4147, -3.368, -2.378, MATS["Toshiba_Obsidian_Trim"], col_b2)
    add_box_mm("B2_TV_Frame_N",   -1226, -1204, -2383, -2371, -3.368, -2.378, MATS["Toshiba_Obsidian_Trim"], col_b2)
    add_uv_side_box_mm(
        "B2_TV_Screen_831",
        -1225, -1209, -4147, -2383, -3.368, -2.378,
        0.0, 1.0, 0.0, 1.0,
        MATS["B2_TV_Screen"], col_b2
    )
    add_box_mm("B2_TV_Groove_L", -1228, -1220, -4159, -4145, -2.366, -0.95, MATS["Stair_Bronze_Iron"], col_b2)
    add_box_mm("B2_TV_Groove_R", -1228, -1220, -2385, -2371, -2.366, -0.95, MATS["Stair_Bronze_Iron"], col_b2)
    add_box_mm("B2_Fireplace_Hearth", -1375, -780, -4680, -1850, zf_b2, z_b2 + 0.23, MATS["OLO_Black_Backsplash"], col_b2)
    add_box_mm("B2_Fireplace_Trough", -1160, -960, -3950, -2550, z_b2 + 0.21, z_b2 + 0.235, MATS["OLO_ToeKick_Black"], col_b2)
    add_box_mm("B2_Fireplace_Flame",  -1110, -1010, -3880, -2620, z_b2 + 0.232, z_b2 + 0.42, MATS["Fireplace_Glow"], col_b2)

    add_cyl_mm("B2_B1_Main_Column", 4680.0, -1420.0, 240.0, zf_b2, 0.00, plaster_mat, col_b2, segs=48)

    # 2b. B2 Lounge: Sweeping Curved Crescent Modular Sofa + Rear Console + Separated Round Marble Coffee Table (rev. 2026-11-05)
    # Strictly matching user reference photo media_1793053080597_aa27f308.jpg & user feedback:
    # - True sweeping crescent/C-arc velvet sofa facing West/Northwest towards the "8:31 PM" TV wall & fireplace
    # - Positioned at (cx=1050, cy=-3180) with outer radius 1600mm (console 1840mm) and ang=-48..+18 deg
    #   so the South end stays at y >= -4411mm (>1.02m North of B2_Wall_South_Full at y=-5430mm — completely clear of the South wall even under steep top-down perspective!)
    # - 5 segmented curved plush seat cushions with tufted channel seams
    # - Continuous curved wrap-around backrest + 5 curved back cushions + cylindrical bolster pillows
    # - Curved dark charcoal console table hugging the outer back of the sofa
    # - Round marble coffee table positioned near center of curvature with >380mm clear space from sofa (ZERO overlap/fusion!)
    # - North end terminates at y = -2685mm, leaving >1.10m wide open walkway to Grand Stair entrance
    pts_b2_rug = []
    for k in range(48):
        ang = 2.0 * math.pi * k / 48.0
        pts_b2_rug.append((1320.0 + 1350.0 * math.cos(ang), -3250.0 + 1120.0 * math.sin(ang)))
    add_prism("B2_Sofa_Rug", pts_b2_rug, z_b2 + 0.002, z_b2 + 0.010, MATS["Rug_Warm"], col_b2)

    sofa_mat = MATS["Sofa_Sage_Velvet"]
    cx_sf, cy_sf = 1050.0, -3180.0
    r_seat_in  =  820.0
    r_seat_out = 1480.0
    r_back_in  = 1390.0
    r_back_out = 1600.0
    ang_sf_start = -48.0
    ang_sf_end   =  18.0
    n_modules = 5
    span_deg = (ang_sf_end - ang_sf_start) / float(n_modules)

    # 1) Recessed dark plinth toe-kick under the curved sofa
    pts_sf_plinth = arc_band_poly(cx_sf, cy_sf, r_seat_in + 45.0, cx_sf, cy_sf, r_back_out - 35.0, ang_sf_start + 1.5, ang_sf_end - 1.5, n=44)
    add_prism("B2_CurvedSofa_Plinth", pts_sf_plinth, zf_b2, z_b2 + 0.045, MATS["OLO_ToeKick_Black"], col_b2)

    # 2) 5 Segmented Curved Plush Seat Cushions with articulated tuft seams & rounded bullnose
    for m_i in range(n_modules):
        a1 = ang_sf_start + m_i * span_deg + 0.65
        a2 = ang_sf_start + (m_i + 1) * span_deg - 0.65
        pts_mod_base = arc_band_poly(cx_sf, cy_sf, r_seat_in + 12.0, cx_sf, cy_sf, r_seat_out, a1, a2, n=14)
        add_prism(f"B2_CurvedSofa_SeatBase_{m_i+1}", pts_mod_base, z_b2 + 0.045, z_b2 + 0.24, sofa_mat, col_b2)
        pts_mod_top = arc_band_poly(cx_sf, cy_sf, r_seat_in, cx_sf, cy_sf, r_seat_out - 10.0, a1 + 0.3, a2 - 0.3, n=14)
        add_prism(f"B2_CurvedSofa_SeatTop_{m_i+1}", pts_mod_top, z_b2 + 0.24, z_b2 + 0.405, sofa_mat, col_b2)
        pts_mod_crown = arc_band_poly(cx_sf, cy_sf, r_seat_in + 28.0, cx_sf, cy_sf, r_seat_out - 45.0, a1 + 1.1, a2 - 1.1, n=12)
        add_prism(f"B2_CurvedSofa_SeatCrown_{m_i+1}", pts_mod_crown, z_b2 + 0.405, z_b2 + 0.428, sofa_mat, col_b2)

        # Curved plush back cushion for each module
        pts_bcush = arc_band_poly(cx_sf, cy_sf, r_back_in - 115.0, cx_sf, cy_sf, r_back_in + 10.0, a1 + 0.9, a2 - 0.9, n=12)
        add_prism(f"B2_CurvedSofa_BackCush_{m_i+1}", pts_bcush, z_b2 + 0.405, z_b2 + 0.735, sofa_mat, col_b2)

    # 3) Continuous Sweeping Curved Outer Backrest Shell
    pts_back_shell = arc_band_poly(cx_sf, cy_sf, r_back_in, cx_sf, cy_sf, r_back_out, ang_sf_start - 1.0, ang_sf_end + 1.0, n=56)
    add_prism("B2_CurvedSofa_BackShell", pts_back_shell, z_b2 + 0.045, z_b2 + 0.765, sofa_mat, col_b2)
    pts_back_crown = arc_band_poly(cx_sf, cy_sf, r_back_in + 20.0, cx_sf, cy_sf, r_back_out - 20.0, ang_sf_start - 0.5, ang_sf_end + 0.5, n=56)
    add_prism("B2_CurvedSofa_BackCrown", pts_back_crown, z_b2 + 0.765, z_b2 + 0.790, sofa_mat, col_b2)

    # Rounded end armrests at South-West tip (ang_sf_start) and North-East tip (ang_sf_end)
    for end_idx, end_ang in enumerate([ang_sf_start, ang_sf_end]):
        er_rad = math.radians(end_ang)
        r_mid = 0.5 * (r_seat_in + r_back_out)
        r_rad = 0.5 * (r_back_out - r_seat_in)
        ecx = cx_sf + r_mid * math.cos(er_rad)
        ecy = cy_sf + r_mid * math.sin(er_rad)
        add_cyl_mm(f"B2_CurvedSofa_EndCap_{end_idx+1}", ecx, ecy, r_rad * 0.48, z_b2 + 0.045, z_b2 + 0.62, sofa_mat, col_b2, segs=24)

    # 4) Accent Pillows & Bolsters along the inner curve (matching reference photo)
    for p_idx, (p_ang, p_mat_key) in enumerate([(-38.0, "Cabinet_Cream"), (-21.0, "Sofa_Sage_Velvet"), (-5.0, "Cabinet_Cream"), (10.0, "Cabinet_Cream")]):
        pr = math.radians(p_ang)
        px = cx_sf + (r_back_in - 165.0) * math.cos(pr)
        py = cy_sf + (r_back_in - 165.0) * math.sin(pr)
        add_cyl_mm(f"B2_CurvedSofa_Pillow_{p_idx+1}", px, py, 92.0, z_b2 + 0.41, z_b2 + 0.66, MATS[p_mat_key], col_b2, segs=24)

    # 5) Curved Dark Console Table Hugging Behind the Sofa Backrest (signature detail in media_1793053080597_aa27f308.jpg)
    r_cons_in  = r_back_out + 15.0   # 1615mm
    r_cons_out = r_back_out + 240.0  # 1840mm
    pts_cons_top = arc_band_poly(cx_sf, cy_sf, r_cons_in, cx_sf, cy_sf, r_cons_out, -40.0, 14.0, n=40)
    add_prism("B2_CurvedSofa_RearConsole_Top", pts_cons_top, z_b2 + 0.60, z_b2 + 0.65, MATS["Cabinet_Charcoal"], col_b2)
    for leg_ang in [-36.0, -12.0, 10.0]:
        pts_cleg = arc_band_poly(cx_sf, cy_sf, r_cons_in + 20.0, cx_sf, cy_sf, r_cons_out - 20.0, leg_ang - 2.5, leg_ang + 2.5, n=6)
        add_prism(f"B2_CurvedSofa_RearConsole_Leg_{int(leg_ang+90)}", pts_cleg, zf_b2, z_b2 + 0.60, MATS["Cabinet_Charcoal"], col_b2)

    # 6) Round Pale-Marble Coffee Table in the center of the crescent (>380mm clear floor gap to sofa!)
    # Sofa inner edge is at R = 820mm from (1050, -3180); Coffee Table at (960, -3180) with radius 350mm stays within R <= 440mm!
    add_cyl_mm("B2_Coffee_Table_Top", 960.0, -3180.0, 350.0, z_b2 + 0.31, z_b2 + 0.36, MATS["Coffee_Pale_Marble"], col_b2, segs=48)
    add_cyl_mm("B2_Coffee_Table_Base", 960.0, -3180.0, 220.0, zf_b2, z_b2 + 0.31, MATS["Cabinet_Charcoal"], col_b2, segs=36)
    add_cyl_mm("B2_Coffee_Table_Tray", 960.0, -3180.0, 115.0, z_b2 + 0.36, z_b2 + 0.385, MATS["Gold_Brass"], col_b2, segs=32)

    # Sculptural Organic Side Tables beside the sofa ends (100% inside room, >1.1m North of South wall)
    add_cyl_mm("B2_Side_Table_1", 2220.0, -2360.0, 175.0, zf_b2, z_b2 + 0.46, MATS["SideTable_Green_Marble"], col_b2, segs=32)
    add_cyl_mm("B2_Side_Table_2", 1480.0, -4220.0, 160.0, zf_b2, z_b2 + 0.42, MATS["Coffee_Pale_Marble"], col_b2, segs=32)

    # 2c. B2 Contemporary Automatic Mahjong Suite (moved to former SE Tea position) & Open-Zone Home Gym Equipment
    # Mahjong Table (960 x 960 x 760mm centered at x=5420, y=-3350) + 4 Upholstered Chairs
    add_box_mm("B2_Mahjong_Pedestal",   5190, 5650, -3580, -3120, zf_b2, z_b2 + 0.690, MATS["Cabinet_Charcoal"], col_b2, r_corner=60.0)
    add_box_mm("B2_Mahjong_BaseGold",   5180, 5660, -3590, -3110, zf_b2, z_b2 + 0.025, MATS["Gold_Brass"], col_b2, r_corner=62.0)
    add_box_mm("B2_Mahjong_Table_Frame",4940, 5900, -3830, -2870, z_b2 + 0.690, z_b2 + 0.760, MATS["Cabinet_Charcoal"], col_b2, r_corner=80.0)
    add_box_mm("B2_Mahjong_Table_Rim",  4945, 5895, -3825, -2875, z_b2 + 0.754, z_b2 + 0.764, MATS["Gold_Brass"], col_b2, r_corner=78.0)
    add_box_mm("B2_Mahjong_Table_Felt", 5010, 5830, -3760, -2940, z_b2 + 0.758, z_b2 + 0.768, MATS["SideTable_Green_Marble"], col_b2, r_corner=24.0)

    def add_mahjong_chair(cname, cx, cy, facing_deg):
        add_cyl_mm(f"{cname}_SeatBase", cx, cy, 230.0, z_b2 + 0.40, z_b2 + 0.44, MATS["Cabinet_Charcoal"], col_b2, segs=28)
        add_cyl_mm(f"{cname}_SeatPad",  cx, cy, 222.0, z_b2 + 0.44, z_b2 + 0.49, MATS["Cabinet_Cream"], col_b2, segs=28)
        back_center_deg = facing_deg + 180.0
        pts_shell = arc_band_poly(cx, cy, 195.0, cx, cy, 250.0, back_center_deg - 90.0, back_center_deg + 90.0, n=20)
        add_prism(f"{cname}_BackShell", pts_shell, z_b2 + 0.44, z_b2 + 0.77, MATS["OLO_Cab_Greige"], col_b2)
        for l_i, l_ang in enumerate([45.0, 135.0, 225.0, 315.0]):
            lr = math.radians(facing_deg + l_ang)
            lx = cx + 185.0 * math.cos(lr)
            ly = cy + 185.0 * math.sin(lr)
            add_cyl_mm(f"{cname}_Leg_{l_i+1}", lx, ly, 11.0, z_b2 + 0.05, z_b2 + 0.40, MATS["OLO_ToeKick_Black"], col_b2, segs=12)
            add_cyl_mm(f"{cname}_Foot_{l_i+1}", lx, ly, 10.0, zf_b2, z_b2 + 0.05, MATS["Gold_Brass"], col_b2, segs=12)

    add_mahjong_chair("B2_Mahjong_Chair_E", 6140.0, -3350.0, 180.0)
    add_mahjong_chair("B2_Mahjong_Chair_W", 4700.0, -3350.0,   0.0)
    add_mahjong_chair("B2_Mahjong_Chair_N", 5420.0, -2630.0, -90.0)
    add_mahjong_chair("B2_Mahjong_Chair_S", 5420.0, -4070.0,  90.0)

    # Home Gym / Fitness Zone: Single Sculpted Red Spin Exercise Bike on Dark Mat (x: 3420..4280, y: -1020..+320)
    add_box_mm("B2_Gym_Mat", 3420, 4280, -1020, 320, zf_b2, z_b2 + 0.014, MATS["Cabinet_Charcoal"], col_b2, r_corner=40.0)

    def _add_bike_yz_part_mm(pname, x1, x2, yz_pts_mm, mat):
        mesh_p = bpy.data.meshes.new(pname)
        bm_p = bmesh.new()
        x0, x1m = x1 * MM, x2 * MM
        v_bot = [bm_p.verts.new((x0, py * MM, z_b2 + pz * MM)) for (py, pz) in yz_pts_mm]
        v_top = [bm_p.verts.new((x1m, py * MM, z_b2 + pz * MM)) for (py, pz) in yz_pts_mm]
        bm_p.faces.new(list(reversed(v_bot)))
        bm_p.faces.new(v_top)
        np_c = len(yz_pts_mm)
        for k in range(np_c):
            nk = (k + 1) % np_c
            bm_p.faces.new([v_bot[k], v_bot[nk], v_top[nk], v_top[k]])
        bmesh.ops.recalc_face_normals(bm_p, faces=bm_p.faces[:])
        bm_p.to_mesh(mesh_p)
        bm_p.free()
        obj_p = bpy.data.objects.new(pname, mesh_p)
        obj_p.data.materials.append(mat)
        link_obj(obj_p, col_b2)
        return obj_p

    # Front & rear floor stabilizer bars + rubber end-caps
    add_box_mm("B2_Gym_RedBike_FootF", 3580, 4120, -850, -790, z_b2 + 0.014, z_b2 + 0.068, MATS["Cabinet_Charcoal"], col_b2, r_corner=16.0)
    add_box_mm("B2_Gym_RedBike_FootR", 3580, 4120,  100,  160, z_b2 + 0.014, z_b2 + 0.068, MATS["Cabinet_Charcoal"], col_b2, r_corner=16.0)
    # Glossy Crimson-Red Spin Bike Frame (Spine + Sloped Front Head Post + Seat Tube + Upper Strut)
    add_box_mm("B2_Gym_RedBike_Spine", 3822, 3878, -800, 110, z_b2 + 0.055, z_b2 + 0.135, MATS["Gym_Bike_Red"], col_b2, r_corner=12.0)
    _add_bike_yz_part_mm("B2_Gym_RedBike_FrontPost", 3824, 3876, [(-540, 130), (-475, 130), (-675, 720), (-725, 720)], MATS["Gym_Bike_Red"])
    _add_bike_yz_part_mm("B2_Gym_RedBike_RearPost",  3824, 3876, [(-275, 130), (-210, 130), (-45, 665), (-95, 665)], MATS["Gym_Bike_Red"])
    _add_bike_yz_part_mm("B2_Gym_RedBike_TopBar",    3826, 3874, [(-685, 595), (-90, 540), (-75, 595), (-695, 650)], MATS["Gym_Bike_Red"])
    # Upright Front Flywheel (Chrome disc + Crimson rim + Curved Red Fender Guard)
    _fw_rim = [( -680.0 + 220.0 * math.cos(2 * math.pi * k / 28), 420.0 + 220.0 * math.sin(2 * math.pi * k / 28)) for k in range(28)]
    _fw_dsc = [( -680.0 + 198.0 * math.cos(2 * math.pi * k / 28), 420.0 + 198.0 * math.sin(2 * math.pi * k / 28)) for k in range(28)]
    _add_bike_yz_part_mm("B2_Gym_RedBike_FlywheelRim", 3832, 3868, _fw_rim, MATS["Gym_Bike_Red"])
    _add_bike_yz_part_mm("B2_Gym_RedBike_Flywheel",    3828, 3872, _fw_dsc, MATS["B2_Chrome_Silver"])
    add_box_mm("B2_Gym_RedBike_Guard", 3816, 3884, -850, -520, z_b2 + 0.620, z_b2 + 0.675, MATS["Gym_Bike_Red"], col_b2, r_corner=18.0)
    # Chrome Crank Hub, Crank Arms, & Pedals
    _cr_hub = [(-300.0 + 95.0 * math.cos(2 * math.pi * k / 20), 330.0 + 95.0 * math.sin(2 * math.pi * k / 20)) for k in range(20)]
    _add_bike_yz_part_mm("B2_Gym_RedBike_CrankHub", 3802, 3898, _cr_hub, MATS["B2_Chrome_Silver"])
    add_box_mm("B2_Gym_RedBike_PedalL", 3710, 3800, -355, -245, z_b2 + 0.305, z_b2 + 0.335, MATS["Cabinet_Charcoal"], col_b2, r_corner=8.0)
    add_box_mm("B2_Gym_RedBike_PedalR", 3900, 3990, -355, -245, z_b2 + 0.305, z_b2 + 0.335, MATS["Cabinet_Charcoal"], col_b2, r_corner=8.0)
    # Chrome Seat Post & Ergonomic Black Saddle
    add_box_mm("B2_Gym_RedBike_SeatPost", 3834, 3866, -92, -52, z_b2 + 0.640, z_b2 + 0.920, MATS["B2_Chrome_Silver"], col_b2, r_corner=8.0)
    add_box_mm("B2_Gym_RedBike_Saddle",   3765, 3935, -155, 55, z_b2 + 0.920, z_b2 + 0.985, MATS["Cabinet_Charcoal"], col_b2, r_corner=32.0)
    # Chrome Stem, Racing Bullhorn Handlebars + Red Grips + Dark LCD Console
    add_box_mm("B2_Gym_RedBike_Stem",      3832, 3868, -718, -678, z_b2 + 0.700, z_b2 + 1.020, MATS["B2_Chrome_Silver"], col_b2, r_corner=8.0)
    add_box_mm("B2_Gym_RedBike_HandleBar", 3650, 4050, -760, -680, z_b2 + 1.015, z_b2 + 1.058, MATS["Cabinet_Charcoal"], col_b2, r_corner=16.0)
    add_box_mm("B2_Gym_RedBike_GripL",     3625, 3675, -795, -675, z_b2 + 1.015, z_b2 + 1.062, MATS["Gym_Bike_Red"], col_b2, r_corner=12.0)
    add_box_mm("B2_Gym_RedBike_GripR",     4025, 4075, -795, -675, z_b2 + 1.015, z_b2 + 1.062, MATS["Gym_Bike_Red"], col_b2, r_corner=12.0)
    add_box_mm("B2_Gym_RedBike_Console",   3780, 3920, -775, -685, z_b2 + 1.062, z_b2 + 1.160, MATS["OLO_Oven_DarkGlass"], col_b2, r_corner=18.0)

    # B2 wine corner (rev. 2026-10-28): north-wall niche block with grid wine rack + 2 drawers (x 5040..6340, in the NE corner beside the display wall)
    # and a 3-bay backlit display wall with rounded bronze-ringed pilasters on the east wall (y 915..-1590). Generated by b2_wine_spec.py.
    def _add_hcyl_mm(hname, cx, y1, y2, cz, r, mat, segs=20):
        pts = [(r * math.cos(2 * math.pi * k / segs), r * math.sin(2 * math.pi * k / segs)) for k in range(segs)]
        o = add_prism(hname, pts, -(y2 - y1) * MM / 2.0, (y2 - y1) * MM / 2.0, mat, col_b2)
        if o is not None:
            o.rotation_euler = (math.radians(90.0), 0.0, 0.0)
            o.location = (cx * MM, (y1 + y2) * MM / 2.0, cz)
        return o

    def _add_xcyl_mm(xname, x1, x2, cy, cz, r, mat, segs=12):
        pts = [(r * math.cos(2 * math.pi * k / segs), r * math.sin(2 * math.pi * k / segs)) for k in range(segs)]
        o = add_prism(xname, pts, -(x2 - x1) * MM / 2.0, (x2 - x1) * MM / 2.0, mat, col_b2)
        if o is not None:
            o.rotation_euler = (0.0, math.radians(90.0), 0.0)
            o.location = ((x1 + x2) * MM / 2.0, cy * MM, cz)
        return o
    # B2 North wall beside 1400mm AluWineRack: 4 Equal Flush 600mm Mirror Doors (x: 2175..4575 = 2400mm wide)
    add_box_mm("B2_Mirror_Carcass_Wall", 2175.0, 4575.0, 1002.0, 1410.0, -4.5350, -2.5900, MATS["Cabinet_Charcoal"], col_b2)
    add_box_mm("B2_Mirror_Plinth_ToeKick", 2175.0, 4575.0, 998.0, 1030.0, -4.5450, -4.5250, MATS["OLO_ToeKick_Black"], col_b2)
    add_box_mm("B2_Mirror_Niche_Head", 2140.0, 4575.0, 960.0, 1410.0, -2.5900, -2.5600, plaster_mat, col_b2)
    add_box_mm("B2_Mirror_Niche_SideL", 2140.0, 2175.0, 960.0, 1410.0, -4.5450, -2.5600, plaster_mat, col_b2)
    add_box_mm("B2_Mirror_Perimeter_LED", 2175.0, 4575.0, 968.0, 982.0, -2.5980, -2.5900, MATS["B2_CoolWhite_LED"], col_b2)
    m_doors_w = (4575.0 - 2175.0) / 4.0  # Exact 600.0mm per door
    for md_i in range(4):
        md_x1 = 2175.0 + md_i * m_doors_w + 1.5
        md_x2 = 2175.0 + (md_i + 1) * m_doors_w - 1.5
        add_box_mm(f"B2_Mirror_Door_Panel_{md_i+1}", md_x1, md_x2, 978.0, 1000.0, -4.5240, -2.5920, MATS["Mirror_Silver"], col_b2)
        if md_i in (0, 2):
            add_box_mm(f"B2_Mirror_Door_EdgePull_{md_i+1}", md_x2 - 8.0, md_x2 - 1.0, 968.0, 978.0, -3.6200, -3.3800, MATS["Cabinet_Charcoal"], col_b2)

    # B2 North-Wall Wine Rack Cabinet strictly matching CAD 置信地下室高柜酒柜.dwg:
    # Exact 1400mm wide (x: 4575..5975) x 2000mm tall (z: -4.550..-2.550) x 434mm deep (y: 976..1410), L-joining East Wine Wall at (5975, 976):
    #   - Bottom 0..700mm (-4.550..-3.850): 2 cols x 2 stacked drawers = 4 drawers (697 x 342 mm each, 40mm recessed plinth)
    #   - Middle 700..1700mm (-3.850..-2.850): exact 1000mm tall open brushed-aluminum tubular wine rack + backlit alabaster + twin glass doors
    #   - Top 1700..2000mm (-2.850..-2.550): exact 300mm tall full-width up-flip cabinet door (1396 x 295 mm)
    aw_x0, aw_x1 = 4575.0, 5975.0
    aw_xm = 0.5 * (aw_x0 + aw_x1)  # 5275.0 (700 + 700 mm exact)
    aw_z0 = -4.550
    add_box_mm("B2_AluWineRack_ToeKick", aw_x0, aw_x1, 1006.0, 1410.0, aw_z0, aw_z0 + 0.040, MATS["OLO_ToeKick_Black"], col_b2)
    add_box_mm("B2_AluWineRack_SideL", aw_x0, aw_x0 + 18.0, 998.0, 1410.0, aw_z0 + 0.040, aw_z0 + 2.000, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_AluWineRack_SideR", aw_x1 - 18.0, aw_x1, 998.0, 1410.0, aw_z0 + 0.040, aw_z0 + 2.000, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_AluWineRack_BotPlate", aw_x0 + 18.0, aw_x1 - 18.0, 998.0, 1410.0, aw_z0 + 0.040, aw_z0 + 0.058, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_AluWineRack_LowDivC", aw_xm - 18.0, aw_xm + 18.0, 998.0, 1410.0, aw_z0 + 0.058, aw_z0 + 0.700, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_AluWineRack_MidShelf", aw_x0 + 18.0, aw_x1 - 18.0, 998.0, 1410.0, aw_z0 + 0.682, aw_z0 + 0.700, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_AluWineRack_LowBody", aw_x0 + 18.0, aw_x1 - 18.0, 1004.0, 1410.0, aw_z0 + 0.058, aw_z0 + 0.682, MATS["OLO_Cab_White"], col_b2)
    # 4 Exact CAD Drawers (697 x 342 mm each: z_rel 12..354 & 356..698)
    for col_i, (dx0, dx1) in enumerate(((aw_x0 + 1.5, aw_xm - 1.5), (aw_xm + 1.5, aw_x1 - 1.5)), 1):
        add_box_mm(f"B2_AluWineRack_DrwBot_{col_i}", dx0, dx1, 976.0, 998.0, aw_z0 + 0.012, aw_z0 + 0.354, MATS["OLO_Cab_White"], col_b2)
        add_box_mm(f"B2_AluWineRack_DrwTop_{col_i}", dx0, dx1, 976.0, 998.0, aw_z0 + 0.356, aw_z0 + 0.698, MATS["OLO_Cab_White"], col_b2)
        # Subtle recessed finger reveal bar along top of each drawer
        add_box_mm(f"B2_AluWineRack_DrwPullB_{col_i}", dx0 + 180.0, dx1 - 180.0, 974.0, 982.0, aw_z0 + 0.344, aw_z0 + 0.354, MATS["B2_Chrome_Silver"], col_b2)
        add_box_mm(f"B2_AluWineRack_DrwPullT_{col_i}", dx0 + 180.0, dx1 - 180.0, 974.0, 982.0, aw_z0 + 0.688, aw_z0 + 0.698, MATS["B2_Chrome_Silver"], col_b2)
    # Top 300mm Flip-Up Cabinet (z_rel 1700..2000: 18mm bottom shelf + full-width 1396x295mm flip door)
    add_box_mm("B2_AluWineRack_TopShelf", aw_x0 + 18.0, aw_x1 - 18.0, 998.0, 1410.0, aw_z0 + 1.700, aw_z0 + 1.718, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_AluWineRack_TopBody", aw_x0 + 18.0, aw_x1 - 18.0, 1004.0, 1410.0, aw_z0 + 1.718, aw_z0 + 1.982, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_AluWineRack_Head", aw_x0, aw_x1, 998.0, 1410.0, aw_z0 + 1.982, aw_z0 + 2.000, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_AluWineRack_TopFlipDoor", aw_x0 + 2.0, aw_x1 - 2.0, 976.0, 998.0, aw_z0 + 1.700, aw_z0 + 1.995, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_AluWineRack_TopFlipSeam", aw_x0 + 2.0, aw_x1 - 2.0, 975.0, 996.0, aw_z0 + 1.696, aw_z0 + 1.700, MATS["Cabinet_Charcoal"], col_b2)
    # Middle 1000mm Aluminum-Tube Wine Rack Zone (z_rel 700..1700, x: 4593..5957)
    aw_in_x0, aw_in_x1 = aw_x0 + 18.0, aw_x1 - 18.0
    aw_in_z0, aw_in_z1 = aw_z0 + 0.700, aw_z0 + 1.700
    add_uv_front_box_mm("B2_AluWineRack_BackGlow", aw_in_x0, aw_in_x1, 1385.0, 1408.0, aw_in_z0, aw_in_z1, 0.0, 1.0, 0.0, 1.0, MATS["B2_Backlit_Alabaster"], col_b2)
    add_box_mm("B2_AluWineRack_TopLED", aw_in_x0 + 8.0, aw_in_x1 - 8.0, 1020.0, 1045.0, aw_in_z1 - 0.008, aw_in_z1, MATS["B2_CoolWhite_LED"], col_b2)
    n_aw_cols, n_aw_rows = 10, 8
    aw_cw = (aw_in_x1 - aw_in_x0) / float(n_aw_cols)
    aw_rh = (aw_in_z1 - aw_in_z0) / float(n_aw_rows)
    for ci in range(n_aw_cols + 1):
        cx = aw_in_x0 + ci * aw_cw
        add_cyl_mm(f"B2_AluWineRack_TubeVF_{ci}", cx, 1045.0, 6.0, aw_in_z0, aw_in_z1, MATS["B2_Chrome_Silver"], col_b2, segs=12)
        add_cyl_mm(f"B2_AluWineRack_TubeVB_{ci}", cx, 1355.0, 6.0, aw_in_z0, aw_in_z1, MATS["B2_Chrome_Silver"], col_b2, segs=12)
    for ri in range(n_aw_rows + 1):
        rz = aw_in_z0 + ri * aw_rh
        _add_xcyl_mm(f"B2_AluWineRack_TubeHF_{ri}", aw_in_x0, aw_in_x1, 1045.0, rz, 4.8, MATS["B2_Chrome_Silver"], segs=12)
        _add_xcyl_mm(f"B2_AluWineRack_TubeHB_{ri}", aw_in_x0, aw_in_x1, 1355.0, rz, 4.8, MATS["B2_Chrome_Silver"], segs=12)
    for ri in range(n_aw_rows):
        rz_rail = aw_in_z0 + ri * aw_rh + 0.014
        bz = aw_in_z0 + ri * aw_rh + 0.044
        for ci in range(n_aw_cols):
            bx = aw_in_x0 + (ci + 0.5) * aw_cw
            _add_hcyl_mm(f"B2_AluWineRack_CradleL_{ri}_{ci}", bx - 22.0, 1045.0, 1355.0, rz_rail, 4.2, MATS["B2_Chrome_Silver"], segs=10)
            _add_hcyl_mm(f"B2_AluWineRack_CradleR_{ri}_{ci}", bx + 22.0, 1045.0, 1355.0, rz_rail, 4.2, MATS["B2_Chrome_Silver"], segs=10)
            if (ri * 3 + ci * 5) % 9 < 4:
                bmat = MATS["Wine_Bottle_Red"] if (ri + ci) % 2 == 0 else MATS["Cabinet_Charcoal"]
                _add_hcyl_mm(f"B2_AluWineRack_BtlB_{ri}_{ci}", bx, 1085.0, 1340.0, bz, 29.0, bmat, segs=14)
                _add_hcyl_mm(f"B2_AluWineRack_BtlN_{ri}_{ci}", bx, 1030.0, 1085.0, bz, 10.5, bmat, segs=12)
    # Two slim aluminum-framed clear glass doors over the 1400x1000mm wine rack zone
    for di_w, (dx0, dx1, hx) in enumerate(((aw_x0 + 2.0, aw_xm - 2.0, aw_xm - 14.0), (aw_xm + 2.0, aw_x1 - 2.0, aw_xm + 14.0))):
        add_box_mm(f"B2_AluWineRack_DoorFrameL_{di_w}", dx0, dx0 + 16.0, 976.0, 992.0, aw_in_z0, aw_in_z1, MATS["B2_Chrome_Silver"], col_b2)
        add_box_mm(f"B2_AluWineRack_DoorFrameR_{di_w}", dx1 - 16.0, dx1, 976.0, 992.0, aw_in_z0, aw_in_z1, MATS["B2_Chrome_Silver"], col_b2)
        add_box_mm(f"B2_AluWineRack_DoorFrameB_{di_w}", dx0 + 16.0, dx1 - 16.0, 976.0, 992.0, aw_in_z0, aw_in_z0 + 0.016, MATS["B2_Chrome_Silver"], col_b2)
        add_box_mm(f"B2_AluWineRack_DoorFrameT_{di_w}", dx0 + 16.0, dx1 - 16.0, 976.0, 992.0, aw_in_z1 - 0.016, aw_in_z1, MATS["B2_Chrome_Silver"], col_b2)
        add_box_mm(f"B2_AluWineRack_DoorGlass_{di_w}", dx0 + 16.0, dx1 - 16.0, 980.0, 988.0, aw_in_z0 + 0.016, aw_in_z1 - 0.016, MATS["VentShaft_Clear_White_Glass"], col_b2)
        add_box_mm(f"B2_AluWineRack_DoorPull_{di_w}", hx - 4.0, hx + 4.0, 966.0, 976.0, aw_in_z0 + 0.34, aw_in_z0 + 0.66, MATS["B2_Chrome_Silver"], col_b2)

    # B2 East Wine Wall trimmed to stay strictly flush under B1 mezzanine slab (Y: +976..-1680):
    # Exact 2656mm wide (y: +976..-1680, s=0..2656) x 2000mm tall (z: -4.550..-2.550) x 340mm deep (x: 6000..6340):
    #   - Symmetrical 90mm 3-flute scalloped end columns (3 x 30mm wave, projecting +25mm to x=5975)
    #   - 80mm concave transition piers (s: 90..170 & 2486..2566)
    #   - 4 x 80mm semicircular pilasters (R=40mm at s=210.0, 955.3, 1700.7, 2446.0) with 4 staggered 20mm chrome rings (z_rel 426, 852, 1278, 1704)
    #   - 3 x 665.3mm backlit alabaster bays with 4 x 20mm crystal glass shelves (z_rel 384, 788, 1192, 1596)
    ew_y0 = 976.0   # s = 0 at North L-corner
    ew_span = 2656.0
    ew_z0 = -4.550
    ew_xb = 6340.0
    ew_xf = 6000.0  # 340mm cabinet depth

    def _add_ew_extruded_profile(pname, pts_xy, z_lo, z_hi, mat):
        me = bpy.data.meshes.new(pname)
        bm = bmesh.new()
        vb = [bm.verts.new((px * MM, py * MM, z_lo)) for px, py in pts_xy]
        vt = [bm.verts.new((px * MM, py * MM, z_hi)) for px, py in pts_xy]
        n = len(pts_xy)
        for i in range(n):
            j = (i + 1) % n
            f = bm.faces.new([vb[i], vb[j], vt[j], vt[i]])
            f.smooth = True
        bm.faces.new(vb[::-1])
        bm.faces.new(vt)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        sharp = [e for e in bm.edges if len(e.link_faces) == 2 and e.link_faces[0].normal.dot(e.link_faces[1].normal) < 0.72]
        if sharp:
            bmesh.ops.split_edges(bm, edges=sharp)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(pname, me)
        ob.data.materials.append(mat)
        link_obj(ob, col_b2)
        return ob

    # Continuous 20mm base & top plinth plates across full 2656mm span
    add_box_mm("B2_Display_FullBase", ew_xf, ew_xb, ew_y0 - ew_span, ew_y0, ew_z0, ew_z0 + 0.020, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_Display_FullBaseChrome", ew_xf - 4.0, ew_xf + 2.0, ew_y0 - ew_span, ew_y0, ew_z0, ew_z0 + 0.020, MATS["B2_Chrome_Silver"], col_b2)
    add_box_mm("B2_Display_FullTop",  ew_xf, ew_xb, ew_y0 - ew_span, ew_y0, ew_z0 + 1.980, ew_z0 + 2.000, MATS["OLO_Cab_White"], col_b2)
    add_box_mm("B2_Display_FullTopChrome", ew_xf - 4.0, ew_xf + 2.0, ew_y0 - ew_span, ew_y0, ew_z0 + 1.980, ew_z0 + 2.000, MATS["B2_Chrome_Silver"], col_b2)

    # Left (North s=0..90) & Right (South s=2566..2656) 3-flute scalloped end columns (each flute 30mm, R=15mm, proud to x=5975)
    for end_tag, s_start, s_dir in (("EndN", 0.0, 1.0), ("EndS", ew_span, -1.0)):
        pts_flute = [(ew_xb, ew_y0 - s_start)]
        # 3 alternating semicircular flutes (convex, concave, convex) along 90mm end
        for f_idx in range(3):
            sa = s_start + s_dir * (f_idx * 30.0)
            sb = s_start + s_dir * ((f_idx + 1) * 30.0)
            sc = 0.5 * (sa + sb)
            sgn = -1.0 if (f_idx % 2 == 0) else 1.0  # -X protrudes into room (convex), +X recesses (concave)
            for k in range(9):
                ang = math.pi * (k / 8.0)
                s_cur = sc - 0.5 * (sb - sa) * math.cos(ang)
                x_cur = (ew_xf - 25.0) + sgn * 15.0 * math.sin(ang)
                if f_idx > 0 and k == 0:
                    continue
                pts_flute.append((x_cur, ew_y0 - s_cur))
        s_end = s_start + s_dir * 90.0
        pts_flute.append((ew_xb, ew_y0 - s_end))
        if s_dir < 0:
            pts_flute.reverse()
        _add_ew_extruded_profile(f"B2_Display_Scalloped_{end_tag}", pts_flute, ew_z0 + 0.020, ew_z0 + 1.980, MATS["OLO_Cab_White"])

        # Adjacent 80mm concave transition pier (s=90..170 & s=2836..2916, curved recess at x=6040)
        s_t0 = s_start + s_dir * 90.0
        s_t1 = s_start + s_dir * 170.0
        s_tc = 0.5 * (s_t0 + s_t1)
        pts_tr = [(ew_xb, ew_y0 - s_t0)]
        for k in range(13):
            ang = math.pi * (k / 12.0)
            s_cur = s_tc - 0.5 * (s_t1 - s_t0) * math.cos(ang)
            x_cur = (ew_xf + 40.0) + 40.0 * math.sin(ang)
            pts_tr.append((x_cur, ew_y0 - s_cur))
        pts_tr.append((ew_xb, ew_y0 - s_t1))
        if s_dir < 0:
            pts_tr.reverse()
        _add_ew_extruded_profile(f"B2_Display_ConcavePier_{end_tag}", pts_tr, ew_z0 + 0.020, ew_z0 + 1.980, MATS["OLO_Cab_White"])

    # 4 Exact Semicircular Pilasters (R=40mm at s_mid = 210.0, 955.3, 1700.7, 2446.0) + 4 Staggered 20mm Chrome Rings (426, 852, 1278, 1704mm)
    for _p_idx, _s_mid in enumerate((210.0, 955.3, 1700.7, 2446.0)):
        _p_y = ew_y0 - _s_mid
        add_cyl_mm(f"B2_Display_Pilaster_{_p_idx}", ew_xf, _p_y, 40.0, ew_z0 + 0.020, ew_z0 + 1.980, MATS["OLO_Cab_White"], col_b2, segs=32)
        add_box_mm(f"B2_Display_Pilaster_Back_{_p_idx}", ew_xf, ew_xb, _p_y - 40.0, _p_y + 40.0, ew_z0 + 0.020, ew_z0 + 1.980, MATS["OLO_Cab_White"], col_b2)
        for _r_idx, _zr in enumerate((0.426, 0.852, 1.278, 1.704)):
            add_cyl_mm(f"B2_Display_Ring_{_p_idx}_{_r_idx}", ew_xf, _p_y, 45.0, ew_z0 + _zr, ew_z0 + _zr + 0.020, MATS["B2_Chrome_Silver"], col_b2, segs=32)

    # 3 Equal 665.3mm Backlit Alabaster Bays (s: 250..915.3, 995.3..1660.7, 1740.7..2406) + 4 x 20mm Crystal Glass Shelves (384, 788, 1192, 1596mm)
    _wine_bays = [
        ("Bay1", ew_y0 - 915.3,  ew_y0 - 250.0,  ew_y0 - 340.0,  ew_y0 - 825.3,  0.00, 0.34),
        ("Bay2", ew_y0 - 1660.7, ew_y0 - 995.3,  ew_y0 - 1085.3, ew_y0 - 1570.7, 0.33, 0.67),
        ("Bay3", ew_y0 - 2406.0, ew_y0 - 1740.7, ew_y0 - 1830.7, ew_y0 - 2316.0, 0.66, 1.00),
    ]
    for _bname, _by1, _by2, _sy0, _sy1, _bu0, _bu1 in _wine_bays:
        add_uv_side_box_mm(
            f"B2_Display_{_bname}_BackGlow",
            ew_xb - 18.0, ew_xb, _by1, _by2, ew_z0 + 0.020, ew_z0 + 1.980,
            _bu0, _bu1, 0.0, 1.0,
            MATS["B2_Backlit_Alabaster"], col_b2
        )
        # Exact CAD 20mm vertical chrome strips (90mm inset from bay sides)
        add_box_mm(f"B2_Display_{_bname}_Strip_0", ew_xb - 24.0, ew_xb - 18.0, _sy0 - 10.0, _sy0 + 10.0, ew_z0 + 0.020, ew_z0 + 1.980, MATS["B2_Chrome_Silver"], col_b2)
        add_box_mm(f"B2_Display_{_bname}_Strip_1", ew_xb - 24.0, ew_xb - 18.0, _sy1 - 10.0, _sy1 + 10.0, ew_z0 + 0.020, ew_z0 + 1.980, MATS["B2_Chrome_Silver"], col_b2)
        add_box_mm(f"B2_Display_{_bname}_HeadLED", ew_xf + 12.0, ew_xf + 34.0, _by1, _by2, ew_z0 + 1.972, ew_z0 + 1.980, MATS["B2_CoolWhite_LED"], col_b2)
        for _si, _zr in enumerate((0.384, 0.788, 1.192, 1.596)):
            _sz = ew_z0 + _zr
            add_box_mm(f"B2_Display_{_bname}_Glass_{_si}", ew_xf, ew_xb - 18.0, _by1, _by2, _sz, _sz + 0.020, MATS["B2_Crystal_Glass"], col_b2)
            add_box_mm(f"B2_Display_{_bname}_ShelfChrome_{_si}", ew_xf - 2.0, ew_xf + 4.0, _by1, _by2, _sz, _sz + 0.020, MATS["B2_Chrome_Silver"], col_b2)
            add_box_mm(f"B2_Display_{_bname}_ShelfLED_{_si}", ew_xf + 10.0, ew_xf + 26.0, _by1 + 10.0, _by2 - 10.0, _sz - 0.006, _sz, MATS["B2_CoolWhite_LED"], col_b2)

    # Curated wine & crystal bottles resting cleanly inside Bay1 (60..726), Bay2 (-684..-19), Bay3 (-1430..-764)
    add_cyl_mm("B2_Display_Wine_1_Body", 6190.0, 410.0, 36.0, -2.9340, -2.7040, MATS["Wine_Bottle_Red"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Wine_1_Neck", 6190.0, 410.0, 13.0, -2.7040, -2.6140, MATS["Wine_Bottle_Red"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Wine_2_Body", 6190.0, 300.0, 36.0, -2.9340, -2.7040, MATS["Wine_Bottle_Red"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Wine_2_Neck", 6190.0, 300.0, 13.0, -2.7040, -2.6140, MATS["Wine_Bottle_Red"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Spirit_T0_Body", 6180.0, -250.0, 42.0, -2.9340, -2.7140, MATS["B2_Crystal_Glass"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Spirit_T0_Neck", 6180.0, -250.0, 14.0, -2.7140, -2.6440, MATS["B2_Crystal_Glass"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Spirit_T1_Body", 6180.0, -360.0, 42.0, -2.9340, -2.7140, MATS["B2_Crystal_Glass"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Spirit_T1_Neck", 6180.0, -360.0, 14.0, -2.7140, -2.6440, MATS["B2_Crystal_Glass"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Spirit_T2_Body", 6180.0, -470.0, 42.0, -2.9340, -2.7140, MATS["B2_Crystal_Glass"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Spirit_T2_Neck", 6180.0, -470.0, 14.0, -2.7140, -2.6440, MATS["B2_Crystal_Glass"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Carafe_Body", 6180.0, 355.0, 58.0, -3.7420, -3.5620, MATS["B2_Crystal_Glass"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Carafe_Neck", 6180.0, 355.0, 14.0, -3.5620, -3.4920, MATS["B2_Crystal_Glass"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Decanter_Body", 6180.0, -360.0, 50.0, -3.3380, -3.1380, MATS["B2_Crystal_Glass"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Decanter_Neck", 6180.0, -360.0, 14.0, -3.1380, -3.0680, MATS["B2_Crystal_Glass"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Spirit_M0_Body", 6180.0, -1000.0, 42.0, -3.3380, -3.1180, MATS["B2_Crystal_Glass"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Spirit_M0_Neck", 6180.0, -1000.0, 14.0, -3.1180, -3.0480, MATS["B2_Crystal_Glass"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Spirit_M1_Body", 6180.0, -1110.0, 42.0, -3.3380, -3.1180, MATS["B2_Crystal_Glass"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Spirit_M1_Neck", 6180.0, -1110.0, 14.0, -3.1180, -3.0480, MATS["B2_Crystal_Glass"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Spirit_M2_Body", 6180.0, -1220.0, 42.0, -3.3380, -3.1180, MATS["B2_Crystal_Glass"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Spirit_M2_Neck", 6180.0, -1220.0, 14.0, -3.1180, -3.0480, MATS["B2_Crystal_Glass"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Wine_3_Body", 6190.0, -280.0, 36.0, -4.1460, -3.9160, MATS["Wine_Bottle_Red"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Wine_3_Neck", 6190.0, -280.0, 13.0, -3.9160, -3.8260, MATS["Wine_Bottle_Red"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Wine_4_Body", 6190.0, -390.0, 36.0, -4.1460, -3.9160, MATS["Wine_Bottle_Red"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Wine_4_Neck", 6190.0, -390.0, 13.0, -3.9160, -3.8260, MATS["Wine_Bottle_Red"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Round_1_Body", 6180.0, 455.0, 62.0, -4.1460, -3.9960, MATS["B2_Crystal_Glass"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Round_1_Neck", 6180.0, 455.0, 14.0, -3.9960, -3.9260, MATS["B2_Crystal_Glass"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Round_2_Body", 6180.0, 275.0, 62.0, -4.1460, -3.9960, MATS["B2_Crystal_Glass"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Round_2_Neck", 6180.0, 275.0, 14.0, -3.9960, -3.9260, MATS["B2_Crystal_Glass"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Round_3_Body", 6180.0, -1020.0, 62.0, -4.1460, -3.9960, MATS["B2_Crystal_Glass"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Round_3_Neck", 6180.0, -1020.0, 14.0, -3.9960, -3.9260, MATS["B2_Crystal_Glass"], col_b2, segs=14)
    add_cyl_mm("B2_Display_Round_4_Body", 6180.0, -1200.0, 62.0, -4.1460, -3.9960, MATS["B2_Crystal_Glass"], col_b2, segs=20)
    add_cyl_mm("B2_Display_Round_4_Neck", 6180.0, -1200.0, 14.0, -3.9960, -3.9260, MATS["B2_Crystal_Glass"], col_b2, segs=14)

    # B2 South Wall Full Height + Tall Open Shelving Cabinet updated to exact 1.5m (1500 mm) width:
    # Exact 1500mm wide (x: 4820..6320) x 4110mm tall (z: -4.550..-0.440m), open-topped (NO top cap beam!):
    #   - 4 x 24mm vertical fins (depth 400mm, stepped right end 430mm) with R=80mm quarter-circle rounded TOP-FRONT corner ONLY (flat 90° bottom!)
    #   - 3 x 468mm bays with 3 TWIN-SHELF PAIRS (25mm thick: z_rel 950/1275, 2000/2325, 3050/3375mm) + 上下发光灯带 (upper & lower LEDs!)
    #   - 3 centered 388x500mm floor drawer boxes (40mm symmetric side gap, 40mm toe-kick, 18mm counter lid)
    add_box_mm("B2_Wall_South_Full", -1520.0, 6450.0, -5690.0, -5430.0, -4.5500, 0.0000, plaster_mat, col_b2)
    tc_x0, tc_x1 = 4820.0, 6320.0   # Exact 1500mm (1.5m) wide!
    tc_z0 = -4.550
    tc_z1 = tc_z0 + 4.110           # -0.440m (exact 4110mm CAD height!)
    add_box_mm("B2_TallCab_WhiteBack", tc_x0, tc_x1, -5430.0, -5412.0, tc_z0, tc_z1, MATS["OLO_Cab_White"], col_b2)

    def _add_cad_tallcab_fin(fname, x1, x2, y_back_mm, y_front_mm, z_bot_m, z_top_m, r_top_mm=80.0, frame_t_mm=16.0):
        """CAD-exact Y-Z vertical fin: flat 90° bottom, crisp R=80mm quarter-circle top-front curve ONLY."""
        def _yz_profile(yb, yf, zb, zt, rc_mm):
            rc_m = rc_mm * MM
            pts_yz = [(yb * MM, zb), (yf * MM, zb), (yf * MM, zt - rc_m)]
            for k in range(1, 13):
                a = math.radians(90.0 * k / 12.0)
                pts_yz.append(((yf - rc_mm) * MM + rc_m * math.cos(a), (zt - rc_m) + rc_m * math.sin(a)))
            pts_yz.append((yb * MM, zt))
            return pts_yz

        for sfx, dx, yb, yf, zb, zt, rc, fmat in (
            ("Frame", 0.0, y_back_mm, y_front_mm, z_bot_m, z_top_m, r_top_mm, MATS["B2_TallCab_Gunmetal"]),
            ("Leather", 1.5, y_back_mm + 4.0, y_front_mm - frame_t_mm, z_bot_m + 0.020, z_top_m - frame_t_mm * MM, max(24.0, r_top_mm - frame_t_mm), MATS["B2_TallCab_BeigeLeather"]),
        ):
            mesh_d = bpy.data.meshes.new(f"{fname}_{sfx}")
            bm_d = bmesh.new()
            pyz = _yz_profile(yb, yf, zb, zt, rc)
            xl = (x1 - (1.2 if sfx == "Leather" else 0.0)) * MM
            xr = (x2 + (1.2 if sfx == "Leather" else 0.0)) * MM
            vl = [bm_d.verts.new((xl, yv, zv)) for yv, zv in pyz]
            vr = [bm_d.verts.new((xr, yv, zv)) for yv, zv in pyz]
            np_len = len(pyz)
            for idx_p in range(np_len):
                jn = (idx_p + 1) % np_len
                f_side = bm_d.faces.new([vl[idx_p], vl[jn], vr[jn], vr[idx_p]])
                f_side.smooth = True
            bm_d.faces.new(vl[::-1])
            bm_d.faces.new(vr)
            bmesh.ops.recalc_face_normals(bm_d, faces=bm_d.faces[:])
            sharp = [e for e in bm_d.edges if len(e.link_faces) == 2 and e.link_faces[0].normal.dot(e.link_faces[1].normal) < 0.72]
            if sharp:
                bmesh.ops.split_edges(bm_d, edges=sharp)
            bm_d.to_mesh(mesh_d)
            bm_d.free()
            obj_d = bpy.data.objects.new(f"{fname}_{sfx}", mesh_d)
            obj_d.data.materials.append(fmat)
            link_obj(obj_d, col_b2)

    # 4 x 24mm vertical fins at rel X = 0, 492, 984, 1476 (3 equal 468mm bays totaling 1500mm)
    div_specs = [
        (tc_x0 +    0.0, tc_x0 +   24.0, -5030.0),
        (tc_x0 +  492.0, tc_x0 +  516.0, -5030.0),
        (tc_x0 +  984.0, tc_x0 + 1008.0, -5030.0),
        (tc_x0 + 1476.0, tc_x0 + 1500.0, -5000.0),  # Rightmost 430mm end fin per CAD plan
    ]
    for di, (dx1, dx2, yf_fin) in enumerate(div_specs):
        _add_cad_tallcab_fin(f"B2_TallCab_Fin_{di}", dx1, dx2, -5430.0, yf_fin, tc_z0, tc_z1, r_top_mm=80.0)

    # 3 Pairs of CAD Twin Shelves (z_rel = 950, 1275 | 2000, 2325 | 3050, 3375 mm, 25mm thick) + 上下发光灯带
    tall_shelves_z_rel = [0.950, 1.275, 2.000, 2.325, 3.050, 3.375]
    bay_spans = [(tc_x0 + 24.0, tc_x0 + 492.0), (tc_x0 + 516.0, tc_x0 + 984.0), (tc_x0 + 1008.0, tc_x0 + 1476.0)]
    for bi, (bx1, bx2) in enumerate(bay_spans, start=1):
        bxc = 0.5 * (bx1 + bx2)
        # Centered 388 x 500 mm floor drawer box (40mm symmetric side gap inside 468mm bay, 40mm toe-kick, 18mm lid)
        add_box_mm(f"B2_TallCab_Bay{bi}_FloorBoxKick", bxc - 180.0, bxc + 180.0, -5400.0, -5075.0, tc_z0, tc_z0 + 0.040, MATS["OLO_ToeKick_Black"], col_b2)
        add_box_mm(f"B2_TallCab_Bay{bi}_FloorBoxBody", bxc - 194.0, bxc + 194.0, -5410.0, -5055.0, tc_z0 + 0.040, tc_z0 + 0.482, MATS["Cabinet_Charcoal"], col_b2)
        add_box_mm(f"B2_TallCab_Bay{bi}_FloorBoxDrwF", bxc - 193.0, bxc + 193.0, -5055.0, -5036.0, tc_z0 + 0.044, tc_z0 + 0.478, MATS["B2_TallCab_Gunmetal"], col_b2)
        add_box_mm(f"B2_TallCab_Bay{bi}_FloorBoxLid",  bxc - 194.0, bxc + 194.0, -5412.0, -5034.0, tc_z0 + 0.482, tc_z0 + 0.500, MATS["B2_TallCab_CreamShelf"], col_b2)
        for si, sz_rel in enumerate(tall_shelves_z_rel):
            sz = tc_z0 + sz_rel
            # 20mm gunmetal side end-brackets + 428mm veined marble/cream inner shelf (20+428+20=468mm bay, 25mm thick)
            add_box_mm(f"B2_TallCab_Bay{bi}_BrkL_{si}", bx1, bx1 + 20.0, -5412.0, -5045.0, sz, sz + 0.025, MATS["B2_TallCab_Gunmetal"], col_b2)
            add_box_mm(f"B2_TallCab_Bay{bi}_BrkR_{si}", bx2 - 20.0, bx2, -5412.0, -5045.0, sz, sz + 0.025, MATS["B2_TallCab_Gunmetal"], col_b2)
            add_box_mm(f"B2_TallCab_Bay{bi}_Shelf_{si}", bx1 + 20.0, bx2 - 20.0, -5412.0, -5045.0, sz, sz + 0.015, MATS["B2_TallCab_CreamShelf"], col_b2)
            add_uv_front_box_mm(f"B2_TallCab_Bay{bi}_ShelfMarble_{si}", bx1 + 20.0, bx2 - 20.0, -5412.0, -5045.0, sz + 0.015, sz + 0.025, (bi - 1) * 0.25, (bi - 1) * 0.25 + 0.45, si * 0.14, si * 0.14 + 0.35, MATS["Marble_Fishbelly"], col_b2)
            # 上下发光灯带 (both lower glow & upper wall-wash LED per CAD callout!)
            add_box_mm(f"B2_TallCab_Bay{bi}_LED_Bot_{si}", bx1 + 24.0, bx2 - 24.0, -5090.0, -5070.0, sz - 0.007, sz, MATS["Warm_LED_Glow"], col_b2)
            add_box_mm(f"B2_TallCab_Bay{bi}_LED_Top_{si}", bx1 + 24.0, bx2 - 24.0, -5406.0, -5390.0, sz + 0.025, sz + 0.032, MATS["Warm_LED_Glow"], col_b2)

    # Curated styling accents centered cleanly in 1.5m TallCab bays (centers 5078, 5570, 6062)
    add_box_mm("B2_TallCab_Book_1", 4920.0, 5060.0, -5340.0, -5140.0, tc_z0 + 1.300, tc_z0 + 1.490, MATS["Book_Cream"], col_b2)
    add_box_mm("B2_TallCab_Book_2", 5430.0, 5630.0, -5360.0, -5140.0, tc_z0 + 2.350, tc_z0 + 2.410, MATS["Book_Cream"], col_b2)
    add_box_mm("B2_TallCab_TopBoxL", 4900.0, 5240.0, -5365.0, -5100.0, tc_z0 + 3.400, tc_z0 + 3.580, MATS["Cabinet_Charcoal"], col_b2)
    add_box_mm("B2_TallCab_TopBoxR", 5890.0, 6220.0, -5365.0, -5100.0, tc_z0 + 3.400, tc_z0 + 3.580, MATS["Cabinet_Charcoal"], col_b2)
    add_cyl_mm("B2_TallCab_VaseBlack", 6062.0, -5220.0, 62.0, tc_z0 + 1.300, tc_z0 + 1.560, MATS["Cabinet_Charcoal"], col_b2, segs=24)
    add_box_mm("B2_TallCab_Print1", 4940.0, 5200.0, -5390.0, -5376.0, tc_z0 + 2.350, tc_z0 + 2.660, MATS["Book_Cream"], col_b2)
    add_box_mm("B2_TallCab_Print2", 5440.0, 5690.0, -5390.0, -5376.0, tc_z0 + 1.300, tc_z0 + 1.610, MATS["Cabinet_Charcoal"], col_b2)
    add_cyl_mm("B2_TallCab_BronzeObj", 5078.0, -5220.0, 50.0, tc_z0 + 3.400, tc_z0 + 3.600, MATS["B2_TallCab_Gunmetal"], col_b2, segs=20)
    add_box_mm("B2_TallCab_GlassCube", 5960.0, 6160.0, -5320.0, -5140.0, tc_z0 + 2.350, tc_z0 + 2.540, MATS["B2_Crystal_Glass"], col_b2)

    col_b1 = bpy.data.collections.new("B1_负一层_夹层")
    bpy.context.scene.collection.children.link(col_b1)
    cols["B1_Mezz"] = col_b1
    p_b1 = PLANS["B1_Mezz"]
    z_b1, h_b1 = p_b1["z0"], p_b1["h"]
    zf_b1 = z_b1 + 0.005

    # B1 Mezzanine S-Curved Edge calibrated strictly to site construction skeleton photo (IMG_7189.HEIC)
    # The platform curves forward and wraps COMPLETELY around the outside of the main column (cx=3860, cy=-1780)
    # with a continuous sweeping cantilevered balcony (y reaches -2435mm), exposing the North bookcase & void,
    # and returns smoothly to East wall (6340, -1760).
    # B1 Mezzanine S-Curved Edge strictly calibrated to CAD screenshot (media_1793816192005_98fa95ee.jpg):
    # - Segment 1 (x = -200..1300): Straight horizontal edge at y = -480mm along North of straight stair run (Steps 6..13)
    # - Segment 2 (x = 1300..2480): Convex circular arc wrapping concentrically around the Grand Staircase's outer R1067 curve
    #   (centered at cx1=1300, cy1=-1660 with radius R_mezz=1180mm, keeping the entire stairwell open from above!)
    # - Segment 3 (x = 2480..6340): Smooth S-inflection at (2480, -1660) plunging into the concave belly that wraps around
    #   the South side of the main column (cx=3860, cy=-1780, r=290) with exact 312mm clearance at (3860, -2382),
    #   and sweeping back Northward to meet the East wall tangentially at (6340, -1760).
    # B1 Mezzanine S-Curved Edge (original version wrapping gracefully around round column (4680, -1420, r=240)):
    def _catmull_rom_chain(knots, n_per=16):
        pts = []
        for i in range(len(knots) - 1):
            p0 = knots[max(0, i - 1)] if i > 0 else knots[0]
            p1 = knots[i]
            p2 = knots[i + 1]
            p3 = knots[min(len(knots) - 1, i + 2)]
            for k in range(n_per):
                t = k / float(n_per)
                t2 = t * t
                t3 = t2 * t
                pt_x = 0.5 * ((2*p1[0]) + (-p0[0] + p2[0])*t + (2*p0[0] - 5*p1[0] + 4*p2[0] - p3[0])*t2 + (-p0[0] + 3*p1[0] - 3*p2[0] + p3[0])*t3)
                pt_y = 0.5 * ((2*p1[1]) + (-p0[1] + p2[1])*t + (2*p0[1] - 5*p1[1] + 4*p2[1] - p3[1])*t2 + (-p0[1] + 3*p1[1] - 3*p2[1] + p3[1])*t3)
                pts.append((float(pt_x), float(pt_y)))
        pts.append(knots[-1])
        return pts

    b1_knots = [
        (1020.0,  -620.0),  # Meets B1_Mezz_NW_Arrival SE corner & 1.0m-wide B1->B2 stair starting East edge
        (1120.0,  -660.0),  # Smooth tangential transition outside 1.0m B2_GrandStair curve (+60mm clear of tread)
        (1560.0,  -660.0),  # Parallel north lip of stair straight run (exact C1 tangent to R=1280 arc)
        (2040.0,  -753.0),  # Concentric arc around 1.0m Grand Stair (C_bot=(1560,-1940), R=1280, 68 deg)
        (2465.0, -1035.0),  # Concentric arc hugging Grand Stair outer curve (45 deg)
        (2780.0, -1380.0),  # Monotonic smooth curve past stair outer turn (no sharp spike)
        (3200.0, -1640.0),  # Smooth sweep toward cantilevered column belly
        (3720.0, -1810.0),  # Approaching column South front
        (4200.0, -1940.0),  # Sweeping cleanly south of column
        (4680.0, -1972.0),  # Exact 312mm concentric wrap around round column (4680, -1420, r=240)
        (5240.0, -1910.0),  # Bending gently back North-East
        (5720.0, -1770.0),  # Smooth return covering East Wine Wall
        (6060.0, -1695.0),  # Tangential approach to East wall pier
        (6340.0, -1680.0),  # Meets East wall aligned with trimmed B2 East Wine Wall (Y=-1680)
    ]
    pts_b1_front_edge = _catmull_rom_chain(b1_knots, n_per=32)
    n_pts_edge = len(pts_b1_front_edge)

    mesh_b1_slab = bpy.data.meshes.new("B1_Mezz_Slab")
    bm_b1s = bmesh.new()
    rings_b1s = []
    for (ex, ey) in pts_b1_front_edge:
        # Exact 15cm (0.15m) slab thickness (-2.20..-2.05m) giving 1.90m clear height under -0.15m B1 ceiling
        v_fb = bm_b1s.verts.new((ex * MM, ey * MM, -2.20))
        v_nb = bm_b1s.verts.new((ex * MM, 1410.0 * MM, -2.20))
        v_nt = bm_b1s.verts.new((ex * MM, 1410.0 * MM, -2.05))
        v_ft = bm_b1s.verts.new((ex * MM, ey * MM, -2.05))
        rings_b1s.append((v_fb, v_nb, v_nt, v_ft))
    for i in range(n_pts_edge - 1):
        r0, r1 = rings_b1s[i], rings_b1s[i + 1]
        for s in range(4):
            bm_b1s.faces.new([r0[s], r0[(s + 1) % 4], r1[(s + 1) % 4], r1[s]])
    bm_b1s.faces.new(list(rings_b1s[0])[::-1])
    bm_b1s.faces.new(list(rings_b1s[-1]))
    bmesh.ops.recalc_face_normals(bm_b1s, faces=bm_b1s.faces[:])
    bm_b1s.to_mesh(mesh_b1_slab)
    bm_b1s.free()
    for p in mesh_b1_slab.polygons:
        p.use_smooth = (abs(p.normal.z) < 0.7)
    obj_b1_slab = bpy.data.objects.new("B1_Mezz_Slab", mesh_b1_slab)
    obj_b1_slab.data.materials.append(plaster_mat)
    link_obj(obj_b1_slab, col_b1)

    # Seamless 15cm NW Arrival Slab with 90.0 deg edge (x=20mm, y=-620..1410mm) strictly perpendicular to North wall cabinet;
    # South edge (y=-620mm) connects cleanly into 1.0m-wide B1->B2 Grand Stair starting step (x=20..1020mm), 1100mm South of 1F->B1 Tread_1 (y=480mm).
    add_box_mm("B1_Mezz_NW_Arrival", 20.0, 1020.0, -620.0, 1410.0, -2.20, -2.05, plaster_mat, col_b1)
    add_box_mm("B1_Landing_West_GapGlass", 20.0, 36.0, -612.0, 472.0, -2.05, -1.13, MATS["Glass_Balustrade_Clear"], col_b1)

    # Flush under-mezzanine soffit closing gap above B2 North/East wine & mirror cabinets (-2.55..-2.20m)
    add_box_mm("B2_UnderMezz_Soffit_North", 2140.0, 6340.0,   976.0, 1410.0, -2.55, -2.20, plaster_mat, col_b2)
    add_box_mm("B2_UnderMezz_Soffit_East",  6000.0, 6340.0, -1680.0,  976.0, -2.55, -2.20, plaster_mat, col_b2)

    def add_b1_edge_ribbon_pts(rname, pts_list, n_off_in_mm, n_off_out_mm, z0, z1, mat, smooth_sides=True):
        if len(pts_list) < 2:
            return None
        np_loc = len(pts_list)
        mesh_rb = bpy.data.meshes.new(rname)
        bm_rb = bmesh.new()
        rings_rb = []
        for i, (ex, ey) in enumerate(pts_list):
            i_prev = max(0, i - 1)
            i_next = min(np_loc - 1, i + 1)
            dx = pts_list[i_next][0] - pts_list[i_prev][0]
            dy = pts_list[i_next][1] - pts_list[i_prev][1]
            length = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / length, dx / length
            p_in  = ((ex + n_off_in_mm * nx) * MM,  (ey + n_off_in_mm * ny) * MM)
            p_out = ((ex + n_off_out_mm * nx) * MM, (ey + n_off_out_mm * ny) * MM)
            v0 = bm_rb.verts.new((p_in[0],  p_in[1],  z0))
            v1 = bm_rb.verts.new((p_out[0], p_out[1], z0))
            v2 = bm_rb.verts.new((p_out[0], p_out[1], z1))
            v3 = bm_rb.verts.new((p_in[0],  p_in[1],  z1))
            rings_rb.append((v0, v1, v2, v3))
        for i in range(np_loc - 1):
            r0, r1 = rings_rb[i], rings_rb[i + 1]
            for s in range(4):
                bm_rb.faces.new([r0[s], r0[(s + 1) % 4], r1[(s + 1) % 4], r1[s]])
        bm_rb.faces.new(list(rings_rb[0])[::-1])
        bm_rb.faces.new(list(rings_rb[-1]))
        bmesh.ops.recalc_face_normals(bm_rb, faces=bm_rb.faces[:])
        bm_rb.to_mesh(mesh_rb)
        bm_rb.free()
        if smooth_sides:
            for p in mesh_rb.polygons:
                p.use_smooth = (abs(p.normal.z) < 0.7)
        obj_rb = bpy.data.objects.new(rname, mesh_rb)
        obj_rb.data.materials.append(mat)
        link_obj(obj_rb, col_b1)
        return obj_rb

    # Continuous Fascia Trim + Plain Frameless Clear Glass Balustrade starting cleanly at (820, 480) along B1 mezzanine edge (NO gold cap!)
    add_b1_edge_ribbon_pts("B1_Mezz_Fascia_Trim", pts_b1_front_edge, -8.0, 14.0, -2.21, -2.045, MATS["Basement_Warm_Plaster"])
    pts_b1_glass = pts_b1_front_edge
    add_b1_edge_ribbon_pts("B1_Platform_Glass_Curved", pts_b1_glass, -9.0, 9.0, -2.05, -1.13, MATS["Glass_Balustrade_Clear"])

    # B1 North Wall 5110 x 1880 x 320mm Cabinet Wall (exact staggered widths + Left push-to-open door + Vertical LED baffle + Right slanted translucent wood louver)
    # (x: 930..6040mm, y: 1090..1410mm, z: -2.050..-0.170m fitting 1.90m B1 clear height)
    bk_x0, bk_x1 = 930.0, 6040.0
    bk_y0, bk_y1 = 1090.0, 1410.0
    bk_z0, bk_z1 = -2.050, -0.170
    add_box_mm("B1_Grid_Carcass", bk_x0, bk_x1, bk_y0 + 100.0, bk_y1, bk_z0 + 0.025, bk_z1, MATS["OLO_Cab_White"], col_b1)
    add_box_mm("B1_Grid_SideL",   bk_x0, bk_x0 + 20.0, bk_y0 + 20.0, bk_y1, bk_z0 + 0.025, bk_z1, MATS["OLO_Cab_White"], col_b1)
    add_box_mm("B1_Grid_SideR",   bk_x1 - 20.0, bk_x1, bk_y0 + 20.0, bk_y1, bk_z0 + 0.025, bk_z1, MATS["OLO_Cab_White"], col_b1)
    add_box_mm("B1_Grid_TopShadowGap", bk_x0, bk_x1, bk_y0 + 18.0, bk_y1, bk_z1, bk_z1 + 0.020, MATS["Cabinet_Charcoal"], col_b1)
    add_box_mm("B1_Grid_BasePlinth", bk_x0, bk_x1, bk_y0 + 34.0, bk_y1, bk_z0, bk_z0 + 0.025, MATS["OLO_Cab_White"], col_b1)

    n_cols_bk = 10
    col_w_bk = (bk_x1 - bk_x0) / float(n_cols_bk)
    row_zs_bk = [-2.025, -1.405, -0.785, -0.170]
    for si, (sz0, sz1) in enumerate([(-2.025, -2.005), (-1.414, -1.396), (-0.794, -0.776), (-0.188, -0.170)]):
        add_box_mm(f"B1_Grid_Shelf_{si}", bk_x0 + 20.0, bk_x1 - 20.0, bk_y0 + 22.0, bk_y0 + 100.0, sz0, sz1, MATS["OLO_Cab_White"], col_b1)

    # Rhythmic segmented plinth glow dashes
    for pg_i, (c_a, c_b) in enumerate([(0.1, 2.8), (4.2, 6.9), (8.2, 9.9)]):
        add_box_mm(
            f"B1_Grid_BaseGlow_{pg_i}",
            bk_x0 + c_a * col_w_bk, bk_x0 + c_b * col_w_bk,
            bk_y0 + 10.0, bk_y0 + 34.0, bk_z0, bk_z0 + 0.024, MATS["Warm_LED_Amber"], col_b1
        )

    # 9 aligned main columns (5110mm / 9 = 567.78mm each) matching site photo media_1795478108181_f8f2dea3.jpg:
    # ONLY the 9 bays with built internal vertical baffles get Left push door + Vertical LED baffle + Right slanted translucent wood!
    # Top (row 2): cols {1, 5, 8} | Mid (row 1): cols {2, 4, 6} | Bot (row 0): cols {1, 5, 8} (staggered 3+3+3 rhythm matching reference!)
    _b1_col_w = (bk_x1 - bk_x0) / 9.0
    _b1_row_layouts = [
        # Row 0 (bot): 9 aligned bays, LED+slant in cols 1, 5, 8
        ([_b1_col_w] * 9, {1: 185.0, 5: 175.0, 8: 175.0}),
        # Row 1 (mid): 9 aligned bays, LED+slant in cols 2, 4, 6
        ([_b1_col_w] * 9, {2: 170.0, 4: 185.0, 6: 180.0}),
        # Row 2 (top): 9 aligned bays, LED+slant in cols 1, 5, 8
        ([_b1_col_w] * 9, {1: 185.0, 5: 175.0, 8: 175.0}),
    ]
    for ri in range(3):
        rz0, rz1 = row_zs_bk[ri] + 0.002, row_zs_bk[ri + 1] - 0.002
        widths, led_bays = _b1_row_layouts[ri]
        cur_x = bk_x0
        for bi, bw in enumerate(widths):
            bx0, bx1 = cur_x, cur_x + bw
            cur_x = bx1
            sw = led_bays.get(bi)
            if sw is None:
                add_box_mm(f"B1_Grid_Door_{ri}_{bi}", bx0 + 2.0, bx1 - 2.0, bk_y0, bk_y0 + 20.0, rz0, rz1, MATS["OLO_Cab_White"], col_b1)
            else:
                xv = bx1 - sw - 22.0
                # 1) Left push-to-open door (弹压方式门板) covering LEFT of vertical LED baffle
                add_box_mm(f"B1_Grid_Door_{ri}_{bi}", bx0 + 2.0, xv - 1.0, bk_y0, bk_y0 + 20.0, rz0, rz1, MATS["OLO_Cab_White"], col_b1)
                # 2) Vertical baffle divider + exposed glowing LED strip mounted on its right side
                add_box_mm(f"B1_Grid_Baffle_{ri}_{bi}", xv, xv + 20.0, bk_y0 + 16.0, bk_y0 + 96.0, rz0 + 0.008, rz1 - 0.008, MATS["OLO_Cab_White"], col_b1)
                add_box_mm(f"B1_Grid_VertLED_{ri}_{bi}", xv + 20.0, xv + 32.0, bk_y0 + 26.0, bk_y0 + 86.0, rz0 + 0.008, rz1 - 0.008, MATS["Warm_LED_Amber"], col_b1)
                add_box_mm(f"B1_Grid_SlantNiche_{ri}_{bi}", xv + 20.0, bx1 - 2.0, bk_y0 + 92.0, bk_y0 + 100.0, rz0 + 0.008, rz1 - 0.008, MATS["Cabinet_Charcoal"], col_b1)
                # 3) Right slanted translucent wood louver (透光的斜倾木板) letting vertical baffle LED light wash out obliquely
                pts_slant = [(xv + 28.0, bk_y0 + 84.0), (bx1 - 2.0, bk_y0), (bx1 - 2.0, bk_y0 + 16.0), (xv + 28.0, bk_y0 + 98.0)]
                add_prism(f"B1_Grid_SlantWood_{ri}_{bi}", pts_slant, rz0 + 0.008, rz1 - 0.008, MATS["B1_Slant_TranslucentWood"], col_b1)

    # B1 East Wall 2440 x 870 x 300mm Black-Carcass & Brushed Gold-Shelf Low Cabinet below Fish-Pond Window (黑色柜体 + 金色横板 + 错落灯带)
    ec_x0, ec_x1 = 6040.0, 6340.0
    ec_y0, ec_y1 = -1350.0, 1090.0
    ec_z0, ec_z1 = -2.050, -1.180
    add_box_mm("B1_East_LowCab_Back", ec_x1 - 18.0, ec_x1, ec_y0, ec_y1, ec_z0, ec_z1, MATS["Cabinet_Charcoal"], col_b1)
    add_box_mm("B1_East_LowCab_Bot",  ec_x0, ec_x1, ec_y0, ec_y1, ec_z0, ec_z0 + 0.026, MATS["Gold_Brass"], col_b1)
    add_box_mm("B1_East_LowCab_Mid",  ec_x0, ec_x1, ec_y0, ec_y1, -1.625, -1.600, MATS["Gold_Brass"], col_b1)
    add_box_mm("B1_East_LowCab_Top",  ec_x0, ec_x1, ec_y0, ec_y1, ec_z1 - 0.026, ec_z1, MATS["Gold_Brass"], col_b1)
    ec_bay_w = (ec_y1 - ec_y0 - 24.0) / 4.0  # 4 x 604mm bays
    _ec_led_ratios = [0.95, 0.55, 0.85, 0.65]
    for ei in range(5):
        ey = ec_y0 + ei * ec_bay_w
        add_box_mm(f"B1_East_LowCab_Div_{ei}", ec_x0, ec_x1, ey, ey + 24.0, ec_z0 + 0.026, ec_z1 - 0.026, MATS["Cabinet_Charcoal"], col_b1)
        if ei < 4:
            bay_len = ec_bay_w - 28.0
            span_l = bay_len * _ec_led_ratios[ei]
            ly0 = ey + 26.0 + (bay_len - span_l) * (0.5 if ei % 2 == 0 else 0.15)
            sz_z = (ec_z1 - 0.042, ec_z1 - 0.027) if ei % 2 == 0 else (-1.641, -1.626)
            add_box_mm(f"B1_East_LowCab_ShelfLED_{ei}", ec_x0 + 25.0, ec_x0 + 45.0, ly0, ly0 + span_l, sz_z[0], sz_z[1], MATS["Warm_LED_Amber"], col_b1)

    # East Wall Two Genuine Recessed Viewing Windows (North Horizontal Garden Window above B1_East_LowCab + South Underwater Fish-Pond Window)
    # 1. North Mezzanine Horizontal Garden Window (y: -1150..+900, z: -1.16..-0.58m, NO unnatural flat sticker — real 3D courtyard garden outside!)
    add_box_mm("B1_East_Win_Lower_Reveal_Bot",   6340, 6600, -1150,  900, -1.16,  -1.135, plaster_mat, col_b1)
    add_box_mm("B1_East_Win_Lower_Reveal_Top",   6340, 6600, -1150,  900, -0.605, -0.58,  plaster_mat, col_b1)
    add_box_mm("B1_East_Win_Lower_Reveal_South", 6340, 6600, -1150, -1125, -1.16, -0.58,  plaster_mat, col_b1)
    add_box_mm("B1_East_Win_Lower_Reveal_North", 6340, 6600,   875,   900, -1.16, -0.58,  plaster_mat, col_b1)
    add_box_mm("B1_East_Win_Lower_Frame_Bot",    6520, 6560, -1125,  875, -1.135, -1.107, MATS["OLO_ToeKick_Black"], col_b1)
    add_box_mm("B1_East_Win_Lower_Frame_Top",    6520, 6560, -1125,  875, -0.633, -0.605, MATS["OLO_ToeKick_Black"], col_b1)
    add_box_mm("B1_East_Win_Lower_Frame_South",  6520, 6560, -1125, -1097, -1.135, -0.605, MATS["OLO_ToeKick_Black"], col_b1)
    add_box_mm("B1_East_Win_Lower_Frame_North",  6520, 6560,   847,   875, -1.135, -0.605, MATS["OLO_ToeKick_Black"], col_b1)
    add_box_mm("B1_East_Win_Lower_Glass",        6535, 6545, -1122,  872, -1.132, -0.608, MATS["VentShaft_Clear_White_Glass"], col_b1)

    # 3D Sunken Courtyard Garden outside B1 Mezzanine Window (x: 6565..8050, y: -1360..+1120, z: -1.32..+0.25m)
    mat_g_soil   = make_mat("Garden_Rich_Soil",   (0.18, 0.14, 0.10, 1.0), metallic=0.0, roughness=0.92)
    mat_g_moss   = make_mat("Garden_Lush_Moss",   (0.22, 0.40, 0.16, 1.0), metallic=0.0, roughness=0.82)
    mat_g_gravel = make_mat("Garden_River_Stone", (0.58, 0.56, 0.52, 1.0), metallic=0.0, roughness=0.78)
    mat_g_rock   = make_mat("Garden_Taihu_Rock",  (0.34, 0.35, 0.33, 1.0), metallic=0.0, roughness=0.80)
    mat_g_wall   = make_mat("Garden_Limestone",   (0.76, 0.73, 0.67, 1.0), metallic=0.0, roughness=0.72)
    mat_g_cedar  = make_mat("Garden_Cedar_Slat",  (0.46, 0.30, 0.18, 1.0), metallic=0.0, roughness=0.65)
    mat_g_bamboo = make_mat("Garden_Bamboo_Culm", (0.30, 0.52, 0.20, 1.0), metallic=0.0, roughness=0.38)
    mat_g_leaf1  = make_mat("Garden_Foliage_Deep",(0.13, 0.36, 0.14, 1.0), metallic=0.0, roughness=0.55)
    mat_g_leaf2  = make_mat("Garden_Foliage_Sun", (0.28, 0.54, 0.19, 1.0), metallic=0.0, roughness=0.48)
    mat_g_leaf3  = make_mat("Garden_Maple_Tip",   (0.54, 0.24, 0.16, 1.0), metallic=0.0, roughness=0.52)
    mat_g_bark   = make_mat("Garden_Shrub_Stem",  (0.26, 0.18, 0.12, 1.0), metallic=0.0, roughness=0.82)
    mat_g_flower = make_mat("Garden_Blossom_Soft",(0.94, 0.88, 0.86, 1.0), metallic=0.0, roughness=0.42)
    mat_g_sky    = make_mat("Garden_Daylight_Sky",(0.84, 0.91, 0.96, 1.0), metallic=0.0, roughness=0.90, emission=(0.82, 0.90, 0.96, 1.0), emission_strength=0.42)

    # Planter bed earth, gravel border, low limestone garden wall + warm cedar fence slats + open daylight backdrop
    add_box_mm("B1_Garden_SoilBed",    6565, 8000, -1360, 1120, -1.32, -1.155, mat_g_soil, col_b1)
    add_box_mm("B1_Garden_GravelStrip",6565, 7020, -1300, 1060, -1.160, -1.135, mat_g_gravel, col_b1)
    add_box_mm("B1_Garden_BackWallLow",7920, 8040, -1360, 1120, -1.32, -0.78,  mat_g_wall, col_b1)
    add_box_mm("B1_Garden_BackWallCap",7900, 8060, -1360, 1120, -0.78, -0.735, mat_g_wall, col_b1)
    add_box_mm("B1_Garden_SideWallS",  6565, 8040, -1380, -1320, -1.32, -0.35, mat_g_wall, col_b1)
    add_box_mm("B1_Garden_SideWallN",  6565, 8040,  1080,  1140, -1.32, -0.35, mat_g_wall, col_b1)
    for _sl_i, _sl_z in enumerate([-0.68, -0.58, -0.48, -0.38, -0.28]):
        add_box_mm(f"B1_Garden_FenceSlat_{_sl_i+1}", 7950, 7985, -1320, 1080, _sl_z, _sl_z + 0.068, mat_g_cedar, col_b1)
    add_box_mm("B1_Garden_SkyBackdrop", 8035, 8060, -1340, 1100, -0.74, 0.10, mat_g_sky, col_b1)

    # Natural slate stepping stones & mossy Taihu garden rocks (visible right outside sill)
    add_box_mm("B1_Garden_StepStone_1", 6660, 6940, -520, -240, -1.140, -1.105, mat_g_rock, col_b1, r_corner=45.0)
    add_box_mm("B1_Garden_StepStone_2", 6680, 6960,  180,  460, -1.140, -1.105, mat_g_rock, col_b1, r_corner=45.0)

    def _add_garden_mound(gname, gx, gy, gz, rx_mm, ry_mm, rz_m, mat, segs=12):
        me = bpy.data.meshes.new(gname)
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
        for v in bm.verts:
            # Gentle organic undulation so rocks, moss, and foliage look natural, never rigid spheres
            wob = 1.0 + 0.14 * math.sin(v.co.x * 3.7 + v.co.y * 2.9) * math.cos(v.co.z * 3.1)
            v.co.x = gx * MM + v.co.x * (rx_mm * MM) * wob
            v.co.y = gy * MM + v.co.y * (ry_mm * MM) * wob
            v.co.z = gz + v.co.z * rz_m * wob
        for f in bm.faces:
            f.smooth = True
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(gname, me)
        ob.data.materials.append(mat)
        link_obj(ob, col_b1)
        return ob

    # Sculpted garden rocks & lush moss cushions along the foreground planter
    for _ri, (_rx, _ry, _rrx, _rry, _rrz) in enumerate([
        (6920, -860, 150, 190, 0.14),
        (7180, -120, 175, 210, 0.18),
        (6960,  640, 140, 175, 0.13),
    ], 1):
        _add_garden_mound(f"B1_Garden_Rock_{_ri}", _rx, _ry, -1.07, _rrx, _rry, _rrz, mat_g_rock)
        _add_garden_mound(f"B1_Garden_Moss_{_ri}", _rx - 55, _ry + 40, -1.12, _rrx * 1.15, _rry * 1.05, 0.06, mat_g_moss)

    # Ornamental courtyard bamboo culms + delicate 3D leaf clusters along back planter
    _bamboo_specs = [
        (7640, -1040, 16.0, -0.22), (7720, -880, 14.0, -0.18), (7580, -720, 15.0, -0.26),
        (7760,  -460, 15.0, -0.20), (7660, -260, 17.0, -0.15), (7740,   80, 15.0, -0.22),
        (7620,   380, 16.0, -0.18), (7750,  580, 14.0, -0.24), (7680,  820, 16.0, -0.16),
    ]
    for _bi, (_bx, _by, _br, _btop) in enumerate(_bamboo_specs, 1):
        add_cyl_mm(f"B1_Garden_Bamboo_{_bi}", _bx, _by, _br, -1.17, _btop, mat_g_bamboo, col_b1, segs=10)
        # Bamboo node rings & airy sunlit foliage clusters at window height (-0.98..-0.54m)
        for _ni, _nz in enumerate([-0.96, -0.78, -0.60], 1):
            add_cyl_mm(f"B1_Garden_BambooNode_{_bi}_{_ni}", _bx, _by, _br + 2.5, _nz, _nz + 0.012, mat_g_leaf1, col_b1, segs=10)
        _add_garden_mound(f"B1_Garden_BambooLeafA_{_bi}", _bx - 90, _by + (55 if _bi % 2 else -55), -0.74 - 0.04 * (_bi % 3), 140, 180, 0.075, mat_g_leaf2 if _bi % 2 else mat_g_leaf1)
        _add_garden_mound(f"B1_Garden_BambooLeafB_{_bi}", _bx - 40, _by - (45 if _bi % 2 else -45), -0.58 - 0.03 * (_bi % 2), 125, 165, 0.065, mat_g_leaf1 if _bi % 2 else mat_g_leaf2)

    # Layered courtyard shrubs, Japanese maple accent & subtle garden blossoms framed in window view
    _shrub_specs = [
        (7260, -960, -0.98, 220, 260, 0.18, mat_g_leaf1),
        (7180, -560, -1.00, 210, 240, 0.16, mat_g_leaf2),
        (7360, -240, -0.92, 230, 260, 0.21, mat_g_leaf1),
        (7150,  160, -1.01, 200, 250, 0.16, mat_g_leaf2),
        (7340,  480, -0.93, 240, 270, 0.22, mat_g_leaf3),  # Warm Japanese maple accent shrub
        (7200,  860, -0.99, 210, 240, 0.17, mat_g_leaf1),
    ]
    for _si, (_sx, _sy, _sz, _srx, _sry, _srz, _smat) in enumerate(_shrub_specs, 1):
        add_cyl_mm(f"B1_Garden_ShrubStem_{_si}", _sx, _sy, 14.0, -1.17, _sz, mat_g_bark, col_b1, segs=8)
        _add_garden_mound(f"B1_Garden_Shrub_{_si}", _sx, _sy, _sz, _srx, _sry, _srz, _smat)
    # Soft white/blush camellia blossoms nestled into the mid-ground shrubs
    for _fi, (_fx, _fy, _fz) in enumerate([
        (7060, -640, -0.94), (7120, -490, -0.90), (7020, 120, -0.95),
        (7090,  250, -0.91), (7140,  780, -0.93),
    ], 1):
        _add_garden_mound(f"B1_Garden_Blossom_{_fi}", _fx, _fy, _fz, 36, 36, 0.032, mat_g_flower)

    # 2. South Side Underwater Fish-Pond Window (侧面鱼池窗: SAME width 2050mm as left window y=-4375..-2325, +20cm taller H=780mm z=-1.26..-0.48m)
    add_box_mm("B2_East_Win_Upper_Reveal_Bot",   6340, 6600, -4375, -2325, -1.26,  -1.224, MATS["OLO_ToeKick_Black"], col_b2)
    add_box_mm("B2_East_Win_Upper_Reveal_Top",   6340, 6600, -4375, -2325, -0.516, -0.48,  MATS["OLO_ToeKick_Black"], col_b2)
    add_box_mm("B2_East_Win_Upper_Reveal_South", 6340, 6600, -4375, -4338, -1.26,  -0.48,  MATS["OLO_ToeKick_Black"], col_b2)
    add_box_mm("B2_East_Win_Upper_Reveal_North", 6340, 6600, -2362, -2325, -1.26,  -0.48,  MATS["OLO_ToeKick_Black"], col_b2)
    add_box_mm("B2_East_Win_Upper_Glass",        6515, 6530, -4338, -2362, -1.224, -0.516, MATS["VentShaft_Clear_White_Glass"], col_b2)

    # Illuminated 3D Underwater Fish Pond Tank outside South Window (x: 6535..7350) with Golden & Silver Arowanas (金龙鱼 & 银龙鱼)
    mat_pond_water = make_mat("FishPond_Aqua_Glow", (0.12, 0.56, 0.68, 1.0), metallic=0.0, roughness=0.18, emission=(0.18, 0.68, 0.80, 1.0), emission_strength=0.95)
    mat_pond_sky   = make_mat("FishPond_Water_Top", (0.48, 0.88, 0.96, 1.0), metallic=0.0, roughness=0.12, emission=(0.55, 0.92, 1.00, 1.0), emission_strength=1.45)
    mat_pond_bed   = make_mat("FishPond_Gravel_Bed",(0.24, 0.34, 0.36, 1.0), metallic=0.0, roughness=0.72)
    mat_arowana_g  = make_mat("Arowana_Gold_Body",  (0.98, 0.72, 0.14, 1.0), metallic=0.88, roughness=0.18, emission=(0.95, 0.64, 0.10, 1.0), emission_strength=0.45)
    mat_arowana_gf = make_mat("Arowana_Gold_Fin",   (0.96, 0.36, 0.12, 1.0), metallic=0.35, roughness=0.28, emission=(0.92, 0.32, 0.08, 1.0), emission_strength=0.35)
    mat_arowana_s  = make_mat("Arowana_Silver_Body",(0.86, 0.91, 0.96, 1.0), metallic=0.92, roughness=0.14, emission=(0.76, 0.86, 0.96, 1.0), emission_strength=0.40)
    mat_arowana_sf = make_mat("Arowana_Silver_Fin", (0.72, 0.86, 0.94, 1.0), metallic=0.40, roughness=0.24, emission=(0.62, 0.80, 0.92, 1.0), emission_strength=0.30)

    add_box_mm("B2_FishPond_Tank_Back",   7320, 7360, -4380, -2320, -1.26, -0.48, mat_pond_water, col_b2)
    add_box_mm("B2_FishPond_Tank_SideS",  6535, 7360, -4380, -4345, -1.26, -0.48, mat_pond_water, col_b2)
    add_box_mm("B2_FishPond_Tank_SideN",  6535, 7360, -2355, -2320, -1.26, -0.48, mat_pond_water, col_b2)
    add_box_mm("B2_FishPond_Tank_Floor",  6535, 7360, -4380, -2320, -1.27, -1.224, mat_pond_bed, col_b2)
    add_box_mm("B2_FishPond_Tank_Surface",6535, 7360, -4380, -2320, -0.516, -0.475, mat_pond_sky, col_b2)

    def _add_arowana_fish(fname, fx_mm, fy_mm, fz_m, length_mm, dir_y, is_gold=True):
        """Sculpted elongated 3D Arowana (金龙鱼/银龙鱼) swimming along Y outside the East fish-pond window."""
        b_mat = mat_arowana_g if is_gold else mat_arowana_s
        f_mat = mat_arowana_gf if is_gold else mat_arowana_sf
        n_seg = 14
        half_l = 0.5 * length_mm
        bm_f = bmesh.new()
        rings_f = []
        for i in range(n_seg + 1):
            u = i / float(n_seg)  # 0 = snout, 1 = tail base
            ly = dir_y * (half_l - u * length_mm)
            # Graceful S-curve swimming wave in X
            sway_x = 18.0 * math.sin(u * 2.0 * math.pi) * (0.25 + 0.75 * u)
            # Streamlined laterally compressed dragon-fish body profile
            if u < 0.16:
                t_h = u / 0.16
                hw = 15.0 * math.sin(0.5 * math.pi * t_h) + 3.0
                hh = 38.0 * (0.35 + 0.65 * math.sin(0.5 * math.pi * t_h))
            else:
                t_t = (u - 0.16) / 0.84
                hw = 18.0 * ((1.0 - t_t) ** 0.75) + 2.5
                hh = 42.0 * ((1.0 - 0.78 * (t_t ** 1.15)))
            ring = []
            for k in range(8):
                ang = 2.0 * math.pi * k / 8.0
                vx = (fx_mm + sway_x + hw * math.cos(ang)) * MM
                vy = (fy_mm + ly) * MM
                vz = fz_m + (hh * math.sin(ang)) * MM
                ring.append(bm_f.verts.new((vx, vy, vz)))
            rings_f.append(ring)
        for i in range(n_seg):
            r0, r1 = rings_f[i], rings_f[i + 1]
            for k in range(8):
                kn = (k + 1) % 8
                f = bm_f.faces.new([r0[k], r0[kn], r1[kn], r1[k]])
                f.smooth = True
        bm_f.faces.new(rings_f[0][::-1])
        bm_f.faces.new(rings_f[-1])
        bmesh.ops.recalc_face_normals(bm_f, faces=bm_f.faces[:])
        m_f = bpy.data.meshes.new(f"{fname}_Body")
        bm_f.to_mesh(m_f)
        bm_f.free()
        o_f = bpy.data.objects.new(f"{fname}_Body", m_f)
        o_f.data.materials.append(b_mat)
        link_obj(o_f, col_b2)

        # Flowing fan-shaped tail fin (caudal) + long rear dorsal & anal fins + pectoral fins
        y_tail = fy_mm - dir_y * half_l
        y_tail_tip = y_tail - dir_y * (0.20 * length_mm)
        bm_fin = bmesh.new()
        def _add_fin_quad(p0, p1, p2, p3):
            vs = [bm_fin.verts.new((p[0]*MM, p[1]*MM, p[2])) for p in (p0, p1, p2, p3)]
            vs2 = [bm_fin.verts.new(((p[0]+5.0)*MM, p[1]*MM, p[2])) for p in (p0, p1, p2, p3)]
            bm_fin.faces.new(vs)
            bm_fin.faces.new(vs2[::-1])
            for k in range(4):
                kn = (k + 1) % 4
                bm_fin.faces.new([vs[k], vs[kn], vs2[kn], vs2[k]])
        # Caudal fan tail
        _add_fin_quad((fx_mm - 2.0, y_tail, fz_m - 0.014), (fx_mm - 2.0, y_tail, fz_m + 0.014),
                      (fx_mm + 8.0, y_tail_tip, fz_m + 0.056), (fx_mm + 8.0, y_tail_tip, fz_m - 0.056))
        # Long rear dorsal & anal ribbon fins (signature Arowana silhouette)
        y_d0 = fy_mm - dir_y * (0.14 * length_mm)
        y_d1 = fy_mm - dir_y * (0.48 * length_mm)
        _add_fin_quad((fx_mm - 2.0, y_d0, fz_m + 0.030), (fx_mm - 2.0, y_d1, fz_m + 0.016),
                      (fx_mm + 4.0, y_d1 - dir_y * 28.0, fz_m + 0.046), (fx_mm + 4.0, y_d0 - dir_y * 18.0, fz_m + 0.052))
        _add_fin_quad((fx_mm - 2.0, y_d0, fz_m - 0.030), (fx_mm - 2.0, y_d1, fz_m - 0.016),
                      (fx_mm + 4.0, y_d1 - dir_y * 28.0, fz_m - 0.048), (fx_mm + 4.0, y_d0 - dir_y * 18.0, fz_m - 0.052))
        # Swept pectoral wing fins near head
        y_pec = fy_mm + dir_y * (0.24 * length_mm)
        _add_fin_quad((fx_mm - 16.0, y_pec, fz_m - 0.020), (fx_mm - 16.0, y_pec - dir_y * 75.0, fz_m - 0.028),
                      (fx_mm - 52.0, y_pec - dir_y * 95.0, fz_m - 0.058), (fx_mm - 38.0, y_pec - dir_y * 18.0, fz_m - 0.042))
        bmesh.ops.recalc_face_normals(bm_fin, faces=bm_fin.faces[:])
        m_fin = bpy.data.meshes.new(f"{fname}_Fins")
        bm_fin.to_mesh(m_fin)
        bm_fin.free()
        o_fin = bpy.data.objects.new(f"{fname}_Fins", m_fin)
        o_fin.data.materials.append(f_mat)
        link_obj(o_fin, col_b2)

    # 2 Golden Arowanas (金龙鱼) & 2 Silver Arowanas (银龙鱼) swimming gracefully across the 2050x780mm window!
    _add_arowana_fish("B2_FishPond_GoldArowana_1",   6710.0, -2920.0, -0.76, 520.0, +1.0, is_gold=True)
    _add_arowana_fish("B2_FishPond_SilverArowana_1", 6860.0, -3720.0, -0.94, 490.0, -1.0, is_gold=False)
    _add_arowana_fish("B2_FishPond_GoldArowana_2",   6960.0, -3280.0, -1.06, 440.0, -1.0, is_gold=True)
    _add_arowana_fish("B2_FishPond_SilverArowana_2", 6740.0, -3960.0, -0.68, 460.0, +1.0, is_gold=False)

    # B1 ceiling: Enlarged Recessed Elliptical Cove Ceiling + Genuine OPEN HOLLOW Skylight Well above B2 Mahjong Table (x: 4695..6340, y: -5520..-2170)!
    # Split MainSlab_Cap (-0.02..0.00) and MainSlab (-0.08..-0.02) cleanly around the open skylight well!
    add_box_mm("B1_Ceiling_MainSlab_Cap_W",  -1520, 4695, -5690,  1410, -0.02, 0.00, plaster_mat, col_b1)
    add_box_mm("B1_Ceiling_MainSlab_Cap_NE",  4695, 6340, -2170,  1410, -0.02, 0.00, plaster_mat, col_b1)
    add_box_mm("B1_Ceiling_MainSlab_Cap_SE",  4695, 6340, -5690, -5520, -0.02, 0.00, plaster_mat, col_b1)
    add_box_mm("B1_Ceiling_MainSlab_W",       1380, 4695, -5690,  1410, -0.08, -0.02, plaster_mat, col_b1)
    add_box_mm("B1_Ceiling_MainSlab_NE",      4695, 6340, -2170,  1410, -0.08, -0.02, plaster_mat, col_b1)
    add_box_mm("B1_Ceiling_MainSlab_SE",      4695, 6340, -5690, -5520, -0.08, -0.02, plaster_mat, col_b1)
    add_box_mm("B1_Ceiling_MainSlab_SW",     -1520, 1380, -5690, -1350, -0.08, -0.02, plaster_mat, col_b1)
    add_box_mm("B1_Ceiling_Dropped_SW",      -1520, 1380, -5690, -1350, -0.15, -0.08, plaster_mat, col_b1)
    # Dropped ceiling west & south-rim pieces bordering the open Mahjong Skylight Well (x: 4695..6340, y: -5520..-2170 stays 100% HOLLOW!)
    add_box_mm("B1_Ceiling_Dropped_S_West",   1380, 4695, -5690, -2170, -0.15, -0.08, plaster_mat, col_b1)
    add_box_mm("B1_Ceiling_Dropped_S_Rim",    4695, 6340, -5690, -5520, -0.15, -0.08, plaster_mat, col_b1)
    # Crisp white plaster skylight well reveal + warm cove light framing the open shaft above B2 Mahjong Table
    add_box_mm("B1_Skylight_Reveal_W",  4675, 4695, -5520, -2170, -0.15, 0.00, plaster_mat, col_b1)
    add_box_mm("B1_Skylight_Reveal_N",  4695, 6340, -2170, -2150, -0.15, 0.00, plaster_mat, col_b1)
    add_box_mm("B1_Skylight_Reveal_S",  4695, 6340, -5540, -5520, -0.15, 0.00, plaster_mat, col_b1)
    add_box_mm("B1_Skylight_CoveLED_W", 4695, 4712, -5515, -2175, -0.145, -0.125, MATS["Warm_LED_Glow"], col_b1)
    add_box_mm("B1_Skylight_CoveLED_N", 4700, 6335, -2187, -2170, -0.145, -0.125, MATS["Warm_LED_Glow"], col_b1)
    add_box_mm("B1_Skylight_CoveLED_S", 4700, 6335, -5520, -5503, -0.145, -0.125, MATS["Warm_LED_Glow"], col_b1)

    cx_cove, cy_cove = 3450.0, -180.0
    a_cove, b_cove = 1750.0, 1150.0
    x_min_c, x_max_c = 1380.0, 6340.0
    y_min_c, y_max_c = -2170.0, 1410.0
    z_bot_c, z_top_c = -0.1500, -0.0800
    n_cove_base = 96

    def ray_box_intersect(cx, cy, dx, dy, x0, x1, y0, y1):
        t_cand = []
        if abs(dx) > 1e-6:
            t = ((x1 if dx > 0 else x0) - cx) / dx
            if y0 - 1e-3 <= cy + t * dy <= y1 + 1e-3:
                t_cand.append(t)
        if abs(dy) > 1e-6:
            t = ((y1 if dy > 0 else y0) - cy) / dy
            if x0 - 1e-3 <= cx + t * dx <= x1 + 1e-3:
                t_cand.append(t)
        pos = [t for t in t_cand if t > 0]
        return min(pos) if pos else 1.0

    raw_angs = [2.0 * math.pi * i / float(n_cove_base) for i in range(n_cove_base)]
    for cx_k, cy_k in ((x_min_c, y_min_c), (x_max_c, y_min_c), (x_max_c, y_max_c), (x_min_c, y_max_c)):
        ang_k = math.atan2(cy_k - cy_cove, cx_k - cx_cove) % (2.0 * math.pi)
        raw_angs.append(ang_k)
    raw_angs.sort()
    corner_angs = {math.atan2(cy_k - cy_cove, cx_k - cx_cove) % (2.0 * math.pi)
                   for cx_k, cy_k in ((x_min_c, y_min_c), (x_max_c, y_min_c), (x_max_c, y_max_c), (x_min_c, y_max_c))}
    cove_angs = []
    for a in raw_angs:
        if not cove_angs:
            cove_angs.append(a)
        elif abs(a - cove_angs[-1]) < 0.008:
            if any(abs(a - ck) < 1e-6 for ck in corner_angs):
                cove_angs[-1] = a
        else:
            cove_angs.append(a)
    if len(cove_angs) > 1 and (2.0 * math.pi - cove_angs[-1] + cove_angs[0]) < 0.008:
        if any(abs(cove_angs[0] - ck) < 1e-6 for ck in corner_angs):
            cove_angs.pop()
        else:
            cove_angs.pop(0)
    n_cove = len(cove_angs)

    mesh_cove = bpy.data.meshes.new("B1_Ceiling_Dropped_Plate")
    bm_cove = bmesh.new()

    inner_bot_v, inner_top_v, outer_bot_v, outer_top_v = [], [], [], []
    for ang in cove_angs:
        cos_a, sin_a = math.cos(ang), math.sin(ang)
        px = cx_cove + a_cove * cos_a
        py = cy_cove + b_cove * sin_a
        t_box = ray_box_intersect(cx_cove, cy_cove, cos_a, sin_a, x_min_c, x_max_c, y_min_c, y_max_c)
        qx = min(x_max_c, max(x_min_c, cx_cove + t_box * cos_a))
        qy = min(y_max_c, max(y_min_c, cy_cove + t_box * sin_a))
        inner_bot_v.append(bm_cove.verts.new((px * MM, py * MM, z_bot_c)))
        inner_top_v.append(bm_cove.verts.new((px * MM, py * MM, z_top_c)))
        outer_bot_v.append(bm_cove.verts.new((qx * MM, qy * MM, z_bot_c)))
        outer_top_v.append(bm_cove.verts.new((qx * MM, qy * MM, z_top_c)))

    for i in range(n_cove):
        i_next = (i + 1) % n_cove
        f_b = bm_cove.faces.new([outer_bot_v[i], inner_bot_v[i], inner_bot_v[i_next], outer_bot_v[i_next]])
        f_t = bm_cove.faces.new([outer_top_v[i_next], inner_top_v[i_next], inner_top_v[i], outer_top_v[i]])
        f_in = bm_cove.faces.new([inner_bot_v[i], inner_top_v[i], inner_top_v[i_next], inner_bot_v[i_next]])
        f_in.material_index = 1
        f_in.smooth = True
        f_out = bm_cove.faces.new([outer_bot_v[i_next], outer_top_v[i_next], outer_top_v[i], outer_bot_v[i]])

    bmesh.ops.recalc_face_normals(bm_cove, faces=bm_cove.faces[:])
    bm_cove.to_mesh(mesh_cove)
    bm_cove.free()
    obj_cove = bpy.data.objects.new("B1_Ceiling_Dropped_Plate", mesh_cove)
    obj_cove.data.materials.append(plaster_mat)
    obj_cove.data.materials.append(MATS["B1_Oval_Dome_White"])
    link_obj(obj_cove, col_b1)

    def add_elliptical_ring(rname, a_in, b_in, a_out, b_out, z0, z1, mat):
        mesh_er = bpy.data.meshes.new(rname)
        bm_er = bmesh.new()
        ib, it, ob, ot = [], [], [], []
        for ang in cove_angs:
            ca, sa = math.cos(ang), math.sin(ang)
            ib.append(bm_er.verts.new(((cx_cove + a_in * ca) * MM,  (cy_cove + b_in * sa) * MM,  z0)))
            it.append(bm_er.verts.new(((cx_cove + a_in * ca) * MM,  (cy_cove + b_in * sa) * MM,  z1)))
            ob.append(bm_er.verts.new(((cx_cove + a_out * ca) * MM, (cy_cove + b_out * sa) * MM, z0)))
            ot.append(bm_er.verts.new(((cx_cove + a_out * ca) * MM, (cy_cove + b_out * sa) * MM, z1)))
        for i in range(n_cove):
            i_n = (i + 1) % n_cove
            bm_er.faces.new([ob[i], ib[i], ib[i_n], ob[i_n]])
            bm_er.faces.new([ot[i_n], it[i_n], it[i], ot[i]])
            bm_er.faces.new([ib[i], it[i], it[i_n], ib[i_n]])
            bm_er.faces.new([ob[i_n], ot[i_n], ot[i], ob[i]])
        bmesh.ops.recalc_face_normals(bm_er, faces=bm_er.faces[:])
        bm_er.to_mesh(mesh_er)
        bm_er.free()
        obj_er = bpy.data.objects.new(rname, mesh_er)
        obj_er.data.materials.append(mat)
        link_obj(obj_er, col_b1)
        return obj_er

    pts_dome_center = [(cx_cove + a_cove * math.cos(ang), cy_cove + b_cove * math.sin(ang)) for ang in cove_angs]
    add_prism("B1_Ceiling_Oval_DomeLiner", pts_dome_center, -0.088, -0.080, MATS["B1_Oval_Dome_White"], col_b1)
    add_elliptical_ring("B1_Ceiling_Oval_Lip_Outer", a_cove - 30.0, b_cove - 30.0, a_cove + 40.0, b_cove + 40.0, -0.275, -0.245, MATS["Basement_Warm_Plaster"])
    add_elliptical_ring("B1_Ceiling_Oval_Glow",      a_cove - 12.0, b_cove - 12.0, a_cove + 18.0, b_cove + 18.0, -0.245, -0.220, MATS["Warm_LED_Glow"])

    # Flush perimeter downlights around enlarged oval + Recessed Black Magnetic Track east of dome (x: 5620..5680, y: -1450..+1250)
    dl_idx = 0
    for k_dl in range(8):
        ang_dl = 2.0 * math.pi * k_dl / 8.0 + math.pi / 8.0
        dlx = cx_cove + (a_cove + 160.0) * math.cos(ang_dl)
        dly = cy_cove + (b_cove + 160.0) * math.sin(ang_dl)
        if dly > 980.0 or dlx > 5450.0 or dlx < 1550.0:
            continue
        dl_idx += 1
        pts_dl = [(dlx + 38.0 * math.cos(2.0 * math.pi * j / 12.0), dly + 38.0 * math.sin(2.0 * math.pi * j / 12.0)) for j in range(12)]
        add_prism(f"B1_Ceiling_Oval_Downlight_{dl_idx}", pts_dl, -0.2630, -0.2590, MATS["OLO_ToeKick_Black"], col_b1)
    add_box_mm("B1_Ceiling_EastTrack_Housing", 5620.0, 5680.0, -1450.0, 1250.0, -0.2680, -0.2550, MATS["OLO_ToeKick_Black"], col_b1)
    for _ti, _ty in enumerate((-1100.0, -520.0, 100.0, 760.0)):
        add_box_mm(f"B1_Ceiling_EastTrack_BarLED_{_ti}", 5636.0, 5664.0, _ty - 140.0, _ty + 140.0, -0.2700, -0.2670, MATS["Warm_LED_Glow"], col_b1)

    # 5. B1 -> 1F Spiral Staircase (夹层到一楼的独立旋转楼梯, rev. 2026-11-24):
    # - Coaxially centered at (20, 20) with wide 930mm treads (r_in=460, r_out=1390) hugging BOTH West (-1375) and North (+1410) stairwell walls!
    # - Descends CLOCKWISE from 1F (deg_top=270.0°, x=20mm) -> 180° (West wall) -> 90.0° (bottom step strictly perpendicular to North wall cabinet at x=20mm)
    def build_b1_to_1f_spiral_stair(col_target):
        cx_sp, cy_sp = 20.0, 20.0
        r_in_sp, r_out_sp = 460.0, 1390.0
        deg_bot, deg_top = 90.0, 270.0
        n_st = 13
        n_seg_sp = 84
        z_bot_sp = -2.05
        dz = (0.00 - z_bot_sp) / float(n_st)
        marble_mat = MATS["Stair_Ink_Marble"]

        def sp_pt(r_mm, ang_deg):
            ar = math.radians(ang_deg)
            return (cx_sp + r_mm * math.cos(ar), cy_sp + r_mm * math.sin(ar))

        for s_i in range(n_st):
            t_a = s_i / float(n_st)
            t_b = 1.0 if s_i == n_st - 1 else (s_i + 1.03) / float(n_st)
            a1 = deg_bot + (deg_top - deg_bot) * t_a
            a2 = deg_bot + (deg_top - deg_bot) * t_b
            zb = z_bot_sp + s_i * dz
            zt = z_bot_sp + (s_i + 1) * dz
            p_in_a, p_out_a = sp_pt(r_in_sp, a1), sp_pt(r_out_sp, a1)
            p_in_b, p_out_b = sp_pt(r_in_sp, a2), sp_pt(r_out_sp, a2)
            add_stair_step_textured(
                f"B1_To_1F_Spiral_Tread_{s_i+1}",
                p_out_a, p_in_a, p_in_b, p_out_b,
                zt - 0.045, zt,
                marble_mat, col_target,
                step_idx=s_i, total_steps=n_st
            )
            t_r = t_a + 0.16 / float(n_st)
            a_r = deg_bot + (deg_top - deg_bot) * t_r
            p_in_r, p_out_r = sp_pt(r_in_sp, a_r), sp_pt(r_out_sp, a_r)
            add_prism(f"B1_To_1F_Spiral_Riser_{s_i+1}", [p_out_a, p_in_a, p_in_r, p_out_r], zb, zt - 0.045, plaster_mat, col_target)
            add_prism(f"B1_To_1F_Spiral_LED_{s_i+1}",   [p_out_a, p_in_a, p_in_r, p_out_r], zt - 0.058, zt - 0.046, MATS["Warm_LED_Glow"], col_target)

        # Continuous smooth white plaster helical soffit locked tightly into tread undersides (zero air gap!)
        mesh_sp_sof = bpy.data.meshes.new("B1_To_1F_Spiral_WhiteSoffit")
        bm_sps = bmesh.new()
        rings_sps = []
        for k in range(n_seg_sp + 1):
            t = k / float(n_seg_sp)
            ang_d = deg_bot + (deg_top - deg_bot) * t
            zc = z_bot_sp + (0.00 - z_bot_sp) * t
            z_top = min(-0.015, zc + dz * 0.85)
            z_bot = zc - 0.180
            pin  = sp_pt(r_in_sp, ang_d)
            pout = sp_pt(r_out_sp, ang_d)
            v0 = bm_sps.verts.new((pout[0]*MM, pout[1]*MM, z_bot))
            v1 = bm_sps.verts.new((pin[0]*MM,  pin[1]*MM,  z_bot))
            v2 = bm_sps.verts.new((pin[0]*MM,  pin[1]*MM,  z_top))
            v3 = bm_sps.verts.new((pout[0]*MM, pout[1]*MM, z_top))
            rings_sps.append((v0, v1, v2, v3))
        for k in range(n_seg_sp):
            r0, r1 = rings_sps[k], rings_sps[k+1]
            for s in range(4):
                bm_sps.faces.new([r0[s], r0[(s+1)%4], r1[(s+1)%4], r1[s]])
        bm_sps.faces.new(list(rings_sps[0])[::-1])
        bm_sps.faces.new(list(rings_sps[-1]))
        bmesh.ops.recalc_face_normals(bm_sps, faces=bm_sps.faces[:])
        bm_sps.to_mesh(mesh_sp_sof)
        bm_sps.free()
        for p in mesh_sp_sof.polygons:
            p.use_smooth = True
        obj_sps = bpy.data.objects.new("B1_To_1F_Spiral_WhiteSoffit", mesh_sp_sof)
        obj_sps.data.materials.append(plaster_mat)
        link_obj(obj_sps, col_target)

        # Structural wall-anchor cleats locking the spiral stair into West (-1375) and North (+1410) walls
        add_box_mm("B1_To_1F_Spiral_WallCleat_W", -1375.0, -1345.0, -240.0, 280.0, -1.24, -0.78, MATS["Gold_Brass"], col_target)
        add_box_mm("B1_To_1F_Spiral_WallCleat_N", -260.0, 20.0, 1380.0, 1410.0, -2.20, -1.88, MATS["Gold_Brass"], col_target)

        def build_helical_ribbon(rname, r_a_mm, r_b_mm, z_off_bot, z_off_top, mat):
            mesh_hr = bpy.data.meshes.new(rname)
            bm_hr = bmesh.new()
            rings_hr = []
            for k in range(n_seg_sp + 1):
                t = k / float(n_seg_sp)
                ang_d = deg_bot + (deg_top - deg_bot) * t
                zc = z_bot_sp + (0.00 - z_bot_sp) * t
                zb = zc + z_off_bot
                zt = zc + z_off_top
                pa = sp_pt(r_a_mm, ang_d)
                pb = sp_pt(r_b_mm, ang_d)
                v0 = bm_hr.verts.new((pa[0]*MM, pa[1]*MM, zb))
                v1 = bm_hr.verts.new((pb[0]*MM, pb[1]*MM, zb))
                v2 = bm_hr.verts.new((pb[0]*MM, pb[1]*MM, zt))
                v3 = bm_hr.verts.new((pa[0]*MM, pa[1]*MM, zt))
                rings_hr.append((v0, v1, v2, v3))
            for k in range(n_seg_sp):
                r0, r1 = rings_hr[k], rings_hr[k+1]
                for s in range(4):
                    bm_hr.faces.new([r0[s], r0[(s+1)%4], r1[(s+1)%4], r1[s]])
            bm_hr.faces.new(list(rings_hr[0])[::-1])
            bm_hr.faces.new(list(rings_hr[-1]))
            bmesh.ops.recalc_face_normals(bm_hr, faces=bm_hr.faces[:])
            bm_hr.to_mesh(mesh_hr)
            bm_hr.free()
            for p in mesh_hr.polygons:
                p.use_smooth = (abs(p.normal.z) < 0.7)
            obj_hr = bpy.data.objects.new(rname, mesh_hr)
            obj_hr.data.materials.append(mat)
            link_obj(obj_hr, col_target)
            return obj_hr

        # Left / Outer Helical Balustrade: Structural Champagne-Gold Metallic Plate outside White Fascia (zero coplanar Z-fighting!)
        build_helical_ribbon("B1_To_1F_Spiral_OuterFascia",     r_out_sp - 16.0, r_out_sp + 8.0,  -0.18,  0.02, MATS["Basement_Warm_Plaster"])
        build_helical_ribbon("B1_To_1F_Spiral_OuterBalustrade", r_out_sp + 8.5,  r_out_sp + 22.0, -0.18,  0.95, MATS["Gold_Brass"])
        build_helical_ribbon("B1_To_1F_Spiral_OuterSoffitGlow", r_out_sp - 6.0,  r_out_sp + 6.0,  -0.19, -0.16, MATS["Warm_LED_Glow"])

        # Right / Inner Helical Balustrade: White Fascia + Plain Curved Clear Glass (NO gold cap on glass!)
        build_helical_ribbon("B1_To_1F_Spiral_InnerFascia",     r_in_sp - 14.0,  r_in_sp + 14.0,  -0.18,  0.02, MATS["Basement_Warm_Plaster"])
        build_helical_ribbon("B1_To_1F_Spiral_InnerGlass",      r_in_sp - 9.0,   r_in_sp + 9.0,    0.02,  0.92, MATS["Glass_Balustrade_Clear"])

    build_b1_to_1f_spiral_stair(col_b1)

    # Note: B1_Chandelier_Ribbon placeholder removed to keep sightlines clear to B1 bookcase,
    # replaced by central woven mesh leaf pendants descending through the grand stairwell void.

    def build_basement_grand_stair(col_target):
        # 14-step C1-continuous S-curve B1->B2 Grand Staircase (rev. 2026-11-27):
        # - Top starting step (x=20..820mm, y=480mm) touches the exact X=20mm parallel line of 1F->B1 Tread_1 at B1_Mezz_NW_Arrival
        # - Bottom landing anchored solidly onto B2 marble floor (z=-4.55m, x: 1860..2660, y=-840) clear of B2 gym mat & sofa
        # - Open underside (踏步下镂空) with continuous 220mm curved carriage + concealed steel spine + front closed risers + full-depth clamping stringers!
        n_total = 14
        n_ccw = 4
        n_str = 3
        n_segs = 120
        z_top_gs = -2.05
        dz_step = (z_top_gs - z_b2) / float(n_total)
        w_half = 500.0        # Exact 1.0 m (1000 mm) tread width!
        C_top = (1120.0, -620.0)
        r_top = 600.0
        L_str = 440.0
        C_bot = (1560.0, -1940.0)
        r_bot = 720.0
        u1 = float(n_ccw) / float(n_total)
        u2 = float(n_ccw + n_str) / float(n_total)

        def stair_frame_desc(u_desc):
            """Parameter u_desc in [0=top B1, 1=bottom B2]. Returns (p_outer_left, p_inner_right, z_m, n_out, n_in)."""
            uc = max(0.0, min(1.0, float(u_desc)))
            z_m = z_top_gs + (z_b2 - z_top_gs) * uc
            if uc <= u1:
                s = uc / u1
                ang = math.radians(180.0 + 90.0 * s)
                rx, ry = math.cos(ang), math.sin(ang)
                tx, ty = -ry, rx
                xc = C_top[0] + r_top * rx
                yc = C_top[1] + r_top * ry
            elif uc <= u2:
                s = (uc - u1) / (u2 - u1)
                tx, ty = 1.0, 0.0
                xc = C_top[0] + s * L_str
                yc = C_top[1] - r_top
            else:
                s = (uc - u2) / (1.0 - u2)
                ang = math.radians(90.0 - 90.0 * s)
                rx, ry = math.cos(ang), math.sin(ang)
                tx, ty = ry, -rx
                xc = C_bot[0] + r_bot * rx
                yc = C_bot[1] + r_bot * ry
            n_out = (-ty, tx)  # Left when descending = outer/concave-slab edge
            n_in  = (ty, -tx)  # Right when descending = inner curved side
            return (xc + w_half * n_out[0], yc + w_half * n_out[1]), (xc + w_half * n_in[0], yc + w_half * n_in[1]), z_m, n_out, n_in

        marble_mat = MATS["Stair_Ink_Marble"]

        # 14 Steps (index s_i=0 bottom on B2 floor .. 13 top flush at B1 -2.05m!)
        for s_i in range(n_total):
            u_top = 1.0 - (s_i + 1) / float(n_total)
            u_bot = 1.0 - s_i / float(n_total)
            po_hi, pi_hi, z_t, _, _ = stair_frame_desc(u_top)
            po_lo, pi_lo, z_b, _, _ = stair_frame_desc(u_bot)
            add_stair_step_textured(
                f"B2_GrandStair_Tread_{s_i+1}",
                po_lo, pi_lo, pi_hi, po_hi,
                z_t - 0.045, z_t,
                marble_mat, col_target,
                step_idx=s_i, total_steps=n_total
            )
            # FRONT riser at u_bot connecting z_b (Step 1 = -4.55m B2 floor!) seamlessly up to z_t - 0.045 (no floating overhang!)
            u_r_back = max(u_top, u_bot - 0.015)
            u_r_front = max(u_top, u_bot - 0.004)
            po_rb, pi_rb, _, _, _ = stair_frame_desc(u_r_back)
            po_rf, pi_rf, _, _, _ = stair_frame_desc(u_r_front)
            add_prism(f"B2_GrandStair_Riser_{s_i+1}", [po_rf, pi_rf, pi_rb, po_rb], z_b, z_t - 0.045, plaster_mat, col_target)
            add_prism(f"B2_GrandStair_LED_{s_i+1}",   [po_lo, pi_lo, pi_rf, po_rf], z_t - 0.056, z_t - 0.045, MATS["Warm_LED_Glow"], col_target)

        # Continuous monolithic curved structural carriage locking tightly into every step underside (open/hollow below -220mm!)
        mesh_sof = bpy.data.meshes.new("B2_GrandStair_WhiteSoffit")
        bm_sof = bmesh.new()
        rings_sof = []
        for k in range(n_segs + 1):
            u = k / float(n_segs)
            po, pi, zc, _, _ = stair_frame_desc(u)
            z_top = min(z_top_gs - 0.050, zc - 0.048)
            z_bot = max(z_b2, zc - 0.220)
            v0 = bm_sof.verts.new((po[0]*MM, po[1]*MM, z_bot))
            v1 = bm_sof.verts.new((pi[0]*MM, pi[1]*MM, z_bot))
            v2 = bm_sof.verts.new((pi[0]*MM, pi[1]*MM, z_top))
            v3 = bm_sof.verts.new((po[0]*MM, po[1]*MM, z_top))
            rings_sof.append((v0, v1, v2, v3))
        for k in range(n_segs):
            r0, r1 = rings_sof[k], rings_sof[k+1]
            for s in range(4):
                bm_sof.faces.new([r0[s], r0[(s+1)%4], r1[(s+1)%4], r1[s]])
        bm_sof.faces.new(list(rings_sof[0])[::-1])
        bm_sof.faces.new(list(rings_sof[-1]))
        bmesh.ops.recalc_face_normals(bm_sof, faces=bm_sof.faces[:])
        bm_sof.to_mesh(mesh_sof)
        bm_sof.free()
        for p in mesh_sof.polygons:
            p.use_smooth = True
        obj_sof = bpy.data.objects.new("B2_GrandStair_WhiteSoffit", mesh_sof)
        obj_sof.data.materials.append(plaster_mat)
        link_obj(obj_sof, col_target)

        # Central Concealed Structural Steel Box-Spine beneath carriage (hollow/open beneath!)
        mesh_spn = bpy.data.meshes.new("B2_GrandStair_SteelSpine")
        bm_spn = bmesh.new()
        rings_spn = []
        for k in range(n_segs + 1):
            u = k / float(n_segs)
            po, pi, zc, _, _ = stair_frame_desc(u)
            cx_m = 0.5 * (po[0] + pi[0])
            cy_m = 0.5 * (po[1] + pi[1])
            dx_s = po[0] - pi[0]
            dy_s = po[1] - pi[1]
            L_s = math.hypot(dx_s, dy_s) or 1.0
            nx_s, ny_s = dx_s / L_s, dy_s / L_s
            sa_p = (cx_m - 120.0 * nx_s, cy_m - 120.0 * ny_s)
            sb_p = (cx_m + 120.0 * nx_s, cy_m + 120.0 * ny_s)
            zb_s = max(z_b2, zc - 0.285)
            zt_s = max(z_b2 + 0.02, zc - 0.190)
            rings_spn.append((
                bm_spn.verts.new((sb_p[0]*MM, sb_p[1]*MM, zb_s)),
                bm_spn.verts.new((sa_p[0]*MM, sa_p[1]*MM, zb_s)),
                bm_spn.verts.new((sa_p[0]*MM, sa_p[1]*MM, zt_s)),
                bm_spn.verts.new((sb_p[0]*MM, sb_p[1]*MM, zt_s)),
            ))
        for k in range(n_segs):
            r0, r1 = rings_spn[k], rings_spn[k+1]
            for s in range(4):
                bm_spn.faces.new([r0[s], r0[(s+1)%4], r1[(s+1)%4], r1[s]])
        bm_spn.faces.new(list(rings_spn[0])[::-1])
        bm_spn.faces.new(list(rings_spn[-1]))
        bmesh.ops.recalc_face_normals(bm_spn, faces=bm_spn.faces[:])
        bm_spn.to_mesh(mesh_spn)
        bm_spn.free()
        for p in mesh_spn.polygons:
            p.use_smooth = True
        obj_spn = bpy.data.objects.new("B2_GrandStair_SteelSpine", mesh_spn)
        obj_spn.data.materials.append(plaster_mat)
        link_obj(obj_spn, col_target)

        # Top B1 Mezzanine Embed Anchor & Bottom B2 Floor Base Plinth Anchor (shifted further 1000mm South toward B2 sofa!)
        add_box_mm("B2_GrandStair_B1Anchor",    20.0, 1020.0, -640.0, -500.0, -2.24, -2.06, plaster_mat, col_target)
        add_box_mm("B2_GrandStair_FloorAnchor", 1832.0, 2688.0, -1965.0, -1700.0, z_b2, z_b2 + 0.035, MATS["Gold_Brass"], col_target)

        def build_grand_side_ribbon(rname, use_inner_side, off_a_mm, off_b_mm, z_off_bot, z_off_top, mat, u_start=0.0):
            mesh_gr = bpy.data.meshes.new(rname)
            bm_gr = bmesh.new()
            rings_gr = []
            for k in range(n_segs + 1):
                u = u_start + (1.0 - u_start) * (k / float(n_segs))
                po, pi, zc, n_out, n_in = stair_frame_desc(u)
                base_p = pi if use_inner_side else po
                nv = n_in if use_inner_side else n_out
                pa = (base_p[0] + off_a_mm * nv[0], base_p[1] + off_a_mm * nv[1])
                pb = (base_p[0] + off_b_mm * nv[0], base_p[1] + off_b_mm * nv[1])
                zb = max(z_b2, zc + z_off_bot)
                zt = zc + z_off_top
                rings_gr.append((
                    bm_gr.verts.new((pa[0]*MM, pa[1]*MM, zb)),
                    bm_gr.verts.new((pb[0]*MM, pb[1]*MM, zb)),
                    bm_gr.verts.new((pb[0]*MM, pb[1]*MM, zt)),
                    bm_gr.verts.new((pa[0]*MM, pa[1]*MM, zt)),
                ))
            for k in range(n_segs):
                r0, r1 = rings_gr[k], rings_gr[k+1]
                for s in range(4):
                    bm_gr.faces.new([r0[s], r0[(s+1)%4], r1[(s+1)%4], r1[s]])
            bm_gr.faces.new(list(rings_gr[0])[::-1])
            bm_gr.faces.new(list(rings_gr[-1]))
            bmesh.ops.recalc_face_normals(bm_gr, faces=bm_gr.faces[:])
            bm_gr.to_mesh(mesh_gr)
            bm_gr.free()
            for p in mesh_gr.polygons:
                p.use_smooth = (abs(p.normal.z) < 0.7)
            obj_gr = bpy.data.objects.new(rname, mesh_gr)
            obj_gr.data.materials.append(mat)
            link_obj(obj_gr, col_target)
            return obj_gr

        # Full-depth clamping side stringers (non-overlapping bands to eliminate Z-fighting!)
        build_grand_side_ribbon("B2_GrandStair_LeftFascia",      False, -6.0, 16.0, -0.225, 0.02, plaster_mat)
        build_grand_side_ribbon("B2_GrandStair_LeftGlass",       False,  2.0, 16.0,  0.022, 0.92, MATS["Glass_Balustrade_Clear"])
        build_grand_side_ribbon("B2_GrandStair_RightFascia",     True,  -6.0, 14.0, -0.225, 0.02, plaster_mat, u_start=0.0)
        build_grand_side_ribbon("B2_GrandStair_RightGoldPlate",  True,  14.5, 32.0, -0.225, 0.95, MATS["Gold_Brass"], u_start=0.0)

        # Stairwell Hanging Pendants: Centered strictly inside 1F->B1 spiral core (x < 20mm) clearing B1->B2 stair!
        for pi in range(9):
            pang = pi * (2.0 * math.pi / 9.0)
            px = -240.0 + 135.0 * math.cos(pang)
            py = 20.0 + 135.0 * math.sin(pang)
            pz_top = -0.15
            pz_bot = -1.15 - 0.16 * (pi % 3)
            add_cyl_mm(f"B1_Stairwell_Pendant_Wire_{pi+1}",  px, py, 2.0, pz_bot, pz_top, MATS["Gold_Brass"], col_b1, segs=8)
            add_box_mm(f"B1_Stairwell_Pendant_Leaf_{pi+1}",  px - 52.0, px + 52.0, py - 38.0, py + 38.0, pz_bot - 0.28, pz_bot, MATS["Gold_Brass"], col_b1, r_corner=20.0)
            add_cyl_mm(f"B1_Stairwell_Pendant_Light_{pi+1}", px, py, 20.0, pz_bot - 0.22, pz_bot - 0.06, MATS["Warm_LED_Glow"], col_b1, segs=16)

    build_basement_grand_stair(col_b2)
    # B2 CAD linework removed per user requirement (去掉地下室CAD印记线)
    # add_cad_linework_curve(msp, "B2", p_b2["xr"], p_b2["yr"], *p_b2["orig"], z_b2 + 0.008, col_b2)
    # add_cad_linework_curve(msp, "B1", p_b1["xr"], p_b1["yr"], *p_b1["orig"], z_b1 + 0.008, col_b1)  # removed 2026-10-28: thin CAD lines around the B1 mezzanine slab

    # =========================================================================
    # FLOOR 3: 1F_一层 (Ground Floor, z0 = 0.00m, h = 3.15m)
    # Strictly calibrated to manual survey annotations in WechatIMG6.pdf!
    # =========================================================================
    col_1f = bpy.data.collections.new("1F_一层")
    bpy.context.scene.collection.children.link(col_1f)
    cols["1F_Plan"] = col_1f
    p_1f = PLANS["1F_Plan"]
    z_1f, h_1f = p_1f["z0"], p_1f["h"]
    zf_1f = z_1f + 0.005

    # 1F West Slab: Kitchen + Foyer + Dining + 360x1240 West Niche (extended SW corner to -4950 for SW sink alcove)
    pts_1f_west = [
        (-7035, -4950), (-1488, -4950), (-1488, 380), (-5674, 380),
        (-5674, -1085), (-7035, -1085)
    ]
    # 1F Floor Slabs finished in solid White-Celadon Marble (白青色纯色大理石):
    add_prism("1F_Slab_West", pts_1f_west, z_1f - 0.15, z_1f, MATS["Floor_Celadon_White_Marble"], col_1f)
    # 1F Toilet Slab
    add_box_mm("1F_Slab_Toilet", -1488, 743, -5640, -4263, z_1f - 0.15, z_1f, MATS["Slab_Tile_Bath"], col_1f)
    # 1F Living South Slab
    add_prism("1F_Slab_Living_South", [(743, -5640), (4695, -5640), (4695, -1750), (743, -1750)], z_1f - 0.15, z_1f, MATS["Floor_Celadon_White_Marble"], col_1f)
    add_box_mm("1F_Slab_Fireplace", 4695, 6620, -2170, -1750, z_1f - 0.15, z_1f, MATS["Floor_Celadon_White_Marble"], col_1f)

    # 1F Living North Slab + Crossing + Stairwell Landing
    add_box_mm("1F_Slab_Crossing", -1488, 743, -4263, -1620, z_1f - 0.15, z_1f, MATS["Floor_Celadon_White_Marble"], col_1f)
    add_box_mm("1F_Slab_Living_North", 1432, 6620, -1750, 1620, z_1f - 0.15, z_1f, MATS["Floor_Celadon_White_Marble"], col_1f)
    add_box_mm("1F_Slab_Living_Mid", 743, 1432, -1750, -1380, z_1f - 0.15, z_1f, MATS["Floor_Celadon_White_Marble"], col_1f)
    pts_1f_landing = []
    for k in range(15):
        a = math.radians(-90.0 + 115.0 * k / 14.0)
        pts_1f_landing.append((20.0 + 460.0 * math.cos(a), 20.0 + 460.0 * math.sin(a)))
    pts_1f_landing.extend([(1430, 610), (1430, -1380), (20, -1380)])
    add_prism("1F_Slab_Stair_Landing", pts_1f_landing, z_1f - 0.15, z_1f, MATS["Floor_Celadon_White_Marble"], col_1f)

    # 1F Curved Stairwell Frameless Plain Glass Guard around SW of Spiral Stair (-1568..-1488 and arc 180°..270° to -418, 无扶手平白玻璃)
    pts_sp_curb = arc_band_poly(-728.0, -830.0, 760.0, -728.0, -830.0, 840.0, 180.0, 270.0, n=18)
    add_prism("1F_StairGuard_Curb_Arc", pts_sp_curb, zf_1f, z_1f + 0.10, MATS["Counter_Marble"], col_1f)
    add_box_mm("1F_StairGuard_Curb_W", -1568, -1488, -830, 260, zf_1f, z_1f + 0.10, MATS["Counter_Marble"], col_1f)
    add_box_mm("1F_StairGuard_Curb_S", -728, -418, -1670, -1590, zf_1f, z_1f + 0.10, MATS["Counter_Marble"], col_1f)
    pts_sp_glass = arc_band_poly(-728.0, -830.0, 790.0, -728.0, -830.0, 810.0, 180.0, 270.0, n=18)
    add_prism("1F_StairGuard_Glass_Arc", pts_sp_glass, z_1f + 0.102, z_1f + 1.05, MATS["Window_Glass"], col_1f)
    add_box_mm("1F_StairGuard_Glass_W", -1538, -1518, -830, 260, z_1f + 0.102, z_1f + 1.05, MATS["Window_Glass"], col_1f)
    add_box_mm("1F_StairGuard_Glass_S", -728, -418, -1640, -1620, z_1f + 0.102, z_1f + 1.05, MATS["Window_Glass"], col_1f)

    # 1F Exact Calibrated Wall Rectangles per WechatIMG6.pdf manual survey:
    # - Dining N wall = 3706mm (x: -5194..-1488, y: 260..500)
    # - Dining W niche = 360 x 1240mm (x: -5554..-5194, y: -980..260; W wall x: -5794..-5554, 360x360 col y: -100..260)
    # - Foyer N wall = 1721mm (x: -6915..-5194) & 210mm thick step wall (y: -1190..-980)
    # - West wall: 200mm N pier (y: -1390..-1190) + 1430mm Entry Door (y: -2820..-1390) + 310mm S pier (y: -3130..-2820) + 1740mm Kitchen W wall (y: -4870..-3130)
    # - Kitchen-Dining total N-S inner span = 4905mm (y: -4645..+260; Kitchen S wall y: -5070..-4645)
    # - Steam/Oven + Fridge niche = 1083 x 600mm (x: -2088..-1488, y: -4045..-2962; enclosed by N wall y: -2962..-2762 with 535mm return & E wall x: -1488..-1288)
    # - 1F Toilet: 450mm S step (y: -5520..-5070), 2000mm W-E width (x: -1488..+512), 1070mm W wall (y: -5520..-4450),
    #   570mm step under Fridge (x: -1488..-918), 830mm N door (x: -718..+112), 1257mm E double-wall (x: +512..+743, y: -5520..-4263)
    # - Staircase: 3162mm W opening (y: -2902..+260), 1265mm NW wall (y: 260..1525), 1710mm N wall (x: -1488..+222),
    #   cols 447mm (222..669), 309mm (669..978), 373mm gap (978..1351)
    # - Living N wall = 5210mm (x: 1292..6502, y: 1525..1765), NE pier = 330mm (y: 1195..1525)
    # - Living S wall = 5759mm (x: 743..6502, y: -5760..-5520)
    # - Ventilation Shaft = 3350 x 1807mm (x: 4695..6502, y: -5520..-2170), Fireplace = 420 x 1807mm (y: -2170..-1750), SE pier = 383mm (y: -1750..-1367)
    c1f_walls = [
        # Dining Room North wall (3706mm) & NW corner
        (-5794.0, -1488.0,   260.0,   500.0, 1),
        # Dining West Niche (360 x 1240mm) West wall + 360x360 duct column
        (-5794.0, -5554.0,  -980.0,   260.0, 1),
        (-5554.0, -5194.0,  -100.0,   260.0, 1),
        # 210mm step wall South of Niche & 1721mm Foyer North wall (x: -6915..-5194, y: -1190..-980)
        (-7155.0, -5194.0, -1190.0,  -980.0, 1),
        # West Exterior Wall (200mm N pier + 1430mm Door + 310mm S pier + 1740mm Kitchen SW wall)
        (-7155.0, -6915.0, -4870.0, -1190.0, 1),
        # Kitchen South Wall: stepped-out 225mm SW sink alcove (x: -7155..-5480, inner y=-4870) + main South wall (-5480..-1488, inner y=-4645)
        (-7155.0, -5480.0, -5070.0, -4870.0, 1),
        (-5480.0, -1488.0, -5070.0, -4645.0, 1),
        # Steam/Oven + Fridge Niche (1083 x 600mm) Partition Walls
        (-2088.0, -1488.0, -2962.0, -2762.0, 2),  # 535mm N return wall enclosing Fridge pocket
        (-1488.0, -1288.0, -4645.0, -2762.0, 2),  # E partition wall behind Fridge/Oven
        # 1F Toilet West Wall (450mm S step y: -5520..-5070, 1070mm inner W wall y: -5520..-4450)
        (-1728.0, -1488.0, -5760.0, -4450.0, 1),
        # 1F Toilet 570mm step under Fridge pocket (x: -1488..-918, y: -4450..-4263)
        (-1488.0,  -918.0, -4450.0, -4263.0, 2),
        # 1F Toilet North Wall with 830mm Doorway (x: -718..+112)
        ( -918.0,  +512.0, -4400.0, -4263.0, 2),
        # 1F Toilet East Double-Wall (1257mm length: y: -5520..-4263, x: +512..+743)
        ( +512.0,  +743.0, -5520.0, -4263.0, 2),
        # 1F Toilet & Living Room South Exterior Wall (Toilet 2000mm + Living 5759mm: x: -1728..+6742, y: -5760..-5520)
        (-1728.0, +6742.0, -5760.0, -5520.0, 1),
        # Staircase NW Wall (1265mm: y: +260..+1525, x: -1728..-1488)
        (-1728.0, -1488.0,  +260.0, +1765.0, 1),
        # Staircase & Living Room North Wall (continuous from x=-1488 to +6742 at y=+1525..+1765, plus column step 669..978)
        (-1488.0, +6742.0, +1525.0, +1765.0, 1),
        ( +669.0,  +978.0, +1465.0, +1765.0, 1),
        # Living Room & Ventilation Shaft East Exterior Wall (continuous from S corner y=-5760 to N corner y=+1765)
        (+6502.0, +6742.0, -5760.0, +1765.0, 1),
    ]
    c1f_cutouts = [
        (-7165, -6905, -2820, -1390), # Main Entry Door (1430mm: y = -2820..-1390)
        (-7165, -6905, -4350, -3450), # Kitchen West Window (in 1740mm wall segment)
        (-6650, -5750, -5080, -4860), # Kitchen SW Sink Alcove South Window
        (-1735, -1480, -5350, -4750), # Toilet West Window (in 1070mm wall segment)
        ( -718,  +112, -4410, -4255), # 1F Toilet North Door (830mm: x = -718..+112)
        (+6495, +6750, -1367, +1195), # Living Room East Window (between 383mm SE pier & 330mm NE pier)
        (+6495, +6750, -5520, -2170), # Vent shaft East side: full-height clear glass wall (rev. 2026-10-28)
    ]
    build_manifold_walls(
        msp, "1F_Plan", p_1f["xr"], p_1f["yr"], *p_1f["orig"],
        z_1f + 0.002, h_1f, c1f_cutouts, col_1f, override_rects=c1f_walls
    )

    # -------------------------------------------------------------------------
    # 1F Ventilation Shaft (通风井: 3350 x 1807mm, x: 4695..6502, y: -5520..-2170)
    # Completely open/unobstructed void from 1F straight down to the basement (全透无遮挡),
    # with only a simple frameless plain clear glass barrier (无扶手平白玻璃) along its West edge.
    # -------------------------------------------------------------------------
    # 1F vent shaft east side: one seamless floor-to-slab pure white transparent glass pane with crisp white tracks/posts
    add_box_mm("1F_VentShaft_Glass_Balustrade", 4685.0, 4705.0, -5520.0, -2170.0, zf_1f, z_1f + 1.0800, MATS["VentShaft_Clear_White_Glass"], col_1f)
    add_box_mm("1F_VentShaft_EastGlass", 6616.0, 6628.0, -5520.0, -2170.0, z_1f + 0.0020, z_1f + 3.1520, MATS["VentShaft_Clear_White_Glass"], col_1f)
    add_box_mm("1F_VentShaft_EastGlass_BottomTrack", 6602.0, 6642.0, -5520.0, -2170.0, z_1f + 0.0020, z_1f + 0.0520, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_VentShaft_EastGlass_TopTrack", 6602.0, 6642.0, -5520.0, -2170.0, z_1f + 3.1020, z_1f + 3.1520, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_VentShaft_EastGlass_Post_0", 6502.0, 6742.0, -5520.0, -5480.0, z_1f + 0.0020, z_1f + 3.1520, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_VentShaft_EastGlass_Post_3", 6502.0, 6742.0, -2210.0, -2170.0, z_1f + 0.0020, z_1f + 3.1520, MATS["Wall_Panel_White"], col_1f)

    build_window("1F_Win_Kitchen",   -7155, -6915, -4350, -3450, z_1f + 0.002, h_1f, 1.10, 1.85, col_1f)
    build_window("1F_Win_Kitchen_S", -6650, -5750, -5070, -4870, z_1f + 0.002, h_1f, 1.10, 1.85, col_1f)
    build_window("1F_Win_Toilet",    -1728, -1488, -5350, -4750, z_1f + 0.002, h_1f, 0.97, 1.76, col_1f)
    build_window("1F_Win_Living_E",  +6502, +6742, -1367, +1195, z_1f + 0.002, h_1f, 0.14, 2.55, col_1f)
    add_box_mm("1F_Win_Living_E_SunSky", +6736, +6752, -1365, +1193, z_1f + 0.142, z_1f + 2.690, MATS["East_Win_Sunlight_Sky"], col_1f)

    build_door("1F_Main_Entry_Door", -7155, -6915, -2820, -1390, z_1f + 0.002, h_1f, 2.35, col_1f)
    # build_door("1F_Toilet_Door", -718, +112, -4400, -4263, z_1f + 0.002, h_1f, 2.20, col_1f)  # replaced by hidden flush door (rev. 2026-10-28)
    # 1F toilet hidden flush white door + full-height white wall cladding (rev. 2026-11-22: kept flush hidden door per user request)
    add_box_mm("1F_Toilet_HiddenDoor_Header", -718.0, 112.0, -4400.0, -4263.0, z_1f + 2.2000, z_1f + 3.1520, MATS["Wall_New"], col_1f)
    add_box_mm("1F_Toilet_Clad_A_Backing", -1288.0, 763.0, -4263.0, -4258.0, z_1f + 0.0050, z_1f + 3.1500, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Toilet_Clad_A0_Lo", -1288.0, -719.5, -4258.0, -4243.0, z_1f + 0.0650, z_1f + 2.1970, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_A0_Up", -1288.0, -719.5, -4258.0, -4243.0, z_1f + 2.2030, z_1f + 3.1100, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_HiddenDoor_Leaf", -716.5, 110.5, -4300.0, -4243.0, z_1f + 0.0650, z_1f + 2.1970, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_A_OverDoor", -716.5, 110.5, -4258.0, -4243.0, z_1f + 2.2030, z_1f + 3.1100, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_A2_Lo", 113.5, 310.5, -4258.0, -4243.0, z_1f + 0.0650, z_1f + 2.1970, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_A2_Up", 113.5, 310.5, -4258.0, -4243.0, z_1f + 2.2030, z_1f + 3.1100, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_A3_Lo", 313.5, 763.0, -4258.0, -4243.0, z_1f + 0.0650, z_1f + 2.1970, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_A3_Up", 313.5, 763.0, -4258.0, -4243.0, z_1f + 2.2030, z_1f + 3.1100, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Skirt_A_L", -1288.0, -718.0, -4243.0, -4233.0, z_1f + 0.0050, z_1f + 0.0650, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Toilet_Skirt_A_R", 112.0, 773.0, -4243.0, -4233.0, z_1f + 0.0050, z_1f + 0.0650, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Toilet_Crown_A", -1288.0, 773.0, -4243.0, -4233.0, z_1f + 3.1100, z_1f + 3.1500, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Toilet_Clad_B_Backing", 743.0, 748.0, -5520.0, -4258.0, z_1f + 0.0050, z_1f + 3.1500, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Toilet_Clad_B0_Lo", 748.0, 763.0, -5520.0, -4561.5, z_1f + 0.0650, z_1f + 2.1970, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_B0_Up", 748.0, 763.0, -5520.0, -4561.5, z_1f + 2.2030, z_1f + 3.1100, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_B1_Lo", 748.0, 763.0, -4558.5, -4258.0, z_1f + 0.0650, z_1f + 2.1970, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_B1_Up", 748.0, 763.0, -4558.5, -4258.0, z_1f + 2.2030, z_1f + 3.1100, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Skirt_B", 763.0, 773.0, -5520.0, -4233.0, z_1f + 0.0050, z_1f + 0.0650, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Toilet_Crown_B", 763.0, 773.0, -5520.0, -4233.0, z_1f + 3.1100, z_1f + 3.1500, MATS["OLO_ToeKick_Black"], col_1f)

    def build_1f_living_fireplace_wall():
        """Build 1F living room south feature wall flush against the original south wall (y=-5520mm)
        with sculptural white circular moon-gate, seamless pale-gold plum wallpaper, and 50cm cantilevered linear fireplace."""
        x_min, x_max = 763.0, 4684.0
        cx = 0.5 * (x_min + x_max)  # 2723.5 mm
        cz_mm = 1170.0
        z_bot_mm = 5.0
        z_ceil_rel = 2.570
        z_top_mm = z_ceil_rel * 1000.0
        r_ring = 1080.0
        r_wp = 1105.0
        y_wall_front = -5420.0
        y_wall_back = -5520.0
        y_fp_back = -5520.0

        # Lowered 50cm linear fireplace dimensions
        z_fb_bot_rel = 0.360
        z_hearth_rel = 0.500
        z_fb_top_rel = 0.860
        fb_half_w = 760.0
        r_fb = 155.0
        n_arc = 18

        def arc_pts(acx, acz, rad, deg0, deg1, steps):
            pts = []
            for k in range(steps + 1):
                a = math.radians(deg0 + (deg1 - deg0) * k / float(steps))
                pts.append((acx + rad * math.cos(a), acz + rad * math.sin(a)))
            return pts

        # 1. Sculptural White Plaster Circular Moon-Gate Wall (180-seg smooth radial quads + 12-seg quarter fillet)
        angles = [-math.pi + (2.0 * math.pi * k) / 180.0 for k in range(180)]
        for cpx, cpz in ((x_max, z_top_mm), (x_min, z_top_mm), (x_min, z_bot_mm), (x_max, z_bot_mm)):
            angles.append(math.atan2(cpz - cz_mm, cpx - cx))
        angles.sort()
        uniq_angles = []
        for th in angles:
            if not uniq_angles or abs(th - uniq_angles[-1]) > 1e-4:
                uniq_angles.append(th)

        # Cross-section rings from wall back perimeter around true 12-segment quarter-circle reveal fillet to front wall face
        r_fillet = 55.0
        y_f0 = y_wall_front - r_fillet  # -5475.0
        n_fil = 12
        prof_specs = [
            # (radial_offset_or_rect, y_mm, smooth_to_next)
            ("rect", y_wall_back, False),
            (r_ring, y_wall_back, True),
        ]
        for fi in range(n_fil):
            phi = (0.5 * math.pi) * (fi / float(n_fil))
            prof_specs.append((r_ring + r_fillet * (1.0 - math.cos(phi)), y_f0 + r_fillet * math.sin(phi), True))
        prof_specs.extend([
            (r_ring + r_fillet, y_wall_front, False),
            ("rect", y_wall_front, False),
        ])

        mesh_mg = bpy.data.meshes.new("1F_Living_Fireplace_MoonGateWall")
        bm_mg = bmesh.new()
        rings_v = []
        for th in uniq_angles:
            ct, st = math.cos(th), math.sin(th)
            tx = (x_max - cx) / ct if ct > 1e-8 else ((x_min - cx) / ct if ct < -1e-8 else 1e9)
            tz = (z_top_mm - cz_mm) / st if st > 1e-8 else ((z_bot_mm - cz_mm) / st if st < -1e-8 else 1e9)
            t_rect = min(tx, tz)
            ring = []
            for r_spec, py_mm, _ in prof_specs:
                rr = t_rect if r_spec == "rect" else r_spec
                px_m = (cx + rr * ct) * MM
                pz_m = z_1f + (cz_mm + rr * st) * MM
                ring.append(bm_mg.verts.new((px_m, py_mm * MM, pz_m)))
            rings_v.append(ring)

        n_th = len(rings_v)
        n_pr = len(prof_specs)
        for k in range(n_th):
            kn = (k + 1) % n_th
            r0, r1 = rings_v[k], rings_v[kn]
            for pi in range(n_pr):
                pin = (pi + 1) % n_pr
                face = bm_mg.faces.new([r0[pi], r1[pi], r1[pin], r0[pin]])
                face.smooth = prof_specs[pi][2]

        bmesh.ops.recalc_face_normals(bm_mg, faces=bm_mg.faces[:])
        sharp_mg = [
            e for e in bm_mg.edges
            if len(e.link_faces) == 2 and (
                e.link_faces[0].smooth != e.link_faces[1].smooth
                or e.link_faces[0].normal.dot(e.link_faces[1].normal) < 0.72
            )
        ]
        if sharp_mg:
            bmesh.ops.split_edges(bm_mg, edges=sharp_mg)
        bm_mg.to_mesh(mesh_mg)
        bm_mg.free()
        obj_mg = bpy.data.objects.new("1F_Living_Fireplace_MoonGateWall", mesh_mg)
        obj_mg.data.materials.append(MATS["Fireplace_Wall_Plaster"])
        link_obj(obj_mg, col_1f)

        # Clean ceiling structural cap & concealed warm LED cove ring + floor wash strip
        add_box_mm("1F_Living_Fireplace_TopCap", x_min, x_max, y_wall_back, y_wall_front, z_1f + z_ceil_rel, z_1f + 2.940, MATS["Wall_New"], col_1f)
        # Floor base warm cove wash along the bottom edge of the moon-gate wall (matching 图1's warm uplight)
        add_box_mm("1F_Living_Fireplace_FloorLED", x_min + 20.0, x_max - 20.0, y_wall_front - 2.0, y_wall_front + 8.0, z_1f + 0.005, z_1f + 0.022, MATS["Warm_LED_Glow"], col_1f)

        # Build true 3D perimeter Warm LED glow ring behind inner moon-gate lip (r: R_ring+2..R_ring+16)
        mesh_mled = bpy.data.meshes.new("1F_Living_Fireplace_MoonLED")
        bm_ml = bmesh.new()
        ml_segs = 180
        ml_rings = []
        for k in range(ml_segs):
            a = 2.0 * math.pi * k / float(ml_segs)
            ca, sa = math.cos(a), math.sin(a)
            pts_ml = []
            for rr, yy in [(r_ring + 2.0, y_wall_back + 8.0), (r_ring + 16.0, y_wall_back + 8.0), (r_ring + 16.0, y_wall_back + 20.0), (r_ring + 2.0, y_wall_back + 20.0)]:
                pts_ml.append(bm_ml.verts.new(((cx + rr * ca) * MM, yy * MM, z_1f + (cz_mm + rr * sa) * MM)))
            ml_rings.append(pts_ml)
        for k in range(ml_segs):
            kn = (k + 1) % ml_segs
            r0, r1 = ml_rings[k], ml_rings[kn]
            for pi in range(4):
                pin = (pi + 1) % 4
                bm_ml.faces.new([r0[pi], r1[pi], r1[pin], r0[pin]]).smooth = True
        bmesh.ops.recalc_face_normals(bm_ml, faces=bm_ml.faces[:])
        bm_ml.to_mesh(mesh_mled)
        bm_ml.free()
        obj_ml = bpy.data.objects.new("1F_Living_Fireplace_MoonLED", mesh_mled)
        obj_ml.data.materials.append(MATS["Warm_LED_Glow"])
        link_obj(obj_ml, col_1f)

        # 2. Continuous Solid Polar Circular Antique Gold-Foil Plum Wallpaper Backdrop inside Moon-Gate (180-seg true circle)
        mesh_wp = bpy.data.meshes.new("1F_Living_Fireplace_LingnanWallpaper")
        bm_wp = bmesh.new()
        uv_wp = bm_wp.loops.layers.uv.new("UVMap")
        y_wp0, y_wp1 = (y_wall_back + 1.0) * MM, (y_wall_back + 11.0) * MM

        def wp_uv(xm, zm):
            xmm = xm / MM
            zmm = (zm - z_1f) / MM
            u_v = 1.0 - (xmm - (cx - r_ring)) / (2.0 * r_ring)
            v_v = (zmm - (cz_mm - r_ring)) / (2.0 * r_ring)
            return (u_v, v_v)

        n_disc = 180
        radii_wp = [0.35 * r_wp, 0.70 * r_wp, r_wp]
        vf_c = bm_wp.verts.new((cx * MM, y_wp1, z_1f + cz_mm * MM))
        vb_c = bm_wp.verts.new((cx * MM, y_wp0, z_1f + cz_mm * MM))
        rings_f = []
        rings_b = []
        for rr in radii_wp:
            rf = []
            rb = []
            for k in range(n_disc):
                a = 2.0 * math.pi * k / float(n_disc)
                xm_v = (cx + rr * math.cos(a)) * MM
                zm_v = z_1f + (cz_mm + rr * math.sin(a)) * MM
                rf.append(bm_wp.verts.new((xm_v, y_wp1, zm_v)))
                rb.append(bm_wp.verts.new((xm_v, y_wp0, zm_v)))
            rings_f.append(rf)
            rings_b.append(rb)

        for k in range(n_disc):
            kn = (k + 1) % n_disc
            for fverts in (
                [vf_c, rings_f[0][kn], rings_f[0][k]],
                [vb_c, rings_b[0][k], rings_b[0][kn]],
            ):
                f = bm_wp.faces.new(fverts)
                f.smooth = False
                for lp in f.loops:
                    lp[uv_wp].uv = wp_uv(lp.vert.co.x, lp.vert.co.z)
            for ri in range(len(radii_wp) - 1):
                for fverts in (
                    [rings_f[ri][k], rings_f[ri][kn], rings_f[ri + 1][kn], rings_f[ri + 1][k]],
                    [rings_b[ri][kn], rings_b[ri][k], rings_b[ri + 1][k], rings_b[ri + 1][kn]],
                ):
                    f = bm_wp.faces.new(fverts)
                    f.smooth = False
                    for lp in f.loops:
                        lp[uv_wp].uv = wp_uv(lp.vert.co.x, lp.vert.co.z)
            f_rim = bm_wp.faces.new([rings_b[-1][k], rings_f[-1][k], rings_f[-1][kn], rings_b[-1][kn]])
            f_rim.smooth = True
            for lp in f_rim.loops:
                lp[uv_wp].uv = wp_uv(lp.vert.co.x, lp.vert.co.z)

        bmesh.ops.recalc_face_normals(bm_wp, faces=bm_wp.faces[:])
        sharp_wp = [e for e in bm_wp.edges if len(e.link_faces) == 2 and e.link_faces[0].normal.dot(e.link_faces[1].normal) < 0.72]
        if sharp_wp:
            bmesh.ops.split_edges(bm_wp, edges=sharp_wp)
        bm_wp.to_mesh(mesh_wp)
        bm_wp.free()
        obj_wp = bpy.data.objects.new("1F_Living_Fireplace_LingnanWallpaper", mesh_wp)
        obj_wp.data.materials.append(MATS["Fireplace_Lingnan_Wallpaper"])
        link_obj(obj_wp, col_1f)

        # 3. Cantilevered Floating Marble Stone Hearth Shelf protruding into Living Room (top at 50 cm: z_hearth_rel = 0.500 m)
        z_cant_bot_rel = 0.340
        z_cant_top_rel = 0.500
        cant_half_w = 780.0
        r_cant = 140.0
        h_arc_l = arc_pts(cx - cant_half_w + r_cant, z_cant_bot_rel * 1000.0 + r_cant, r_cant, 180.0, 270.0, n_arc)
        h_arc_r = arc_pts(cx + cant_half_w - r_cant, z_cant_bot_rel * 1000.0 + r_cant, r_cant, 270.0, 360.0, n_arc)
        hearth_poly = h_arc_l + h_arc_r + [(cx + cant_half_w, z_cant_top_rel * 1000.0), (cx - cant_half_w, z_cant_top_rel * 1000.0)]
        mesh_h = bpy.data.meshes.new("1F_Living_Fireplace_Hearth")
        bm_h = bmesh.new()
        hy0_m = -5510.0 * MM
        hy1_m = -5140.0 * MM
        h_vb = [bm_h.verts.new((px * MM, hy0_m, z_1f + pz * MM)) for (px, pz) in hearth_poly]
        h_vf = [bm_h.verts.new((px * MM, hy1_m, z_1f + pz * MM)) for (px, pz) in hearth_poly]
        fb_h = bm_h.faces.new(list(reversed(h_vb)))
        ff_h = bm_h.faces.new(h_vf)
        for idx in range(len(hearth_poly)):
            jn = (idx + 1) % len(hearth_poly)
            fs_h = bm_h.faces.new([h_vb[idx], h_vb[jn], h_vf[jn], h_vf[idx]])
            fs_h.smooth = (hearth_poly[idx][1] < z_cant_top_rel * 1000.0 - 2.0 and hearth_poly[jn][1] < z_cant_top_rel * 1000.0 - 2.0)
        bmesh.ops.triangulate(bm_h, faces=[fb_h, ff_h], quad_method='BEAUTY', ngon_method='BEAUTY')
        uv_h = bm_h.loops.layers.uv.new("UVMap")
        hw_m = max(0.2, 2.0 * cant_half_w * MM)
        hh_m = max(0.05, (z_cant_top_rel - z_cant_bot_rel))
        for f in bm_h.faces:
            for l in f.loops:
                co = l.vert.co
                u_val = (co.x - (cx - cant_half_w) * MM) / hw_m
                if abs(f.normal.z) > 0.7:
                    v_val = (co.y - hy0_m) / max(0.05, hy1_m - hy0_m)
                else:
                    v_val = (co.z - (z_1f + z_cant_bot_rel)) / hh_m
                l[uv_h].uv = (u_val, v_val)
        bmesh.ops.recalc_face_normals(bm_h, faces=bm_h.faces[:])
        bm_h.to_mesh(mesh_h)
        bm_h.free()
        obj_h = bpy.data.objects.new("1F_Living_Fireplace_Hearth", mesh_h)
        obj_h.data.materials.append(MATS["Marble_Fishbelly"])
        link_obj(obj_h, col_1f)

        # Concealed warm under-hearth cove LED strip + Open Linear Burner + Flames + Low-Iron Glass Guard on Hearth Top
        add_box_mm("1F_Living_Fireplace_HearthLED", cx - 620.0, cx + 620.0, -5480.0, -5450.0, z_1f + z_cant_bot_rel - 0.008, z_1f + z_cant_bot_rel, MATS["Warm_LED_Glow"], col_1f)
        add_box_mm(
            "1F_Living_Fireplace_Burner",
            cx - 560.0, cx + 560.0,
            -5340.0, -5245.0,
            z_1f + z_cant_top_rel, z_1f + z_cant_top_rel + 0.013,
            MATS["Fireplace_Ember_Bed"], col_1f
        )
        add_box_mm(
            "1F_Living_Fireplace_GlassGuard",
            cx - 580.0, cx + 580.0,
            -5228.0, -5218.0,
            z_1f + z_cant_top_rel, z_1f + z_cant_top_rel + 0.105,
            MATS["Glass_Balustrade_Clear"], col_1f
        )
        add_uv_front_box_mm(
            "1F_Living_Fireplace_Flame_1",
            cx - 530.0, cx + 530.0,
            -5300.0, -5298.0,
            z_1f + z_cant_top_rel + 0.007, z_1f + z_cant_top_rel + 0.240,
            0.0, 1.0, 0.0, 1.0,
            MATS["Fireplace_Flame_Card"], col_1f
        )
        add_uv_front_box_mm(
            "1F_Living_Fireplace_Flame_2",
            cx - 530.0, cx + 530.0,
            -5278.0, -5276.0,
            z_1f + z_cant_top_rel + 0.007, z_1f + z_cant_top_rel + 0.220,
            0.08, 1.08, 0.0, 1.0,
            MATS["Fireplace_Flame_Card"], col_1f
        )

    build_1f_living_fireplace_wall()
    add_box_mm("1F_Toilet_Clad_D_Backing", -1288.0, -1283.0, -4243.0, -2762.0, z_1f + 0.0050, z_1f + 3.1500, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Toilet_Clad_D0_Lo", -1283.0, -1268.0, -4243.0, -3754.5, z_1f + 0.0650, z_1f + 2.1970, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_D0_Up", -1283.0, -1268.0, -4243.0, -3754.5, z_1f + 2.2030, z_1f + 3.1100, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_D1_Lo", -1283.0, -1268.0, -3751.5, -3259.5, z_1f + 0.0650, z_1f + 2.1970, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_D1_Up", -1283.0, -1268.0, -3751.5, -3259.5, z_1f + 2.2030, z_1f + 3.1100, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_D2_Lo", -1283.0, -1268.0, -3256.5, -2762.0, z_1f + 0.0650, z_1f + 2.1970, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Clad_D2_Up", -1283.0, -1268.0, -3256.5, -2762.0, z_1f + 2.2030, z_1f + 3.1100, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Toilet_Skirt_D", -1268.0, -1258.0, -4233.0, -2762.0, z_1f + 0.0050, z_1f + 0.0650, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Toilet_Crown_D", -1268.0, -1258.0, -4233.0, -2762.0, z_1f + 3.1100, z_1f + 3.1500, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Foyer_Clad_N_Backing", -6915.0, -5194.0, -1195.0, -1190.0, z_1f + 0.0050, z_1f + 3.1500, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Foyer_Clad_N0_Lo", -6915.0, -6342.5, -1210.0, -1195.0, z_1f + 0.0650, z_1f + 2.1970, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Foyer_Clad_N0_Up", -6915.0, -6342.5, -1210.0, -1195.0, z_1f + 2.2030, z_1f + 3.1100, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Foyer_Clad_N1_Lo", -6339.5, -5769.5, -1210.0, -1195.0, z_1f + 0.0650, z_1f + 2.1970, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Foyer_Clad_N1_Up", -6339.5, -5769.5, -1210.0, -1195.0, z_1f + 2.2030, z_1f + 3.1100, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Foyer_Clad_N2_Lo", -5766.5, -5194.0, -1210.0, -1195.0, z_1f + 0.0650, z_1f + 2.1970, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Foyer_Clad_N2_Up", -5766.5, -5194.0, -1210.0, -1195.0, z_1f + 2.2030, z_1f + 3.1100, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Foyer_Skirt_N", -6915.0, -5164.0, -1220.0, -1210.0, z_1f + 0.0050, z_1f + 0.0650, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Foyer_Crown_N", -6915.0, -5164.0, -1220.0, -1210.0, z_1f + 3.1100, z_1f + 3.1500, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Toilet_Sconce_Plate", 763.0, 778.0, -5010.0, -4890.0, z_1f + 1.0500, z_1f + 1.7500, MATS["Stair_Bronze_Iron"], col_1f)
    add_box_mm("1F_Toilet_Sconce_SideS", 778.0, 812.0, -5010.0, -4985.0, z_1f + 1.0500, z_1f + 1.7500, MATS["Stair_Bronze_Iron"], col_1f)
    add_box_mm("1F_Toilet_Sconce_SideN", 778.0, 812.0, -4915.0, -4890.0, z_1f + 1.0500, z_1f + 1.7500, MATS["Stair_Bronze_Iron"], col_1f)
    add_box_mm("1F_Toilet_Sconce_Bot", 778.0, 812.0, -4985.0, -4915.0, z_1f + 1.0500, z_1f + 1.1000, MATS["Stair_Bronze_Iron"], col_1f)
    add_box_mm("1F_Toilet_Sconce_Top", 778.0, 812.0, -4985.0, -4915.0, z_1f + 1.7000, z_1f + 1.7500, MATS["Stair_Bronze_Iron"], col_1f)
    add_box_mm("1F_Toilet_Sconce_Glow", 778.0, 800.0, -4985.0, -4915.0, z_1f + 1.1000, z_1f + 1.7000, MATS["Warm_LED_Glow"], col_1f)

    # -------------------------------------------------------------------------
    # 1F OLO Kitchen, Island & Foyer Cabinetry (strictly matching reference front rendering & WechatIMG6.pdf)
    # -------------------------------------------------------------------------
    # 1. Right (West) Foyer Partition Shoe Cabinet (310mm slim pier-aligned depth y: -3130..-2820 + 430 x 500mm East column)
    #   - Left 430x500mm full-height matte greige column (x: -5429..-4999, y: -3225..-2725)
    add_box_mm("1F_Foyer_Col_East", -5429, -4999, -3225, -2725, zf_1f, z_1f + 3.15, MATS["OLO_Cab_Greige"], col_1f)
    #   - Center Framed See-Through Plant Niche Section (x: -6172..-5429, y: -3130..-2820)
    add_box_mm("1F_Foyer_Mid_BotDoorL", -5798, -5432, -3130, -2820, zf_1f, z_1f + 0.88, MATS["OLO_Cab_Greige"], col_1f)
    add_box_mm("1F_Foyer_Mid_BotDoorR", -6170, -5802, -3130, -2820, zf_1f, z_1f + 0.88, MATS["OLO_Cab_Greige"], col_1f)
    add_box_mm("1F_Foyer_Mid_TopHeader", -6172, -5429, -3130, -2820, z_1f + 2.02, z_1f + 3.15, MATS["OLO_Cab_Greige"], col_1f)
    # 1F foyer niche: ultra-clear glass in a champagne-bronze grid (rev. 2026-10-29, generated by f1_foyerglass_spec.py)
    add_box_mm("1F_Foyer_GlassGrid_Bot", -6172.0, -5429.0, -3135.0, -2815.0, z_1f + 0.8800, z_1f + 0.9150, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_Top", -6172.0, -5429.0, -3135.0, -2815.0, z_1f + 1.9850, z_1f + 2.0200, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_W", -6172.0, -6137.0, -3135.0, -2815.0, z_1f + 0.9150, z_1f + 1.9850, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_E", -5464.0, -5429.0, -3135.0, -2815.0, z_1f + 0.9150, z_1f + 1.9850, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_ClearGlass_N", -6137.0, -5464.0, -2843.0, -2835.0, z_1f + 0.9150, z_1f + 1.9850, MATS["Window_Glass"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_N_V0", -6011.4, -5993.4, -2835.0, -2817.0, z_1f + 0.9150, z_1f + 1.9850, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_N_V1", -5607.6, -5589.6, -2835.0, -2817.0, z_1f + 0.9150, z_1f + 1.9850, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_N_H0", -6137.0, -5464.0, -2835.0, -2817.0, z_1f + 1.0558, z_1f + 1.0738, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_N_H1", -6137.0, -5464.0, -2835.0, -2817.0, z_1f + 1.6978, z_1f + 1.7158, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_N_H2", -6137.0, -5464.0, -2835.0, -2817.0, z_1f + 1.8476, z_1f + 1.8656, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_ClearGlass_S", -6137.0, -5464.0, -3115.0, -3107.0, z_1f + 0.9150, z_1f + 1.9850, MATS["Window_Glass"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_S_V0", -6011.4, -5993.4, -3133.0, -3115.0, z_1f + 0.9150, z_1f + 1.9850, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_S_V1", -5607.6, -5589.6, -3133.0, -3115.0, z_1f + 0.9150, z_1f + 1.9850, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_S_H0", -6137.0, -5464.0, -3133.0, -3115.0, z_1f + 1.0558, z_1f + 1.0738, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_S_H1", -6137.0, -5464.0, -3133.0, -3115.0, z_1f + 1.6978, z_1f + 1.7158, MATS["Glass_Grid_Bronze"], col_1f)
    add_box_mm("1F_Foyer_GlassGrid_S_H2", -6137.0, -5464.0, -3133.0, -3115.0, z_1f + 1.8476, z_1f + 1.8656, MATS["Glass_Grid_Bronze"], col_1f)
    #   - Decorative green bamboo stalks & foliage standing inside the see-through niche
    for b_idx, (bx, by, bh) in enumerate([(-5760, -2980, 1.88), (-5820, -2965, 1.82), (-5790, -2995, 1.91), (-5850, -2975, 1.76)]):
        add_cyl_mm(f"1F_Foyer_Bamboo_Stem_{b_idx}", bx, by, 8.0, z_1f + 0.916, z_1f + bh, MATS["Plant_Bamboo_Green"], col_1f, segs=12)
        for l_z in [1.15, 1.32, 1.48, 1.64, 1.78]:
            if l_z < bh:
                add_box_mm(f"1F_Foyer_Bamboo_Leaf_{b_idx}_{int(l_z*100)}", bx - 120, bx + 120, by - 45, by + 45, z_1f + l_z, z_1f + l_z + 0.035, MATS["Plant_Bamboo_Green"], col_1f, r_corner=12.0)
    #   - Right Full-Height Double-Door Storage Section (x: -6915..-6172, y: -3130..-2820)
    add_box_mm("1F_Foyer_West_TallDoorL", -6541, -6174, -3130, -2820, zf_1f, z_1f + 2.02, MATS["OLO_Cab_Greige"], col_1f)
    add_box_mm("1F_Foyer_West_TallDoorR", -6915, -6545, -3130, -2820, zf_1f, z_1f + 2.02, MATS["OLO_Cab_Greige"], col_1f)
    add_box_mm("1F_Foyer_West_TopHeader", -6915, -6172, -3130, -2820, z_1f + 2.02, z_1f + 3.15, MATS["OLO_Cab_Greige"], col_1f)

    # 2. Left (East) Built-in Toshiba Obsidian Black Dual-Door Refrigerator & White Overhead Cabinet (x: -2088..-1488, y: -3750..-2962)
    add_box_mm("1F_Kitchen_Fridge_ToeKick",      -2045, -1488, -3750, -2962, zf_1f,        z_1f + 0.05,  MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Kitchen_Fridge_Carcass",      -2065, -1488, -3750, -2962, z_1f + 0.05,  z_1f + 1.882, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Kitchen_Fridge_UpperCarcass", -2065, -1488, -3750, -2962, z_1f + 1.882, z_1f + 2.45,  MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_Fridge_DoorN",        -2088, -2065, -3352, -2966, z_1f + 0.052, z_1f + 1.878, MATS["Toshiba_Obsidian_Black"], col_1f, r_corner=4.0)
    add_box_mm("1F_Kitchen_Fridge_DoorS",        -2088, -2065, -3746, -3360, z_1f + 0.052, z_1f + 1.878, MATS["Toshiba_Obsidian_Black"], col_1f, r_corner=4.0)
    add_box_mm("1F_Kitchen_Fridge_PocketTrimN",  -2089, -2065, -3352, -3345, z_1f + 0.68,  z_1f + 1.48,  MATS["Toshiba_Obsidian_Trim"], col_1f)
    add_box_mm("1F_Kitchen_Fridge_PocketTrimS",  -2089, -2065, -3367, -3360, z_1f + 0.68,  z_1f + 1.48,  MATS["Toshiba_Obsidian_Trim"], col_1f)
    add_box_mm("1F_Kitchen_Fridge_WaistTrim",    -2089, -2065, -3744, -2968, z_1f + 0.885, z_1f + 0.897, MATS["Toshiba_Obsidian_Trim"], col_1f)
    add_box_mm("1F_Kitchen_Fridge_DisplayLED",   -2090, -2087, -3195, -3120, z_1f + 1.38,  z_1f + 1.46,  MATS["B2_CoolWhite_LED"], col_1f)
    #   - White overhead cabinet double doors above fridge (z: 1.885..2.45m)
    add_box_mm("1F_Kitchen_Fridge_UpperCabN", -2088, -2065, -3354, -2966, z_1f + 1.885, z_1f + 2.45, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_Fridge_UpperCabS", -2088, -2065, -3746, -3358, z_1f + 1.885, z_1f + 2.45, MATS["OLO_Cab_White"], col_1f)

    # 3. Built-in Tall Steam/Oven Tower at SE Corner (x: -2688..-2088, y: -4645..-4045, facing North toward dining room as in front rendering)
    add_box_mm("1F_Kitchen_SE_CornerFiller", -2088, -1488, -4645, -3750, zf_1f, z_1f + 2.45, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_OvenTower_ToeKick", -2688, -2088, -4645, -4085, zf_1f, z_1f + 0.08, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Kitchen_OvenTower_Body",    -2688, -2088, -4645, -4065, z_1f + 0.08, z_1f + 2.45, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_OvenTower_BotDrw1", -2684, -2092, -4065, -4045, z_1f + 0.082, z_1f + 0.34, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_OvenTower_Slot1",   -2684, -2092, -4065, -4048, z_1f + 0.34,  z_1f + 0.37, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Kitchen_OvenTower_BotDrw2", -2684, -2092, -4065, -4045, z_1f + 0.37,  z_1f + 0.62, MATS["OLO_Cab_White"], col_1f)
    #   - White middle built-in appliance / warming drawer (z: 0.625..0.96m)
    add_box_mm("1F_Kitchen_OvenTower_WhiteApp", -2684, -2092, -4065, -4043, z_1f + 0.625, z_1f + 0.96, MATS["Sanitary_White"], col_1f)
    #   - Dark gray/black glass Double Steamer & Oven (z: 0.965..1.58m) with horizontal handles
    add_box_mm("1F_Kitchen_OvenTower_DarkOven1", -2684, -2092, -4065, -4042, z_1f + 0.965, z_1f + 1.27, MATS["OLO_Oven_DarkGlass"], col_1f)
    add_box_mm("1F_Kitchen_OvenTower_Handle1",   -2480, -2296, -4042, -4028, z_1f + 1.18,  z_1f + 1.20, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Kitchen_OvenTower_DarkOven2", -2684, -2092, -4065, -4042, z_1f + 1.275, z_1f + 1.58, MATS["OLO_Oven_DarkGlass"], col_1f)
    add_box_mm("1F_Kitchen_OvenTower_Handle2",   -2480, -2296, -4042, -4028, z_1f + 1.49,  z_1f + 1.51, MATS["OLO_ToeKick_Black"], col_1f)
    #   - White upper cabinet door above steamer/oven (z: 1.585..2.38m) + soffit header (z: 2.38..2.45m)
    add_box_mm("1F_Kitchen_OvenTower_TopDoor",   -2684, -2092, -4065, -4045, z_1f + 1.585, z_1f + 2.38, MATS["OLO_Cab_White"], col_1f)

    # 4. Slim L-Shaped Kitchen Base Counter (480mm deep), SW Sink Alcove, Black Backsplash, Gas Hob, Slim Range Hood & Upper Cabinets
    #   - West Leg (480mm deep: x: -6915..-6435, y: -4870..-3130)
    add_box_mm("1F_Kitchen_W_ToeKick", -6915, -6485, -4870, -3130, zf_1f, z_1f + 0.08, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Kitchen_Counter_W", -6915, -6445, -4870, -3130, z_1f + 0.08, z_1f + 0.86, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_Counter_W_Top", -6915, -6435, -4870, -3130, z_1f + 0.862, z_1f + 0.89, MATS["Sanitary_White"], col_1f)
    #   - SW Sink Alcove Counter Extension & Recessed Sink + Faucet (x: -6445..-5480, y: -4870..-4645)
    add_box_mm("1F_Kitchen_SW_Carcass", -6445, -5480, -4870, -4645, z_1f + 0.08, z_1f + 0.86, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_SW_Top",     -6445, -5480, -4870, -4645, z_1f + 0.862, z_1f + 0.89, MATS["Sanitary_White"], col_1f)
    add_box_mm("1F_Kitchen_Sink",       -6260, -5560, -4780, -4340, z_1f + 0.875, z_1f + 0.894, MATS["OLO_Oven_DarkGlass"], col_1f, r_corner=20.0)
    add_box_mm("1F_Kitchen_Sink_Basin", -6220, -5600, -4740, -4380, z_1f + 0.880, z_1f + 0.896, MATS["Stair_Iron"], col_1f, r_corner=16.0)
    add_cyl_mm("1F_Kitchen_Sink_FaucetPost", -5910.0, -4815.0, 14.0, z_1f + 0.890, z_1f + 1.120, MATS["B2_Chrome_Silver"], col_1f, segs=16)
    add_box_mm("1F_Kitchen_Sink_FaucetArm",  -5922.0, -5898.0, -4825.0, -4680.0, z_1f + 1.095, z_1f + 1.120, MATS["B2_Chrome_Silver"], col_1f, r_corner=8.0)
    #   - South Leg (480mm countertop depth: x: -6445..-2688, y: -4645..-4165 -> 823mm spacious aisle to Island)
    add_box_mm("1F_Kitchen_S_ToeKick", -6445, -2688, -4645, -4215, zf_1f, z_1f + 0.08, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Kitchen_Counter_S", -6445, -2688, -4645, -4190, z_1f + 0.08, z_1f + 0.86, MATS["OLO_Cab_White"], col_1f)
    #   - Front door/drawer panels & black horizontal Gola handle channels along South base cabinets
    add_box_mm("1F_Kitchen_S_TopGola", -6445, -2688, -4192, -4178, z_1f + 0.83, z_1f + 0.86, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Kitchen_S_MidGola", -4500, -3280, -4192, -4178, z_1f + 0.44, z_1f + 0.475, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Kitchen_S_DrwBot",  -4496, -3284, -4190, -4175, z_1f + 0.082, z_1f + 0.44, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_S_DrwTop",  -4496, -3284, -4190, -4175, z_1f + 0.475, z_1f + 0.83, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_S_DoorR",   -3280, -2692, -4190, -4175, z_1f + 0.082, z_1f + 0.83, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_S_DoorL1",  -5100, -4504, -4190, -4175, z_1f + 0.082, z_1f + 0.83, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_S_DoorL2",  -6445, -5104, -4190, -4175, z_1f + 0.082, z_1f + 0.83, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_Counter_Top", -6445, -2688, -4645, -4165, z_1f + 0.862, z_1f + 0.89, MATS["Sanitary_White"], col_1f)
    #   - Deep Black Glass Backsplash East of SW sink window (z: 0.89..1.52m, x: -5480..-2688)
    add_box_mm("1F_Kitchen_Black_Backsplash", -5480, -2688, -4645, -4622, z_1f + 0.89, z_1f + 1.52, MATS["OLO_Black_Backsplash"], col_1f)
    #   - Dual-burner Black Glass Gas Hob & Slim T-Shaped Under-Cabinet Range Hood (centered in 480mm counter)
    add_box_mm("1F_Kitchen_Stove", -4270, -3510, -4585, -4205, z_1f + 0.891, z_1f + 0.905, MATS["OLO_Black_Backsplash"], col_1f, r_corner=12.0)
    add_cyl_mm("1F_Kitchen_BurnerL", -4060, -4395, 85.0, z_1f + 0.906, z_1f + 0.925, MATS["OLO_Oven_DarkGlass"], col_1f, segs=24)
    add_cyl_mm("1F_Kitchen_BurnerR", -3720, -4395, 85.0, z_1f + 0.906, z_1f + 0.925, MATS["OLO_Oven_DarkGlass"], col_1f, segs=24)
    add_box_mm("1F_Kitchen_RangeHood", -4340, -3440, -4645, -4310, z_1f + 1.46, z_1f + 1.52, MATS["OLO_Black_Backsplash"], col_1f)
    add_box_mm("1F_Kitchen_RangeHood_Trim", -4340, -3440, -4315, -4305, z_1f + 1.47, z_1f + 1.505, MATS["Sanitary_White"], col_1f)
    #   - 5-Door Matte White Upper Wall Cabinets East of SW window (z: 1.52..2.38m, y: -4645..-4285, x: -5480..-2688)
    add_box_mm("1F_Kitchen_Upper_Carcass", -5480, -2688, -4645, -4305, z_1f + 1.52, z_1f + 2.38, MATS["OLO_Cab_White"], col_1f)
    n_up_doors = 5
    up_w = (-2688.0 - (-5480.0)) / n_up_doors
    for ud_i in range(n_up_doors):
        ux1 = -5480.0 + ud_i * up_w + 2.5
        ux2 = -5480.0 + (ud_i + 1) * up_w - 2.5
        add_box_mm(f"1F_Kitchen_Upper_Door_{ud_i+1}", ux1, ux2, -4305, -4285, z_1f + 1.522, z_1f + 2.378, MATS["OLO_Cab_White"], col_1f)

    # 5. Central Kitchen Island (岛台: 24-seg smooth R85 quarter-round corner columns + flat side panels,
    #    recessed dark plinth, white sub-top collar, flush R85 countertop,
    #    North dining side: 3 full-height flush doors; South kitchen side: Left/Right doors + 4 central stacked drawers with deep black Gola channels)
    #    Overall footprint: x: -4000..-2700 (1300mm wide), y: -3470..-2820 (650mm deep, rev. 2026-10-28)
    def add_smooth_rbox_mm(bname, x1, x2, y1, y2, z0, z1, r_c, mat, col, segs=24):
        pts = []
        corners = [
            (x2 - r_c, y2 - r_c, 0.0, 90.0),
            (x1 + r_c, y2 - r_c, 90.0, 180.0),
            (x1 + r_c, y1 + r_c, 180.0, 270.0),
            (x2 - r_c, y1 + r_c, 270.0, 360.0),
        ]
        for cx, cy, a1, a2 in corners:
            for k in range(segs + 1):
                a = math.radians(a1 + (a2 - a1) * k / float(segs))
                pts.append((cx + r_c * math.cos(a), cy + r_c * math.sin(a)))
        return add_prism(bname, pts, z0, z1, mat, col)

    def add_quarter_col_mm(qname, cx, cy, r_c, a1, a2, z0, z1, mat, col, segs=24):
        pts = [(cx, cy)]
        for k in range(segs + 1):
            a = math.radians(a1 + (a2 - a1) * k / float(segs))
            pts.append((cx + r_c * math.cos(a), cy + r_c * math.sin(a)))
        return add_prism(qname, pts, z0, z1, mat, col)

    # 5. Slim Central Kitchen Island (calibrated to WechatIMG6.jpg manual survey: width 1180mm x depth 520mm, rev. 2026-11-03)
    add_smooth_rbox_mm("1F_Kitchen_Island_Plinth", -3850, -2770, -3295, -2865, zf_1f, z_1f + 0.075, 45.0, MATS["OLO_ToeKick_Black"], col_1f)
    add_quarter_col_mm("1F_Kitchen_Island_Corner_NW", -3815, -2905, 85.0,  90.0, 180.0, z_1f + 0.075, z_1f + 0.848, MATS["OLO_Cab_White"], col_1f)
    add_quarter_col_mm("1F_Kitchen_Island_Corner_SW", -3815, -3255, 85.0, 180.0, 270.0, z_1f + 0.075, z_1f + 0.848, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_Island_SideFlat_W", -3900, -3815, -3253, -2907, z_1f + 0.075, z_1f + 0.848, MATS["OLO_Cab_White"], col_1f)
    add_quarter_col_mm("1F_Kitchen_Island_Corner_NE", -2805, -2905, 85.0,   0.0,  90.0, z_1f + 0.075, z_1f + 0.848, MATS["OLO_Cab_White"], col_1f)
    add_quarter_col_mm("1F_Kitchen_Island_Corner_SE", -2805, -3255, 85.0, 270.0, 360.0, z_1f + 0.075, z_1f + 0.848, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_Island_SideFlat_E", -2805, -2720, -3253, -2907, z_1f + 0.075, z_1f + 0.848, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_Island_CoreWhite",   -3815, -2805, -3305, -2826, z_1f + 0.075, z_1f + 0.848, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_Island_SouthRecess", -3815, -2805, -3326, -3305, z_1f + 0.076, z_1f + 0.848, MATS["OLO_Black_Backsplash"], col_1f)
    add_box_mm("1F_Kitchen_Island_S_DoorL", -3813, -3540, -3340, -3322, z_1f + 0.075, z_1f + 0.822, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Kitchen_Island_S_DoorR", -3080, -2807, -3340, -3322, z_1f + 0.075, z_1f + 0.822, MATS["OLO_Cab_White"], col_1f)
    drw_z_ranges = [
        (0.075, 0.244),
        (0.268, 0.434),
        (0.458, 0.624),
        (0.648, 0.822),
    ]
    for d_idx, (dz1, dz2) in enumerate(drw_z_ranges):
        add_box_mm(f"1F_Kitchen_Island_S_Drawer_{d_idx+1}", -3535, -3085, -3340, -3322, z_1f + dz1, z_1f + dz2, MATS["OLO_Cab_White"], col_1f)
        # Feitian 96mm Long Pull (LS-X73-96) on drawers
        d_midz = z_1f + (dz1 + dz2) / 2.0
        add_box_mm(f"1F_Kitchen_Island_Drawer_Pull_{d_idx+1}", -3360, -3260, -3348, -3340, d_midz - 0.009, d_midz + 0.009, MATS["Stair_Bronze_Iron"], col_1f)
    isl_dw = (-2807.0 - (-3813.0)) / 3.0
    for id_i in range(3):
        ix1 = -3813.0 + id_i * isl_dw + 2.0
        ix2 = -3813.0 + (id_i + 1) * isl_dw - 2.0
        add_box_mm(f"1F_Kitchen_Island_FrontDoor_{id_i+1}", ix1, ix2, -2826, -2820, z_1f + 0.075, z_1f + 0.848, MATS["OLO_Cab_White"], col_1f)
    add_smooth_rbox_mm("1F_Kitchen_Island_SubCollar", -3900, -2720, -3340, -2820, z_1f + 0.850, z_1f + 0.866, 85.0, MATS["OLO_Cab_White"], col_1f)
    add_smooth_rbox_mm("1F_Kitchen_Island_Top",       -3902, -2718, -3342, -2818, z_1f + 0.868, z_1f + 0.890, 85.0, MATS["Sanitary_White"], col_1f)

    # 1F Kitchen Hardware: LS-X71-D Jade Square Knobs & LS-X73-96 Feitian Handles (matching media_1793052939351_b9ee45a0.png)
    # Upper Cabinet Doors: Pairs of Jade Knobs near bottom meeting corners
    for ud_i in range(n_up_doors):
        ux1 = -5480.0 + ud_i * up_w + 2.5
        ux2 = -5480.0 + (ud_i + 1) * up_w - 2.5
        hx = ux2 - 25.0 if ud_i % 2 == 0 else ux1 + 25.0
        add_box_mm(f"1F_Kitchen_UpDoor_Knob_{ud_i+1}", hx - 14.0, hx + 14.0, -4285, -4262, z_1f + 1.55, z_1f + 1.58, MATS["OLO_ToeKick_Black"], col_1f)
        add_box_mm(f"1F_Kitchen_UpDoor_Jade_{ud_i+1}", hx - 12.0, hx + 12.0, -4283, -4260, z_1f + 1.552, z_1f + 1.578, MATS["SideTable_Green_Marble"], col_1f)
    # Foyer Glass Doors: Jade Knobs at meeting center
    add_box_mm("1F_Foyer_Glass_KnobL", -5805, -5785, -2815, -2792, z_1f + 1.35, z_1f + 1.38, MATS["SideTable_Green_Marble"], col_1f)
    add_box_mm("1F_Foyer_Glass_KnobR", -5780, -5760, -2815, -2792, z_1f + 1.35, z_1f + 1.38, MATS["SideTable_Green_Marble"], col_1f)
    # - Dining North Tall Sideboard along 3706mm wall (x: -5194..-1735, y: -120..+260) & West Niche Low Sideboard (360 x 880mm in 360x1240 niche)
    # add_box_mm("1F_Dining_Sideboard_N", -5194, -1735, -120, 260, zf_1f, z_1f + 2.35, MATS["Cabinet_Walnut"], col_1f)  # replaced by f1_dining_spec (rev. 2026-10-28)
    # add_box_mm("1F_Dining_Sideboard_W", -5554, -5194, -980, -100, zf_1f, z_1f + 0.90, MATS["Cabinet_Walnut"], col_1f)  # replaced by the 150 mm double-door tall cabinet (f1_dining_spec)
    # - 1F Dining Table replaced below by 1.20x0.75m Song-Aesthetic Wooden Dining Table & 4 Song Armchairs
    for idx, cx in enumerate([]):  # rev. 2026-10-28: wall-side chairs replaced by the banquette
        add_box_mm(f"1F_Dining_Chair_{idx+1}", cx - 200, cx + 200, -520, -140, zf_1f, z_1f + 0.78, MATS["Accent_Leather"], col_1f, r_corner=40.0)
    # 1F dining front wall: floor-to-slab white cabinetry + lit banquette niche (rev. 2026-10-28, generated by f1_dining_spec.py)
    # add_box_mm("1F_Dining_Wall_L_Carcass", -5194.0, -4250.0, -100.0, 260.0, z_1f + 0.0000, z_1f + 3.1500, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_L_Plinth", -5174.0, -4270.0, -80.0, -100.0, z_1f + 0.0000, z_1f + 0.0600, MATS["OLO_ToeKick_Black"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_L_Door_1", -5192.5, -4251.5, -120.0, -100.0, z_1f + 0.0615, z_1f + 0.9485, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_L_Door_2", -5192.5, -4251.5, -120.0, -100.0, z_1f + 0.9515, z_1f + 1.9485, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_L_Door_3", -5192.5, -4251.5, -120.0, -100.0, z_1f + 1.9515, z_1f + 3.1485, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_L_Handle_1", -4298.0, -4282.0, -145.0, -120.0, z_1f + 0.4500, z_1f + 0.8500, MATS["Stair_Bronze_Iron"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_L_Handle_2", -4298.0, -4282.0, -145.0, -120.0, z_1f + 1.0500, z_1f + 1.6500, MATS["Stair_Bronze_Iron"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_R_Carcass", -2450.0, -1735.0, -100.0, 260.0, z_1f + 0.0000, z_1f + 3.1500, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_R_Plinth", -2430.0, -1755.0, -80.0, -100.0, z_1f + 0.0000, z_1f + 0.0600, MATS["OLO_ToeKick_Black"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_R_Door_1", -2448.5, -1736.5, -120.0, -100.0, z_1f + 0.0615, z_1f + 0.9485, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_R_Door_2", -2448.5, -1736.5, -120.0, -100.0, z_1f + 0.9515, z_1f + 1.9485, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_R_Door_3", -2448.5, -1736.5, -120.0, -100.0, z_1f + 1.9515, z_1f + 3.1485, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_R_Handle_1", -2418.0, -2402.0, -145.0, -120.0, z_1f + 0.4500, z_1f + 0.8500, MATS["Stair_Bronze_Iron"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_R_Handle_2", -2418.0, -2402.0, -145.0, -120.0, z_1f + 1.0500, z_1f + 1.6500, MATS["Stair_Bronze_Iron"], col_1f)  # replaced 2026-10-29 by the ripple-glass planted box
    # add_box_mm("1F_Dining_Wall_Upper_Carcass", -4250.0, -2450.0, -100.0, 260.0, z_1f + 1.9500, z_1f + 3.1500, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the planted glass box (v2)
    # add_box_mm("1F_Dining_Wall_Upper_Door_1", -4248.5, -3651.5, -120.0, -100.0, z_1f + 1.9520, z_1f + 3.1480, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the planted glass box (v2)
    # add_box_mm("1F_Dining_Wall_Upper_Door_2", -3648.5, -3051.5, -120.0, -100.0, z_1f + 1.9520, z_1f + 3.1480, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the planted glass box (v2)
    # add_box_mm("1F_Dining_Wall_Upper_Door_3", -3048.5, -2451.5, -120.0, -100.0, z_1f + 1.9520, z_1f + 3.1480, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the planted glass box (v2)
    # add_box_mm("1F_Dining_Niche_Back", -4250.0, -2450.0, 240.0, 260.0, z_1f + 0.0000, z_1f + 1.9500, MATS["OLO_Cab_White"], col_1f)  # superseded by v3 block (2026-10-31)
    # add_box_mm("1F_Dining_Niche_SideW", -4250.0, -4230.0, -120.0, 240.0, z_1f + 0.0000, z_1f + 1.9500, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the planted glass box (v2)
    # add_box_mm("1F_Dining_Niche_SideE", -2470.0, -2450.0, -120.0, 240.0, z_1f + 0.0000, z_1f + 1.9500, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the planted glass box (v2)
    # add_box_mm("1F_Dining_Niche_Soffit", -4230.0, -2470.0, -120.0, 240.0, z_1f + 1.9000, z_1f + 1.9500, MATS["OLO_Cab_White"], col_1f)  # replaced 2026-10-29 by the planted glass box (v2)
    # add_box_mm("1F_Dining_Niche_LED", -4220.0, -2480.0, -110.0, -95.0, z_1f + 1.8920, z_1f + 1.9000, MATS["Warm_LED_Glow"], col_1f)  # replaced 2026-10-29 by the planted glass box (v2)
    # add_box_mm("1F_Dining_Bench_Toe", -4230.0, -2470.0, -240.0, 240.0, z_1f + 0.0000, z_1f + 0.0700, MATS["OLO_ToeKick_Black"], col_1f)  # superseded by v3 block (2026-10-31)
    # add_box_mm("1F_Dining_Bench_Base", -4230.0, -2470.0, -280.0, 240.0, z_1f + 0.0700, z_1f + 0.4000, MATS["OLO_Cab_White"], col_1f)  # superseded by v3 block (2026-10-31)
    # add_box_mm("1F_Dining_Bench_Seat", -4225.0, -2475.0, -285.0, 240.0, z_1f + 0.4000, z_1f + 0.4900, MATS["Linen_Cushion"], col_1f)  # superseded by v3 block (2026-10-31)
    # add_box_mm("1F_Dining_Bench_Back", -4225.0, -2475.0, 110.0, 240.0, z_1f + 0.4900, z_1f + 0.9800, MATS["Linen_Cushion"], col_1f)  # superseded by v3 block (2026-10-31)
    # add_box_mm("1F_Dining_Bench_BackTop", -4225.0, -2475.0, 120.0, 240.0, z_1f + 0.9800, z_1f + 1.0000, MATS["Linen_Cushion"], col_1f)  # superseded by v3 block (2026-10-31)
    # add_box_mm("1F_Dining_WestTall_Carcass", -5324.0, -5194.0, -980.0, -100.0, z_1f + 0.0000, z_1f + 3.1500, MATS["OLO_Cab_White"], col_1f)  # superseded by v3 block (2026-10-31)
    # add_box_mm("1F_Dining_WestTall_Plinth", -5194.0, -5164.0, -1220.0, -100.0, z_1f + 0.0000, z_1f + 0.0650, MATS["OLO_ToeKick_Black"], col_1f)  # superseded by v3 block (2026-10-31)
    # add_box_mm("1F_Dining_WestTall_Crown", -5194.0, -5164.0, -1220.0, -100.0, z_1f + 3.1100, z_1f + 3.1500, MATS["OLO_ToeKick_Black"], col_1f)  # superseded by v3 block (2026-10-31)
    # add_box_mm("1F_Dining_WestTall_Door_1", -5194.0, -5174.0, -1208.5, -656.5, z_1f + 0.0670, z_1f + 3.1080, MATS["OLO_Cab_White"], col_1f)  # superseded by v3 block (2026-10-31)
    # add_box_mm("1F_Dining_WestTall_Handle_1", -5174.0, -5149.0, -698.0, -682.0, z_1f + 0.9500, z_1f + 1.5500, MATS["Stair_Bronze_Iron"], col_1f)  # superseded by v3 block (2026-10-31)
    # add_box_mm("1F_Dining_WestTall_Door_2", -5194.0, -5174.0, -653.5, -101.5, z_1f + 0.0670, z_1f + 3.1080, MATS["OLO_Cab_White"], col_1f)  # superseded by v3 block (2026-10-31)
    # add_box_mm("1F_Dining_WestTall_Handle_2", -5174.0, -5149.0, -628.0, -612.0, z_1f + 0.9500, z_1f + 1.5500, MATS["Stair_Bronze_Iron"], col_1f)  # superseded by v3 block (2026-10-31)
    # - 1F Dining Room: Integrated Sideboard & Chinese Pagoda Eaved Canopy Banquette (rev. 2026-11-04)
    #   Strictly matching reference photo (media_1793814667626_791da8fa.jpg) + carved wood pillar (media_1793814781501_338ef8fa.jpg):
    #   5 Proportional Modules along North Wall (x: -5194..-1735, W=3459mm):
    #   1. West Return L-Wall Recessed Shelves (x: -5324..-5194, y: -950..-120): backlit open vertical teaware shelves
    #   2. Module 1: Left Tall Cabinet (-5194..-4714, W=480mm) with single full-height sleek white door
    #   3. Module 2: Left Base Cabinet (H=0.58m) + Upper Lit Glass Showcase (z: 0.60..2.80m, W=520mm) with 3 illuminated glass shelves
    #   4. Left Middle Pilaster / Carved Wooden Column (-4194..-4114, W=80mm, D=140mm) resting above base plinth line
    #   5. Module 3: Center Banquette + Feature Gold-Vein Marble Wall + 4-Door Ripple-Glass Overhead Cabinet + Pagoda Eave Canopy (-4114..-2814, W=1300mm)
    #   6. Right Middle Pilaster / Carved Wooden Column (-2814..-2734, W=80mm, D=140mm)
    #   7. Module 4: Right Base Cabinet (H=0.58m) + Upper Lit Glass Showcase (z: 0.60..2.80m, W=520mm) with 3 illuminated glass shelves
    #   8. Module 5: Right Tall Cabinet (-2214..-1734, W=480mm) with single full-height sleek white door

    # - 1F Dining Room: Real 3D L-Shaped Neo-Chinese Sideboard, Blonde-Wood Pagoda Canopy, Golden Wave Backdrop & Curved Banquette
    #   (rev. 2026-11-22: full real-3D upgrade matching media_1795367527550_6dc6804b.jpg)
    cab_mat = make_mat("Dining_Lacquer_White", (0.95, 0.94, 0.93, 1.0), metallic=0.0, roughness=0.22)
    try:
        _c_nt = cab_mat.node_tree
        _c_bsdf = _c_nt.nodes.get("Principled BSDF")
        if _c_bsdf is not None:
            if "Coat Weight" in _c_bsdf.inputs:
                _c_bsdf.inputs["Coat Weight"].default_value = 0.22
                _c_bsdf.inputs["Coat Roughness"].default_value = 0.14
            _c_bev = _c_nt.nodes.new("ShaderNodeBevel")
            _c_bev.samples = 4
            _c_bev.inputs["Radius"].default_value = 0.002
            _c_nt.links.new(_c_bev.outputs["Normal"], _c_bsdf.inputs["Normal"])
    except Exception:
        pass

    eave_mat = make_mat("Dining_Blonde_Wood", (0.84, 0.69, 0.49, 1.0), metallic=0.0, roughness=0.34)
    try:
        _ew_bsdf = eave_mat.node_tree.nodes.get("Principled BSDF")
        if _ew_bsdf is not None and "Coat Weight" in _ew_bsdf.inputs:
            _ew_bsdf.inputs["Coat Weight"].default_value = 0.12
            _ew_bsdf.inputs["Coat Roughness"].default_value = 0.24
    except Exception:
        pass
    eave_deep_mat = make_mat("Dining_Blonde_Wood_Deep", (0.74, 0.56, 0.36, 1.0), metallic=0.0, roughness=0.38)
    gold_trim_mat = make_mat("Dining_Gold_Trim", (0.84, 0.69, 0.42, 1.0), metallic=0.86, roughness=0.24)
    boucle_mat = make_mat("Dining_Cream_Boucle", (0.88, 0.85, 0.81, 1.0), metallic=0.0, roughness=0.76)
    try:
        _bq_bsdf = boucle_mat.node_tree.nodes.get("Principled BSDF")
        if _bq_bsdf is not None:
            for _bk, _bv in (("Sheen Weight", 0.65), ("Sheen Roughness", 0.55)):
                if _bk in _bq_bsdf.inputs:
                    _bq_bsdf.inputs[_bk].default_value = _bv
    except Exception:
        pass
    ceramic_mat = make_mat("Dining_Ceramic_White", (0.96, 0.96, 0.95, 1.0), metallic=0.0, roughness=0.14)
    try:
        _cm_bsdf = ceramic_mat.node_tree.nodes.get("Principled BSDF")
        if _cm_bsdf is not None and "Coat Weight" in _cm_bsdf.inputs:
            _cm_bsdf.inputs["Coat Weight"].default_value = 0.35
            _cm_bsdf.inputs["Coat Roughness"].default_value = 0.08
    except Exception:
        pass
    silver_bowl_mat = make_mat("Dining_Silver_Bowl", (0.80, 0.79, 0.77, 1.0), metallic=0.90, roughness=0.24)
    cab_glass_mat = make_mat("Dining_Cab_Glass", (0.92, 0.93, 0.92, 0.28), metallic=0.02, roughness=0.08, transmission=0.88, alpha=0.28)
    wire_glass_mat = MATS["Dining_WireMesh_Glass"]
    song_wood_mat = MATS["Dining_Song_Wood"]
    warm_led = MATS["Dining_Warm_LED"] if "Dining_Warm_LED" in MATS else make_mat("Dining_Warm_LED", (1.00, 0.90, 0.72, 1.0), roughness=0.20, emission=(1.00, 0.90, 0.72, 1.0), emission_strength=4.5)

    wave_wood_mat = make_img_mat(
        "Dining_Golden_Wave_Wood",
        os.path.join(OUT_DIR, "textures", "tex_dining_golden_wave_wood.png"),
        (0.83, 0.67, 0.44, 1.0),
        metallic=0.14,
        roughness=0.30,
        repeat=True
    )
    try:
        _ww_nt = wave_wood_mat.node_tree
        _ww_bsdf = _ww_nt.nodes.get("Principled BSDF")
        if _ww_bsdf is not None:
            for _wk, _wv in (("Coat Weight", 0.22), ("Coat Roughness", 0.16), ("Specular IOR Level", 0.55)):
                if _wk in _ww_bsdf.inputs:
                    _ww_bsdf.inputs[_wk].default_value = _wv
            _ww_bpath = os.path.join(OUT_DIR, "textures", "tex_dining_golden_wave_wood_bump.png")
            if os.path.exists(_ww_bpath):
                _wbtex = _ww_nt.nodes.new("ShaderNodeTexImage")
                _wbtex.image = bpy.data.images.load(_wb_bpath, check_existing=True)
                _wbtex.image.colorspace_settings.name = 'Non-Color'
                _wbtex.extension = 'REPEAT'
                _wrm = _ww_nt.nodes.new("ShaderNodeMapRange")
                _wrm.clamp = True
                _wrm.inputs["From Min"].default_value = 0.0
                _wrm.inputs["From Max"].default_value = 1.0
                _wrm.inputs["To Min"].default_value = 0.22
                _wrm.inputs["To Max"].default_value = 0.44
                _ww_nt.links.new(_wbtex.outputs["Color"], _wrm.inputs["Value"])
                _ww_nt.links.new(_wrm.outputs["Result"], _ww_bsdf.inputs["Roughness"])
                _wbmp = _ww_nt.nodes.new("ShaderNodeBump")
                _wbmp.inputs["Strength"].default_value = 0.55
                _wbmp.inputs["Distance"].default_value = 0.012
                _ww_nt.links.new(_wbtex.outputs["Color"], _wbmp.inputs["Height"])
                _ww_nt.links.new(_wbmp.outputs["Normal"], _ww_bsdf.inputs["Normal"])
    except Exception:
        pass

    def add_song_dining_table_and_chairs(tname, cx_mm, cy_mm, z0, col):
        """1.20 x 0.75m Song-Aesthetic Wooden Dining Table (h=0.75m) + 4 Matching Song Wooden Armchairs (seat=0.45m)."""
        tw, td, th = 1200.0, 750.0, 0.750
        hw, hd = 0.5 * tw, 0.5 * td
        # Contemporary Walnut New-Chinese Table (`1.20x0.75m`): sleek chamfered top, recessed apron & slender tapered legs
        add_box_mm(f"{tname}_TopChamfer", cx_mm - hw + 10.0, cx_mm + hw - 10.0, cy_mm - hd + 10.0, cy_mm + hd - 10.0, z0 + th - 0.040, z0 + th - 0.024, song_wood_mat, col, r_corner=22.0)
        add_box_mm(f"{tname}_Top", cx_mm - hw, cx_mm + hw, cy_mm - hd, cy_mm + hd, z0 + th - 0.024, z0 + th, song_wood_mat, col, r_corner=24.0)
        add_box_mm(f"{tname}_ApronL", cx_mm - hw + 58.0, cx_mm + hw - 58.0, cy_mm + hd - 58.0, cy_mm + hd - 42.0, z0 + 0.680, z0 + 0.710, song_wood_mat, col)
        add_box_mm(f"{tname}_ApronR", cx_mm - hw + 58.0, cx_mm + hw - 58.0, cy_mm - hd + 42.0, cy_mm - hd + 58.0, z0 + 0.680, z0 + 0.710, song_wood_mat, col)
        add_box_mm(f"{tname}_ApronW", cx_mm - hw + 42.0, cx_mm - hw + 58.0, cy_mm - hd + 58.0, cy_mm + hd - 58.0, z0 + 0.680, z0 + 0.710, song_wood_mat, col)
        add_box_mm(f"{tname}_ApronE", cx_mm + hw - 58.0, cx_mm + hw - 42.0, cy_mm - hd + 58.0, cy_mm + hd - 58.0, z0 + 0.680, z0 + 0.710, song_wood_mat, col)

        def _add_taper_rod_pt(rname, p0_xy, z_a, p1_xy, z_b, r_a_mm, r_b_mm, mat, segs=16):
            mesh_r = bpy.data.meshes.new(rname)
            bm_r = bmesh.new()
            va = [bm_r.verts.new(((p0_xy[0] + r_a_mm * math.cos(2 * math.pi * k / segs)) * MM, (p0_xy[1] + r_a_mm * math.sin(2 * math.pi * k / segs)) * MM, z_a)) for k in range(segs)]
            vb = [bm_r.verts.new(((p1_xy[0] + r_b_mm * math.cos(2 * math.pi * k / segs)) * MM, (p1_xy[1] + r_b_mm * math.sin(2 * math.pi * k / segs)) * MM, z_b)) for k in range(segs)]
            for k in range(segs):
                kn = (k + 1) % segs
                f = bm_r.faces.new([va[k], va[kn], vb[kn], vb[k]])
                f.smooth = True
            bm_r.faces.new(va[::-1])
            bm_r.faces.new(vb)
            bmesh.ops.recalc_face_normals(bm_r, faces=bm_r.faces[:])
            bm_r.to_mesh(mesh_r)
            bm_r.free()
            obj_r = bpy.data.objects.new(rname, mesh_r)
            obj_r.data.materials.append(mat)
            link_obj(obj_r, col)

        leg_top_x, leg_top_y = hw - 64.0, hd - 60.0
        leg_bot_x, leg_bot_y = hw - 36.0, hd - 34.0
        for li, (sx, sy) in enumerate(((-1, -1), (1, -1), (1, 1), (-1, 1))):
            p_top = (cx_mm + sx * leg_top_x, cy_mm + sy * leg_top_y)
            p_fer = (cx_mm + sx * (leg_top_x + (leg_bot_x - leg_top_x) * 0.94), cy_mm + sy * (leg_top_y + (leg_bot_y - leg_top_y) * 0.94))
            p_bot = (cx_mm + sx * leg_bot_x, cy_mm + sy * leg_bot_y)
            _add_taper_rod_pt(f"{tname}_Leg_{li}", p_bot, z0 + 0.040, p_top, z0 + 0.710, 15.0, 20.0, song_wood_mat)
            _add_taper_rod_pt(f"{tname}_BrassFoot_{li}", p_bot, z0, p_fer, z0 + 0.040, 14.5, 15.2, gold_trim_mat)

        # 4 Contemporary New-Chinese Walnut Curved-Hoop Armchairs (seat top = 0.450m, open slender legs, horseshoe hoop & lumbar pad)
        def _add_song_armchair(cname, acx, acy, yaw_deg):
            rad = math.radians(yaw_deg)
            ca, sa = math.cos(rad), math.sin(rad)

            def _rot(lx, ly):
                return (acx + lx * ca - ly * sa, acy + lx * sa + ly * ca)

            def _rot_prism(pname, lx1, lx2, ly1, ly2, za, zb, mat):
                pts = [_rot(lx1, ly1), _rot(lx2, ly1), _rot(lx2, ly2), _rot(lx1, ly2)]
                add_prism(pname, pts, za, zb, mat, col)

            # Slim chamfered walnut seat frame & 450mm-high rounded cream boucle cushion
            _rot_prism(f"{cname}_SeatFrame",   -224.0, 224.0, -206.0, 212.0, z0 + 0.398, z0 + 0.422, song_wood_mat)
            _rot_prism(f"{cname}_SeatCushion", -210.0, 210.0, -196.0, 204.0, z0 + 0.422, z0 + 0.450, boucle_mat)
            # Clean minimalist recessed under-seat X/cross rail (no heavy low stretchers)
            _rot_prism(f"{cname}_UnderRailW", -202.0, -184.0, -180.0, 184.0, z0 + 0.382, z0 + 0.398, song_wood_mat)
            _rot_prism(f"{cname}_UnderRailE",  184.0,  202.0, -180.0, 184.0, z0 + 0.382, z0 + 0.398, song_wood_mat)

            # 4 slender tapered round walnut legs + brass tips + 2 rear backrest stiles + 2 angled side supports
            for ci_l, (lxt, lyt, lxb, lyb, has_rear_post) in enumerate((
                (-202.0, 192.0, -214.0, 204.0, False),
                ( 202.0, 192.0,  214.0, 204.0, False),
                (-194.0,-184.0, -206.0,-198.0, True),
                ( 194.0,-184.0,  206.0,-198.0, True),
            )):
                _add_taper_rod_pt(f"{cname}_Leg_{ci_l}", _rot(lxb, lyb), z0 + 0.032, _rot(lxt, lyt), z0 + 0.415, 11.0, 15.0, song_wood_mat, segs=14)
                _add_taper_rod_pt(f"{cname}_Foot_{ci_l}", _rot(lxb, lyb), z0, _rot(lxb * 0.99, lyb * 0.99), z0 + 0.032, 11.0, 11.5, gold_trim_mat, segs=14)
                if has_rear_post:
                    _add_taper_rod_pt(f"{cname}_BackStile_{ci_l}", _rot(lxt, lyt), z0 + 0.415, _rot(lxt * 0.96, -218.0), z0 + 0.728, 13.5, 11.5, song_wood_mat, segs=14)
                else:
                    sx_m = -1.0 if lxt < 0 else 1.0
                    _add_taper_rod_pt(f"{cname}_SidePost_{ci_l}", _rot(sx_m * 204.0, -20.0), z0 + 0.415, _rot(sx_m * 226.0, 75.0), z0 + 0.665, 11.5, 10.5, song_wood_mat, segs=14)

            # Continuous sweeping horseshoe curved walnut backrest & armrest hoop rail
            mesh_hp = bpy.data.meshes.new(f"{cname}_WalnutHoop")
            bm_hp = bmesh.new()
            hp_rings = []
            n_hp = 24
            for k in range(n_hp + 1):
                ang_h = math.radians(-165.0 + 150.0 * (k / float(n_hp)))  # U-hoop around back & sides, open in front (+Y)
                rx, ry = math.cos(ang_h), math.sin(ang_h)
                lx = 228.0 * rx
                ly = 40.0 + 265.0 * ry
                # Smoothly rises from 0.65m front arm tips to 0.745m rear crest
                lz = z0 + 0.650 + 0.095 * max(0.0, -ry)
                in_x, in_y = lx - 14.0 * rx, ly - 14.0 * ry
                out_x, out_y = lx + 14.0 * rx, ly + 14.0 * ry
                p_in = _rot(in_x, in_y)
                p_out = _rot(out_x, out_y)
                hp_rings.append((
                    bm_hp.verts.new((p_in[0] * MM,  p_in[1] * MM,  lz - 0.012)),
                    bm_hp.verts.new((p_out[0] * MM, p_out[1] * MM, lz - 0.012)),
                    bm_hp.verts.new((p_out[0] * MM, p_out[1] * MM, lz + 0.014)),
                    bm_hp.verts.new((p_in[0] * MM,  p_in[1] * MM,  lz + 0.014)),
                ))
            for k in range(n_hp):
                r0, r1 = hp_rings[k], hp_rings[k + 1]
                for s in range(4):
                    f = bm_hp.faces.new([r0[s], r0[(s + 1) % 4], r1[(s + 1) % 4], r1[s]])
                    f.smooth = True
            bm_hp.faces.new(hp_rings[0][::-1])
            bm_hp.faces.new(hp_rings[-1])
            bmesh.ops.recalc_face_normals(bm_hp, faces=bm_hp.faces[:])
            bm_hp.to_mesh(mesh_hp)
            bm_hp.free()
            o_hp = bpy.data.objects.new(f"{cname}_WalnutHoop", mesh_hp)
            o_hp.data.materials.append(song_wood_mat)
            link_obj(o_hp, col)

            # Floating curved cream boucle upholstered lumbar backrest pad nested cleanly inside hoop
            mesh_lb = bpy.data.meshes.new(f"{cname}_LumbarPad")
            bm_lb = bmesh.new()
            lb_rings = []
            n_lb = 14
            for k in range(n_lb + 1):
                u = k / float(n_lb)
                ang_l = math.radians(-135.0 + 90.0 * u)
                rx, ry = math.cos(ang_l), math.sin(ang_l)
                lx = 198.0 * rx
                ly = 45.0 + 235.0 * ry
                us = abs(2.0 * u - 1.0)
                t_thick = 18.0 * (1.0 - 0.35 * us * us)
                z_lo = z0 + 0.555
                z_hi = z0 + 0.720 - 0.025 * us * us
                p_in = _rot(lx - t_thick * rx, ly - t_thick * ry)
                p_out = _rot(lx + t_thick * rx, ly + t_thick * ry)
                lb_rings.append((
                    bm_lb.verts.new((p_in[0] * MM,  p_in[1] * MM,  z_lo)),
                    bm_lb.verts.new((p_out[0] * MM, p_out[1] * MM, z_lo)),
                    bm_lb.verts.new((p_out[0] * MM, p_out[1] * MM, z_hi)),
                    bm_lb.verts.new((p_in[0] * MM,  p_in[1] * MM,  z_hi)),
                ))
            for k in range(n_lb):
                r0, r1 = lb_rings[k], lb_rings[k + 1]
                for s in range(4):
                    f = bm_lb.faces.new([r0[s], r0[(s + 1) % 4], r1[(s + 1) % 4], r1[s]])
                    f.smooth = True
            bm_lb.faces.new(lb_rings[0][::-1])
            bm_lb.faces.new(lb_rings[-1])
            bmesh.ops.recalc_face_normals(bm_lb, faces=bm_lb.faces[:])
            bm_lb.to_mesh(mesh_lb)
            bm_lb.free()
            o_lb = bpy.data.objects.new(f"{cname}_LumbarPad", mesh_lb)
            o_lb.data.materials.append(boucle_mat)
            link_obj(o_lb, col)

        _add_song_armchair(f"{tname}_Chair_S1", cx_mm - 310.0, cy_mm - 610.0, 0.0)
        _add_song_armchair(f"{tname}_Chair_S2", cx_mm + 310.0, cy_mm - 610.0, 0.0)
        _add_song_armchair(f"{tname}_Chair_W",  cx_mm - 835.0, cy_mm,        -90.0)
        _add_song_armchair(f"{tname}_Chair_E",  cx_mm + 835.0, cy_mm,         90.0)

    # Center 1.20x0.75m Song-Aesthetic Wooden Table & 4 Armchairs (cy=-1040mm gives ~441mm ergonomic clearance to banquette front y=-224mm)
    for _old_t in [o for o in col_1f.objects if o.name.startswith("1F_Dining_Infinito_Table")]:
        bpy.data.objects.remove(_old_t, do_unlink=True)
    add_song_dining_table_and_chairs("1F_Dining_Song_Table", -3396.0, -1040.0, zf_1f, col_1f)

    def _add_hollow_frame_mm(fname, x1, x2, y1, y2, z0, z1, fw_mm, fz_m, mat, col):
        add_box_mm(f"{fname}_L", x1, x1 + fw_mm, y1, y2, z0, z1, mat, col)
        add_box_mm(f"{fname}_R", x2 - fw_mm, x2, y1, y2, z0, z1, mat, col)
        add_box_mm(f"{fname}_B", x1 + fw_mm, x2 - fw_mm, y1, y2, z0, z0 + fz_m, mat, col)
        add_box_mm(f"{fname}_T", x1 + fw_mm, x2 - fw_mm, y1, y2, z1 - fz_m, z1, mat, col)

    def _add_hollow_frame_side_mm(fname, x1, x2, y1, y2, z0, z1, fw_mm, fz_m, mat, col):
        add_box_mm(f"{fname}_S", x1, x2, y1, y1 + fw_mm, z0, z1, mat, col)
        add_box_mm(f"{fname}_N", x1, x2, y2 - fw_mm, y2, z0, z1, mat, col)
        add_box_mm(f"{fname}_B", x1, x2, y1 + fw_mm, y2 - fw_mm, z0, z0 + fz_m, mat, col)
        add_box_mm(f"{fname}_T", x1, x2, y1 + fw_mm, y2 - fw_mm, z1 - fz_m, z1, mat, col)

    def _add_lathe_vessel(vname, cx_mm, cy_mm, z_base, profile_r_z_mm, mat, segs=24):
        mesh_v = bpy.data.meshes.new(vname)
        bm_v = bmesh.new()
        rings = []
        cx_m, cy_m = cx_mm * MM, cy_mm * MM
        for rad_mm, h_mm in profile_r_z_mm:
            z_m = z_base + h_mm * MM
            if rad_mm <= 0.5:
                v_c = bm_v.verts.new((cx_m, cy_m, z_m))
                rings.append([v_c])
            else:
                ring = []
                for k in range(segs):
                    a = 2.0 * math.pi * k / segs
                    ring.append(bm_v.verts.new((cx_m + rad_mm * MM * math.cos(a), cy_m + rad_mm * MM * math.sin(a), z_m)))
                rings.append(ring)
        for ri in range(len(rings) - 1):
            r0, r1 = rings[ri], rings[ri + 1]
            if len(r0) == 1 and len(r1) > 1:
                for k in range(segs):
                    f = bm_v.faces.new([r0[0], r1[(k + 1) % segs], r1[k]])
                    f.smooth = True
            elif len(r0) > 1 and len(r1) == 1:
                for k in range(segs):
                    f = bm_v.faces.new([r0[k], r0[(k + 1) % segs], r1[0]])
                    f.smooth = True
            elif len(r0) > 1 and len(r1) > 1:
                for k in range(segs):
                    kn = (k + 1) % segs
                    f = bm_v.faces.new([r0[k], r0[kn], r1[kn], r1[k]])
                    f.smooth = True
        bmesh.ops.recalc_face_normals(bm_v, faces=bm_v.faces[:])
        bm_v.to_mesh(mesh_v)
        bm_v.free()
        obj_v = bpy.data.objects.new(vname, mesh_v)
        obj_v.data.materials.append(mat)
        link_obj(obj_v, col_1f)
        return obj_v

    def _add_tea_jar(jname, cx_mm, cy_mm, z_base, rad_mm, h_mm):
        prof = [
            (0.0, 0.0),
            (rad_mm * 0.82, 0.0),
            (rad_mm, h_mm * 0.14),
            (rad_mm, h_mm * 0.68),
            (rad_mm * 0.86, h_mm * 0.78),
            (rad_mm * 0.90, h_mm * 0.80),
            (rad_mm * 0.84, h_mm * 0.90),
            (rad_mm * 0.30, h_mm * 0.93),
            (rad_mm * 0.24, h_mm),
            (0.0, h_mm),
        ]
        _add_lathe_vessel(jname, cx_mm, cy_mm, z_base, prof, ceramic_mat, segs=24)

    def _add_bottle_vase(vname, cx_mm, cy_mm, z_base, rad_mm, h_mm):
        prof = [
            (0.0, 0.0),
            (rad_mm * 0.70, 0.0),
            (rad_mm, h_mm * 0.28),
            (rad_mm * 0.88, h_mm * 0.56),
            (rad_mm * 0.34, h_mm * 0.74),
            (rad_mm * 0.32, h_mm * 0.96),
            (rad_mm * 0.38, h_mm),
            (0.0, h_mm),
        ]
        _add_lathe_vessel(vname, cx_mm, cy_mm, z_base, prof, ceramic_mat, segs=24)

    def _add_decor_sphere(sname, cx_mm, cy_mm, z_base, rad_mm):
        bm_sp = bmesh.new()
        bmesh.ops.create_icosphere(bm_sp, subdivisions=2, radius=rad_mm * MM)
        for v in bm_sp.verts:
            v.co.x += cx_mm * MM
            v.co.y += cy_mm * MM
            v.co.z += z_base + rad_mm * MM
        for f in bm_sp.faces:
            f.smooth = True
        m_sp = bpy.data.meshes.new(sname)
        bm_sp.to_mesh(m_sp)
        bm_sp.free()
        o_sp = bpy.data.objects.new(sname, m_sp)
        o_sp.data.materials.append(ceramic_mat)
        link_obj(o_sp, col_1f)

    def _add_silver_pedestal_bowl(bname, cx_mm, cy_mm, z_base):
        prof = [
            (0.0, 0.0),
            (62.0, 0.0),
            (24.0, 52.0),
            (138.0, 128.0),
            (142.0, 134.0),
            (126.0, 134.0),
            (22.0, 62.0),
            (0.0, 60.0),
        ]
        _add_lathe_vessel(bname, cx_mm, cy_mm, z_base, prof, silver_bowl_mat, segs=28)

    def _add_interlocking_rings(rname, cx_mm, cy_mm, z_base):
        specs = [
            (0.0, 0.0, 68.0, 62.0, 20.0, 0.35, 0.25),
            (-36.0, -18.0, 96.0, 52.0, 18.0, -0.55, 0.60),
            (38.0, 12.0, 118.0, 56.0, 18.0, 0.65, -0.45),
        ]
        bm_r = bmesh.new()
        n_u, n_v = 28, 14
        for dx, dy, dz, R_maj, r_min, tilt_x, tilt_y in specs:
            rot_x = mathutils.Matrix.Rotation(tilt_x, 3, 'X')
            rot_y = mathutils.Matrix.Rotation(tilt_y, 3, 'Y')
            rot = rot_y @ rot_x
            grid_r = {}
            for iu in range(n_u):
                phi = 2.0 * math.pi * iu / n_u
                cp, sp = math.cos(phi), math.sin(phi)
                for iv in range(n_v):
                    th = 2.0 * math.pi * iv / n_v
                    ct, st = math.cos(th), math.sin(th)
                    p = mathutils.Vector(((R_maj + r_min * ct) * cp * MM, (R_maj + r_min * ct) * sp * MM, r_min * st * MM))
                    p = rot @ p
                    grid_r[(iu, iv)] = bm_r.verts.new((
                        (cx_mm + dx) * MM + p.x,
                        (cy_mm + dy) * MM + p.y,
                        z_base + dz * MM + p.z,
                    ))
            for iu in range(n_u):
                iun = (iu + 1) % n_u
                for iv in range(n_v):
                    ivn = (iv + 1) % n_v
                    f = bm_r.faces.new([grid_r[(iu, iv)], grid_r[(iun, iv)], grid_r[(iun, ivn)], grid_r[(iu, ivn)]])
                    f.smooth = True
        bmesh.ops.recalc_face_normals(bm_r, faces=bm_r.faces[:])
        m_r = bpy.data.meshes.new(rname)
        bm_r.to_mesh(m_r)
        bm_r.free()
        o_r = bpy.data.objects.new(rname, m_r)
        o_r.data.materials.append(ceramic_mat)
        link_obj(o_r, col_1f)

    # North Wall Plan Coordinates (x: -5194.0 .. -1488.0mm, H = 2.460m)
    add_box_mm("1F_Dining_SeamBack_Mod1", -5194.0, -4689.0, -115.0, -98.0, zf_1f, z_1f + 2.458, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Dining_SeamBack_Mod2Base", -4691.0, -4148.0, -115.0, -98.0, zf_1f, z_1f + 0.585, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Dining_SeamBack_Mod4Base", -2644.0, -2111.0, -115.0, -98.0, zf_1f, z_1f + 0.585, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Dining_SeamBack_Mod5", -2113.0, -1488.0, -115.0, -98.0, zf_1f, z_1f + 2.458, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Dining_North_Plinth",  -5194.0, -1488.0, -120.0, -90.0, zf_1f, z_1f + 0.049, MATS["OLO_ToeKick_Black"], col_1f)

    # 1. West Return L-Cabinet (x: -5420..-5180, y: -1320..-110, facing +X East): 64:36 Width Split & 7 Aligned Tiers
    x_wb, x_wf = -5420.0, -5180.0
    add_box_mm("1F_Dining_WestReturn_Plinth", -5405.0, -5182.0, -1320.0, -110.0, zf_1f, z_1f + 0.049, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Dining_WestReturn_BackWall", x_wb, x_wb + 24.0, -1320.0, -110.0, z_1f + 0.049, z_1f + 2.460, cab_mat, col_1f)
    add_box_mm("1F_Dining_WestReturn_PierS", x_wb, x_wf, -1320.0, -1288.0, z_1f + 0.049, z_1f + 2.460, cab_mat, col_1f)
    add_box_mm("1F_Dining_WestReturn_PierMid", x_wb, x_wf, -558.0, -540.0, z_1f + 0.049, z_1f + 2.460, cab_mat, col_1f)
    add_box_mm("1F_Dining_WestReturn_PierN", x_wb, x_wf, -130.0, -110.0, z_1f + 0.049, z_1f + 2.460, cab_mat, col_1f)
    add_box_mm("1F_Dining_WestReturn_Top", x_wb, x_wf, -1320.0, -110.0, z_1f + 2.442, z_1f + 2.460, cab_mat, col_1f)

    def _build_west_bay(bname, y1, y2, tiers, is_wide=True):
        yc = 0.5 * (y1 + y2)
        for ti, (z0_r, z1_r, kind, pull_type) in enumerate(tiers):
            if ti > 0:
                add_box_mm(f"{bname}_Shelf_{ti}", x_wb + 20.0, x_wf - 2.0, y1, y2, z_1f + z0_r - 0.016, z_1f + z0_r, cab_mat, col_1f)
            if kind == "closed":
                add_box_mm(f"{bname}_Seam_{ti}", x_wf - 24.0, x_wf - 18.0, y1, y2, z_1f + z0_r, z_1f + z1_r, MATS["OLO_ToeKick_Black"], col_1f)
                add_box_mm(f"{bname}_Door_{ti}", x_wf - 18.0, x_wf, y1 + 2.0, y2 - 2.0, z_1f + z0_r + 0.002, z_1f + z1_r - 0.018, cab_mat, col_1f)
                zm = z_1f + 0.5 * (z0_r + z1_r) - 0.008
                if pull_type == "frame":
                    _add_hollow_frame_side_mm(f"{bname}_GoldTrim_{ti}", x_wf - 1.0, x_wf + 4.0, y1 + 14.0, y2 - 14.0, z_1f + z0_r + 0.014, z_1f + z1_r - 0.030, 8.0, 0.008, gold_trim_mat, col_1f)
                elif pull_type == "sq":
                    add_box_mm(f"{bname}_PullSq_{ti}", x_wf, x_wf + 12.0, yc - 23.0, yc + 23.0, zm - 0.023, zm + 0.023, gold_trim_mat, col_1f)
                elif pull_type == "hbar":
                    hw_p = 75.0 if is_wide else 45.0
                    hh_p = 0.012 if is_wide else 0.011
                    add_box_mm(f"{bname}_PullH_{ti}", x_wf, x_wf + 12.0, yc - hw_p, yc + hw_p, zm - hh_p, zm + hh_p, gold_trim_mat, col_1f)
                elif pull_type == "vbar":
                    add_box_mm(f"{bname}_PullV_{ti}", x_wf, x_wf + 12.0, yc - 13.0, yc + 13.0, zm - 0.064, zm + 0.064, gold_trim_mat, col_1f)
            else:
                add_box_mm(f"{bname}_GoldLip_{ti}", x_wf - 8.0, x_wf + 2.0, y1, y2, z_1f + z0_r - 0.014, z_1f + z0_r, gold_trim_mat, col_1f)
                _add_hollow_frame_side_mm(f"{bname}_OpenTrim_{ti}", x_wf - 10.0, x_wf, y1 + 2.0, y2 - 2.0, z_1f + z0_r, z_1f + z1_r - 0.016, 6.0, 0.006, gold_trim_mat, col_1f)
                add_box_mm(f"{bname}_LED_{ti}", x_wb + 55.0, x_wb + 80.0, y1 + 12.0, y2 - 12.0, z_1f + z1_r - 0.024, z_1f + z1_r - 0.016, warm_led, col_1f)
                xp = 0.5 * (x_wb + x_wf) + 25.0
                if pull_type == "2jars":
                    _add_tea_jar(f"{bname}_JarA_{ti}", xp, yc - 70.0, z_1f + z0_r, 42.0, 125.0)
                    _add_tea_jar(f"{bname}_JarB_{ti}", xp, yc + 70.0, z_1f + z0_r, 38.0, 112.0)
                elif pull_type == "sphere":
                    _add_decor_sphere(f"{bname}_Sphere_{ti}", xp, yc, z_1f + z0_r, 108.0)
                elif pull_type == "jar":
                    _add_tea_jar(f"{bname}_Jar_{ti}", xp, yc, z_1f + z0_r, 68.0, 185.0)
                elif pull_type == "3jars":
                    _add_tea_jar(f"{bname}_J3A_{ti}", xp, yc - 85.0, z_1f + z0_r, 34.0, 105.0)
                    _add_tea_jar(f"{bname}_J3B_{ti}", xp, yc + 5.0,  z_1f + z0_r, 38.0, 138.0)
                    _add_tea_jar(f"{bname}_J3C_{ti}", xp, yc + 90.0, z_1f + z0_r, 32.0, 96.0)
                elif pull_type == "vase":
                    _add_bottle_vase(f"{bname}_Vase_{ti}", xp, yc, z_1f + z0_r, 76.0, 265.0)
                elif pull_type == "sjar":
                    _add_tea_jar(f"{bname}_SJar_{ti}", xp, yc, z_1f + z0_r, 44.0, 118.0)

    west_south_tiers = [
        (0.050, 0.300, "closed", "frame"),
        (0.300, 0.560, "open",   "2jars"),
        (0.560, 0.800, "closed", "sq"),
        (0.800, 1.240, "open",   "sphere"),
        (1.240, 1.620, "closed", "hbar"),
        (1.620, 2.020, "open",   "jar"),
        (2.020, 2.442, "closed", "frame"),
    ]
    west_north_tiers = [
        (0.050, 0.300, "open",   "sjar"),
        (0.300, 0.560, "closed", "vbar"),
        (0.560, 0.800, "closed", "hbar"),
        (0.800, 1.240, "open",   "3jars"),
        (1.240, 1.620, "open",   "3jars"),
        (1.620, 2.020, "closed", "sq"),
        (2.020, 2.442, "open",   "vase"),
    ]
    _build_west_bay("1F_Dining_WestS", -1288.0, -558.0, west_south_tiers, is_wide=True)
    _build_west_bay("1F_Dining_WestN", -540.0, -130.0, west_north_tiers, is_wide=False)

    # 2. Module 1: Left Tall Flush White Cabinet (x: -5194.0..-4691.0)
    add_box_mm("1F_Dining_Mod1_Tall_Carcass", -5194.0, -4691.0, -100.0, 260.0, zf_1f, z_1f + 2.458, cab_mat, col_1f)
    add_box_mm("1F_Dining_Mod1_Tall_Door",    -5190.0, -4694.5, -124.0, -114.0, z_1f + 0.051, z_1f + 2.456, cab_mat, col_1f)

    # 3 & 7. North Illuminated Display Showcases with Closed Matte-White Lower Doors (Mod 2: -4691..-4148, Mod 4: -2644..-2111)
    def _build_north_open_showcase(mname, x1, x2, is_left=True):
        xc = 0.5 * (x1 + x2)
        yb_in, yf_in = 220.0, -120.0
        # Closed Matte White Base Cabinet & Normal Flush Door below Wire-Glass Door (z: 0.051..1.030)
        add_box_mm(f"{mname}_Base_Carcass", x1, x2, -100.0, 260.0, zf_1f, z_1f + 1.034, cab_mat, col_1f)
        add_box_mm(f"{mname}_Base_Seam",    x1 + 2.0, x2 - 2.0, -114.0, -100.0, z_1f + 0.051, z_1f + 1.034, MATS["OLO_ToeKick_Black"], col_1f)
        add_box_mm(f"{mname}_Base_Door",    x1 + 3.5, x2 - 3.5, -124.0, -114.0, z_1f + 0.051, z_1f + 1.030, cab_mat, col_1f)
        # Illuminated White Display Showcase above Base Door (z: 1.034..2.456)
        add_box_mm(f"{mname}_Back", x1, x2, yb_in, 260.0, z_1f + 1.034, z_1f + 2.458, cab_mat, col_1f)
        add_box_mm(f"{mname}_SideW", x1, x1 + 16.0, yf_in, yb_in, z_1f + 1.034, z_1f + 2.458, cab_mat, col_1f)
        add_box_mm(f"{mname}_SideE", x2 - 16.0, x2, yf_in, yb_in, z_1f + 1.034, z_1f + 2.458, cab_mat, col_1f)
        add_box_mm(f"{mname}_TopPlate", x1, x2, yf_in, yb_in, z_1f + 2.440, z_1f + 2.458, cab_mat, col_1f)
        _add_hollow_frame_mm(f"{mname}_GoldBorder", x1 + 14.0, x2 - 14.0, -112.0, -104.0, z_1f + 1.034, z_1f + 2.442, 8.0, 0.008, gold_trim_mat, col_1f)
        shelf_zs = [1.050, 1.500, 1.960]
        top_zs = [1.500, 1.960, 2.440]
        for si, (sz, tz) in enumerate(zip(shelf_zs, top_zs)):
            add_box_mm(f"{mname}_Shelf_{si}", x1 + 16.0, x2 - 16.0, -110.0, yb_in, z_1f + sz - 0.016, z_1f + sz, cab_mat, col_1f)
            add_box_mm(f"{mname}_ShelfLip_{si}", x1 + 16.0, x2 - 16.0, -112.0, -108.0, z_1f + sz - 0.016, z_1f + sz, gold_trim_mat, col_1f)
            add_box_mm(f"{mname}_LED_{si}", x1 + 26.0, x2 - 26.0, -55.0, -35.0, z_1f + tz - 0.024, z_1f + tz - 0.018, warm_led, col_1f)
        # Gold-framed metallic silk-wire laminated glass door from inner bottom edge of 2nd-from-bottom cubby (1.050m) to full cabinet top (2.456m)
        _add_hollow_frame_mm(f"{mname}_WireDoorFrame", x1 + 4.0, x2 - 4.0, -124.0, -112.0, z_1f + 1.034, z_1f + 2.456, 16.0, 0.016, gold_trim_mat, col_1f)
        add_uv_front_box_mm(f"{mname}_WireDoorPane", x1 + 20.0, x2 - 20.0, -120.0, -114.0, z_1f + 1.050, z_1f + 2.440, 0.0, 1.5, 0.0, 3.2, wire_glass_mat, col_1f)
        hx_wire = (x2 - 12.0) if is_left else (x1 + 12.0)
        add_box_mm(f"{mname}_WireDoorPull", hx_wire - 4.0, hx_wire + 4.0, -133.0, -124.0, z_1f + 1.18, z_1f + 1.48, gold_trim_mat, col_1f)
        yc = 55.0
        if is_left:
            _add_tea_jar(f"{mname}_TrioA", xc - 78.0, yc, z_1f + 1.050, 34.0, 108.0)
            _add_tea_jar(f"{mname}_TrioB", xc + 2.0,  yc - 12.0, z_1f + 1.050, 38.0, 146.0)
            _add_tea_jar(f"{mname}_TrioC", xc + 80.0, yc, z_1f + 1.050, 32.0, 96.0)
            _add_decor_sphere(f"{mname}_Sphere", xc, yc, z_1f + 1.500, 112.0)
            _add_tea_jar(f"{mname}_Jar3", xc, yc, z_1f + 1.960, 78.0, 215.0)
        else:
            _add_silver_pedestal_bowl(f"{mname}_SilverBowl", xc, yc, z_1f + 1.050)
            _add_tea_jar(f"{mname}_Jar2", xc, yc, z_1f + 1.500, 72.0, 195.0)
            _add_interlocking_rings(f"{mname}_Rings", xc, yc, z_1f + 1.960)

    _build_north_open_showcase("1F_Dining_Mod2", -4691.0, -4148.0, is_left=True)

    # 5. Module 3: Center Neo-Chinese Blonde-Wood Pagoda Alcove, Golden Wave Wall & Sculpted Banquette (protruding ONLY 100mm past -124mm cabinet front -> y=-224mm!)
    cx_m3 = -3396.0
    add_box_mm("1F_Dining_Banquette_Plinth", -4115.0, -2677.0, -204.0, 200.0, zf_1f, z_1f + 0.049, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Dining_Banquette_Base", -4120.0, -2672.0, -220.0, 200.0, z_1f + 0.049, z_1f + 0.388, cab_mat, col_1f, r_corner=30.0)
    add_box_mm("1F_Dining_Banquette_BaseLip", -4126.0, -2666.0, -224.0, 195.0, z_1f + 0.388, z_1f + 0.415, eave_mat, col_1f, r_corner=30.0)
    add_box_mm("1F_Dining_Alcove_SideW", -4148.0, -4106.0, -120.0, 240.0, z_1f + 0.388, z_1f + 2.200, eave_mat, col_1f)
    add_box_mm("1F_Dining_Alcove_SideE", -2686.0, -2644.0, -120.0, 240.0, z_1f + 0.388, z_1f + 2.200, eave_mat, col_1f)

    # Golden Flowing-Wave Wood Relief Backdrop (subtle 3D undulation + Dining_Golden_Wave_Wood)
    bm_wb = bmesh.new()
    uv_wb = bm_wb.loops.layers.uv.new("UVMap")
    nx_wb, nz_wb = 32, 16
    x0_wb, x1_wb = -4.106, -2.686
    z0_wb, z1_wb = z_1f + 0.510, z_1f + 1.660
    grid_wb = {}
    for ix in range(nx_wb):
        ut = ix / float(nx_wb - 1)
        xv = x0_wb + ut * (x1_wb - x0_wb)
        for iz in range(nz_wb):
            vt = iz / float(nz_wb - 1)
            zv = z0_wb + vt * (z1_wb - z0_wb)
            wdisp = 0.011 * math.sin(6.0 * math.pi * vt + 1.15 * math.sin(2.0 * math.pi * ut))
            yv = 0.168 - wdisp
            grid_wb[(ix, iz)] = bm_wb.verts.new((xv, yv, zv))
    for ix in range(nx_wb - 1):
        for iz in range(nz_wb - 1):
            f = bm_wb.faces.new([grid_wb[(ix + 1, iz)], grid_wb[(ix, iz)], grid_wb[(ix, iz + 1)], grid_wb[(ix + 1, iz + 1)]])
            f.smooth = True
            for l in f.loops:
                l[uv_wb].uv = ((l.vert.co.x - x0_wb) / (x1_wb - x0_wb), (l.vert.co.z - z0_wb) / (z1_wb - z0_wb))
    bmesh.ops.recalc_face_normals(bm_wb, faces=bm_wb.faces[:])
    m_wb = bpy.data.meshes.new("1F_Dining_Banquette_WaveBack")
    bm_wb.to_mesh(m_wb)
    bm_wb.free()
    o_wb = bpy.data.objects.new("1F_Dining_Banquette_WaveBack", m_wb)
    o_wb.data.materials.append(wave_wood_mat)
    link_obj(o_wb, col_1f)
    add_box_mm("1F_Dining_Banquette_WaveLED", -4090.0, -2702.0, 118.0, 146.0, z_1f + 1.646, z_1f + 1.660, warm_led, col_1f)

    # Plump Cream Boucle Banquette Cushions (seat top EXACT 45.5cm = zf_1f + 0.450, protruding 10cm past -124mm cabinet front!)
    add_box_mm("1F_Dining_Banq_SeatCushion", -4040.0, -2752.0, -214.0, 100.0, z_1f + 0.415, z_1f + 0.455, boucle_mat, col_1f, r_corner=35.0)
    # 3D Sculpted Arched Backrest Cushion
    bm_bc = bmesh.new()
    nx_bc, nz_bc = 36, 14
    x0_bc, x1_bc = -4.000, -2.792
    for ix in range(nx_bc):
        ut = ix / float(nx_bc - 1)
        xv = x0_bc + ut * (x1_bc - x0_bc)
        usym = abs(2.0 * ut - 1.0)
        z_top_b = z_1f + 0.745 + 0.215 * (1.0 - usym * usym)
        for iz in range(nz_bc):
            vt = iz / float(nz_bc - 1)
            zv = (z_1f + 0.448) + vt * (z_top_b - (z_1f + 0.448))
            bulge = math.sin(max(0.0, min(1.0, vt)) * math.pi) ** 0.55 * math.sqrt(max(0.05, 1.0 - 0.85 * usym * usym))
            yv = 0.085 - 0.105 * bulge
            grid_wb[(ix, iz)] = bm_bc.verts.new((xv, yv, zv))
    back_vs = [bm_bc.verts.new((x0_bc + (ix / float(nx_bc - 1)) * (x1_bc - x0_bc), 0.140, grid_wb[(ix, nz_bc - 1)].co.z)) for ix in range(nx_bc)]
    bot_bvs = [bm_bc.verts.new((x0_bc + (ix / float(nx_bc - 1)) * (x1_bc - x0_bc), 0.140, z_1f + 0.448)) for ix in range(nx_bc)]
    for ix in range(nx_bc - 1):
        for iz in range(nz_bc - 1):
            f = bm_bc.faces.new([grid_wb[(ix, iz)], grid_wb[(ix + 1, iz)], grid_wb[(ix + 1, iz + 1)], grid_wb[(ix, iz + 1)]])
            f.smooth = True
        ft = bm_bc.faces.new([grid_wb[(ix, nz_bc - 1)], grid_wb[(ix + 1, nz_bc - 1)], back_vs[ix + 1], back_vs[ix]])
        ft.smooth = True
        fb = bm_bc.faces.new([bot_bvs[ix], bot_bvs[ix + 1], grid_wb[(ix + 1, 0)], grid_wb[(ix, 0)]])
        fb.smooth = True
    bmesh.ops.recalc_face_normals(bm_bc, faces=bm_bc.faces[:])
    m_bc = bpy.data.meshes.new("1F_Dining_Banq_BackCushion")
    bm_bc.to_mesh(m_bc)
    bm_bc.free()
    o_bc = bpy.data.objects.new("1F_Dining_Banq_BackCushion", m_bc)
    o_bc.data.materials.append(boucle_mat)
    link_obj(o_bc, col_1f)

    # 3D Blonde-Wood Arched Backrest Top Rail + Stepped Open-Slat Curved Armrests
    bm_ar = bmesh.new()
    n_ar = 32
    x0_ar, x1_ar = -4.080, -2.712
    a_rings = []
    for ix in range(n_ar + 1):
        ut = ix / float(n_ar)
        xv = x0_ar + ut * (x1_ar - x0_ar)
        usym = abs(2.0 * ut - 1.0)
        z_c = z_1f + 0.760 + 0.235 * (1.0 - usym * usym)
        y_c = 0.025 - 0.165 * (usym ** 3.2)
        ring = [
            bm_ar.verts.new((xv, y_c - 0.026, z_c - 0.018)),
            bm_ar.verts.new((xv, y_c + 0.026, z_c - 0.018)),
            bm_ar.verts.new((xv, y_c + 0.026, z_c + 0.022)),
            bm_ar.verts.new((xv, y_c - 0.026, z_c + 0.022)),
        ]
        a_rings.append(ring)
    for ix in range(n_ar):
        r0, r1 = a_rings[ix], a_rings[ix + 1]
        for k in range(4):
            kn = (k + 1) % 4
            f = bm_ar.faces.new([r0[k], r1[k], r1[kn], r0[kn]])
            f.smooth = True
    bm_ar.faces.new(a_rings[0][::-1])
    bm_ar.faces.new(a_rings[-1])
    bmesh.ops.recalc_face_normals(bm_ar, faces=bm_ar.faces[:])
    m_ar = bpy.data.meshes.new("1F_Dining_Banq_ArchRail")
    bm_ar.to_mesh(m_ar)
    bm_ar.free()
    o_ar = bpy.data.objects.new("1F_Dining_Banq_ArchRail", m_ar)
    o_ar.data.materials.append(eave_mat)
    link_obj(o_ar, col_1f)

    for s_tag, ax1, ax2 in (("L", -4092.0, -4032.0), ("R", -2760.0, -2700.0)):
        add_box_mm(f"1F_Dining_Banq_ArmPostF_{s_tag}", ax1, ax2, -206.0, -156.0, z_1f + 0.415, z_1f + 0.755, eave_mat, col_1f, r_corner=10.0)
        add_box_mm(f"1F_Dining_Banq_ArmPostB_{s_tag}", ax1, ax2, -60.0, 20.0, z_1f + 0.415, z_1f + 0.768, eave_mat, col_1f, r_corner=10.0)
        add_box_mm(f"1F_Dining_Banq_ArmRailLo_{s_tag}", ax1 + 6.0, ax2 - 6.0, -185.0, -45.0, z_1f + 0.565, z_1f + 0.600, eave_mat, col_1f)
        add_box_mm(f"1F_Dining_Banq_ArmRailHi_{s_tag}", ax1 - 4.0, ax2 + 4.0, -218.0, -35.0, z_1f + 0.710, z_1f + 0.760, eave_mat, col_1f, r_corner=12.0)

    # 4-Door Clear Slim Gold-Framed Glass Overhead Cabinet under Pagoda Eave (1.20m under-eave width: x: -3996..-2796, z: 1.66..2.12m)
    add_box_mm("1F_Dining_UpperCab_Soffit", -3996.0, -2796.0, -125.0, 185.0, z_1f + 1.660, z_1f + 1.682, eave_mat, col_1f)
    add_box_mm("1F_Dining_UpperCab_TopBox", -3996.0, -2796.0, -125.0, 185.0, z_1f + 2.115, z_1f + 2.140, eave_mat, col_1f)
    add_box_mm("1F_Dining_UpperCab_InBack", -3996.0, -2796.0, 145.0, 185.0, z_1f + 1.682, z_1f + 2.115, cab_mat, col_1f)
    add_box_mm("1F_Dining_UpperCab_MidShelf", -3994.0, -2798.0, -90.0, 145.0, z_1f + 1.882, z_1f + 1.894, cab_mat, col_1f)
    add_box_mm("1F_Dining_UpperCab_TopLED", -3976.0, -2816.0, 0.0, 22.0, z_1f + 2.104, z_1f + 2.115, warm_led, col_1f)
    add_box_mm("1F_Dining_UpperCab_MidLED", -3976.0, -2816.0, 0.0, 22.0, z_1f + 1.872, z_1f + 1.882, warm_led, col_1f)

    w_gd = (3996.0 - 2796.0) / 4.0
    for gi in range(4):
        gx1 = -3996.0 + gi * w_gd + 3.0
        gx2 = -3996.0 + (gi + 1) * w_gd - 3.0
        gxc = 0.5 * (gx1 + gx2)
        _add_tea_jar(f"1F_Dining_CabJarBot_{gi}", gxc, 35.0, z_1f + 1.682, 42.0, 128.0)
        _add_tea_jar(f"1F_Dining_CabJarTop_{gi}", gxc, 35.0, z_1f + 1.894, 42.0, 128.0)
        _add_hollow_frame_mm(f"1F_Dining_GlassDoorFrame_{gi}", gx1, gx2, -124.0, -104.0, z_1f + 1.682, z_1f + 2.115, 13.0, 0.013, gold_trim_mat, col_1f)
        add_box_mm(f"1F_Dining_GlassDoorPane_{gi}", gx1 + 13.0, gx2 - 13.0, -118.0, -110.0, z_1f + 1.695, z_1f + 2.102, cab_glass_mat, col_1f)
        hx_k = gx2 - 18.0 if gi % 2 == 0 else gx1 + 18.0
        add_box_mm(f"1F_Dining_GlassDoorPull_{gi}", hx_k - 4.0, hx_k + 4.0, -133.0, -124.0, z_1f + 1.760, z_1f + 1.885, gold_trim_mat, col_1f)

    # Suspended Carved Hanging Lotus Columns (垂莲柱) flanking the glass cabinet
    for p_tag, px in (("L", -4092.0), ("R", -2700.0)):
        add_cyl_mm(f"1F_Dining_LotusCol_Shaft_{p_tag}", px, -110.0, 50.0, z_1f + 1.660, z_1f + 2.210, eave_mat, col_1f, segs=20)
        add_cyl_mm(f"1F_Dining_LotusCol_Collar_{p_tag}", px, -110.0, 56.0, z_1f + 1.665, z_1f + 1.700, eave_deep_mat, col_1f, segs=20)
        add_cyl_mm(f"1F_Dining_LotusCol_DropA_{p_tag}", px, -110.0, 38.0, z_1f + 1.615, z_1f + 1.660, eave_mat, col_1f, segs=20)
        add_cyl_mm(f"1F_Dining_LotusCol_DropTip_{p_tag}", px, -110.0, 18.0, z_1f + 1.585, z_1f + 1.615, eave_deep_mat, col_1f, segs=16)

    # Carved Lattice Transom (花格) between glass cabinet and pagoda beam (z: 2.14..2.22m)
    for t_tag, tx1, tx2 in (("L", -4035.0, -3520.0), ("R", -3272.0, -2757.0)):
        _add_hollow_frame_mm(f"1F_Dining_LatticeFrame_{t_tag}", tx1, tx2, -135.0, -108.0, z_1f + 2.138, z_1f + 2.220, 12.0, 0.012, eave_mat, col_1f)
        for mi in range(1, 6):
            mx = tx1 + (tx2 - tx1) * mi / 6.0
            add_box_mm(f"1F_Dining_LatticeV_{t_tag}_{mi}", mx - 5.0, mx + 5.0, -132.0, -112.0, z_1f + 2.148, z_1f + 2.210, eave_mat, col_1f)
        add_box_mm(f"1F_Dining_LatticeH_{t_tag}", tx1 + 10.0, tx2 - 10.0, -132.0, -112.0, z_1f + 2.174, z_1f + 2.184, eave_mat, col_1f)

    # 3D Blonde-Wood Pagoda Flying-Eave Canopy (飞檐斗拱, x: -4360..-2432, rafters + upturned wings projecting cleanly out front)
    add_box_mm("1F_Dining_Pagoda_MainBeam", -4150.0, -2642.0, -225.0, -105.0, z_1f + 2.215, z_1f + 2.275, eave_mat, col_1f)
    add_box_mm("1F_Dining_Pagoda_SubBeam",  -4160.0, -2632.0, -255.0, -120.0, z_1f + 2.275, z_1f + 2.315, eave_deep_mat, col_1f)
    # 3D Dougong stepped brackets left & right
    for d_tag, dx in (("L", -4092.0), ("R", -2700.0)):
        for di, (dw, dd, dz0, dz1) in enumerate([
            (110.0, 85.0, 2.205, 2.240),
            (165.0, 125.0, 2.240, 2.275),
            (220.0, 165.0, 2.275, 2.315),
        ]):
            add_box_mm(f"1F_Dining_Dougong_{d_tag}_{di}", dx - dw * 0.5, dx + dw * 0.5, -120.0 - dd, -105.0, z_1f + dz0, z_1f + dz1, eave_deep_mat if di % 2 else eave_mat, col_1f)

    # 22 Cylindrical Wooden Roof Rafters & Round Eave Tiles (椽子 + 瓦当)
    n_rafters = 22
    bm_rf = bmesh.new()
    for ri in range(n_rafters):
        rx = -4.140 + 1.490 * (ri / float(n_rafters - 1))
        r_ring0, r_ring1 = [], []
        for k in range(10):
            a = 2.0 * math.pi * k / 10.0
            dx_r = 0.015 * math.cos(a)
            dz_r = 0.015 * math.sin(a)
            r_ring0.append(bm_rf.verts.new((rx + dx_r, -0.110, z_1f + 2.355 + dz_r)))
            r_ring1.append(bm_rf.verts.new((rx + dx_r, -0.305, z_1f + 2.295 + dz_r)))
        for k in range(10):
            kn = (k + 1) % 10
            f = bm_rf.faces.new([r_ring0[k], r_ring0[kn], r_ring1[kn], r_ring1[k]])
            f.smooth = True
        bm_rf.faces.new(r_ring0[::-1])
        bm_rf.faces.new(r_ring1)
    bmesh.ops.recalc_face_normals(bm_rf, faces=bm_rf.faces[:])
    m_rf = bpy.data.meshes.new("1F_Dining_Pagoda_Rafters")
    bm_rf.to_mesh(m_rf)
    bm_rf.free()
    o_rf = bpy.data.objects.new("1F_Dining_Pagoda_Rafters", m_rf)
    o_rf.data.materials.append(eave_mat)
    link_obj(o_rf, col_1f)

    # Sweeping 3D Pagoda Roof Deck & Upturned Flying-Eave Wingtips (cleanly proud of soffit y=-340 at tips!)
    bm_pk = bmesh.new()
    nx_pk, ny_pk = 36, 8
    x0_pk, x1_pk = -4.360, -2.432
    pk_bot, pk_top = {}, {}
    for ix in range(nx_pk + 1):
        ut = ix / float(nx_pk)
        xv = x0_pk + ut * (x1_pk - x0_pk)
        usym = abs(2.0 * ut - 1.0)
        lift = 0.145 * (max(0.0, usym - 0.62) / 0.38) ** 2.1
        y_tip = -0.305 - 0.068 * (max(0.0, usym - 0.58) / 0.42) ** 1.6
        yv_back = -0.115 if usym <= 0.72 else (-0.115 - 0.228 * ((usym - 0.72) / 0.28))
        for iy in range(ny_pk + 1):
            vt = iy / float(ny_pk)
            yv = yv_back * (1.0 - vt) + y_tip * vt
            curve_z = -0.055 * (vt ** 0.85) + lift * (0.45 + 0.55 * vt)
            zb = z_1f + 2.385 + curve_z
            zt = zb + 0.028 + 0.010 * (1.0 - vt)
            pk_bot[(ix, iy)] = bm_pk.verts.new((xv, yv, zb))
            pk_top[(ix, iy)] = bm_pk.verts.new((xv, yv, zt))
    for ix in range(nx_pk):
        for iy in range(ny_pk):
            ft = bm_pk.faces.new([pk_top[(ix, iy)], pk_top[(ix + 1, iy)], pk_top[(ix + 1, iy + 1)], pk_top[(ix, iy + 1)]])
            fb = bm_pk.faces.new([pk_bot[(ix + 1, iy)], pk_bot[(ix, iy)], pk_bot[(ix, iy + 1)], pk_bot[(ix + 1, iy + 1)]])
            ft.smooth = True
            fb.smooth = True
        ff = bm_pk.faces.new([pk_bot[(ix, ny_pk)], pk_bot[(ix + 1, ny_pk)], pk_top[(ix + 1, ny_pk)], pk_top[(ix, ny_pk)]])
        ff.smooth = True
        fbk = bm_pk.faces.new([pk_bot[(ix + 1, 0)], pk_bot[(ix, 0)], pk_top[(ix, 0)], pk_top[(ix + 1, 0)]])
        fbk.smooth = False
    for iy in range(ny_pk):
        bm_pk.faces.new([pk_bot[(0, iy)], pk_bot[(0, iy + 1)], pk_top[(0, iy + 1)], pk_top[(0, iy)]])
        bm_pk.faces.new([pk_bot[(nx_pk, iy + 1)], pk_bot[(nx_pk, iy)], pk_top[(nx_pk, iy)], pk_top[(nx_pk, iy + 1)]])
    bmesh.ops.recalc_face_normals(bm_pk, faces=bm_pk.faces[:])
    m_pk = bpy.data.meshes.new("1F_Dining_Pagoda_Canopy")
    bm_pk.to_mesh(m_pk)
    bm_pk.free()
    o_pk = bpy.data.objects.new("1F_Dining_Pagoda_Canopy", m_pk)
    o_pk.data.materials.append(eave_mat)
    link_obj(o_pk, col_1f)

    # 7. Module 4: Right Open Illuminated Display Showcase (-2644..-2111)
    _build_north_open_showcase("1F_Dining_Mod4", -2644.0, -2111.0, is_left=False)

    # 8. Module 5: Right Tall Flush Cabinet + End Pier
    add_box_mm("1F_Dining_Mod5_Tall_Carcass", -2111.0, -1593.0, -100.0, 260.0, zf_1f, z_1f + 2.458, cab_mat, col_1f)
    add_box_mm("1F_Dining_Mod5_Tall_Door",    -2107.5, -1596.5, -124.0, -114.0, z_1f + 0.051, z_1f + 2.456, cab_mat, col_1f)
    add_box_mm("1F_Dining_EastReturn_SidePier", -1590.0, -1488.0, -124.0, 260.0, z_1f + 0.049, z_1f + 2.458, cab_mat, col_1f)
    add_box_mm("1F_Dining_EastReturn_HallWall", -1488.0, -1150.0, 60.0, 260.0, zf_1f, z_1f + 2.60, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Dining_EastReturn_DoorReveal", -1150.0, -1110.0, 60.0, 260.0, z_1f + 2.00, z_1f + 2.60, MATS["Wall_Panel_White"], col_1f)
    add_box_mm("1F_Dining_EastReturn_CorridorBack", -1150.0, -850.0, 220.0, 265.0, zf_1f, z_1f + 2.60, MATS["Wall_New"], col_1f)

    # 9. Dining Room Flush Perimeter Soffit (North only; removed weird hanging West/East passage & toilet beams per user feedback)
    add_box_mm("1F_Dining_Header_North", -5600.0, -850.0, -340.0, 265.0, z_1f + 2.460, z_1f + 2.588, MATS["Pure_White_Ceiling"], col_1f)
    add_box_mm("1F_Dining_Cove_LED_N",   -5088.0, -1382.0, -356.0, -340.5, z_1f + 2.475, z_1f + 2.575, warm_led, col_1f)
    # 9b. Dining-to-Island Corridor 1.0m x 1.0m Recessed Ceiling Coffer & Traditional Chinese Caisson (藻井)
    #     Centered at ccx = -3350mm, ccy = -2280mm (opening x: -3850..-2850, y: -2780..-1780, z: 2.590..2.960m)
    add_box_mm("1F_Living_Ceiling_DiningWell_N", -5600.0, -850.0, -1780.0,   265.0, z_1f + 2.590, z_1f + 2.960, MATS["Pure_White_Ceiling"], col_1f)
    add_box_mm("1F_Living_Ceiling_DiningWell_S", -5600.0, -850.0, -5520.0, -2780.0, z_1f + 2.590, z_1f + 2.960, MATS["Pure_White_Ceiling"], col_1f)
    add_box_mm("1F_Living_Ceiling_DiningWell_W", -5600.0, -3850.0, -2780.0, -1780.0, z_1f + 2.590, z_1f + 2.960, MATS["Pure_White_Ceiling"], col_1f)
    add_box_mm("1F_Living_Ceiling_DiningWell_E", -2850.0,  -850.0, -2780.0, -1780.0, z_1f + 2.590, z_1f + 2.960, MATS["Pure_White_Ceiling"], col_1f)
    add_box_mm("1F_Living_Ceiling_Caisson_TopCap", -3950.0, -2750.0, -2880.0, -1680.0, z_1f + 2.960, z_1f + 3.040, MATS["Pure_White_Ceiling"], col_1f)
    add_box_mm("1F_Living_Ceiling_TrackSlot_N",  -3418.0, -3374.0, -1740.0, -620.0, z_1f + 2.574, z_1f + 2.590, MATS["OLO_ToeKick_Black"], col_1f)
    add_box_mm("1F_Living_Ceiling_TrackSlot_S",  -3418.0, -3374.0, -3200.0, -2820.0, z_1f + 2.574, z_1f + 2.590, MATS["OLO_ToeKick_Black"], col_1f)

    def build_1f_dining_caisson_zaojing():
        """Build 16-arm natural carved pale-wood helical spiral dougong caisson with 3D carved wood Phoenix center."""
        ccx, ccy = -3.350, -2.280

        def make_carved_wood_mat(mname, base_rgba, grain_dark, rough=0.44, bump_s=0.05, coat=0.06):
            mat = bpy.data.materials.new(name=mname)
            mat.use_nodes = True
            nt = mat.node_tree
            bsdf = nt.nodes.get("Principled BSDF")
            if bsdf is not None:
                # Set explicit Base Color default_value so glTF/WebGL exports exact warm pale wood tone cleanly
                bsdf.inputs["Base Color"].default_value = base_rgba
                bsdf.inputs["Metallic"].default_value = 0.0
                bsdf.inputs["Roughness"].default_value = rough
                if "Coat Weight" in bsdf.inputs:
                    bsdf.inputs["Coat Weight"].default_value = coat
                try:
                    tc = nt.nodes.new("ShaderNodeTexCoord")
                    mp = nt.nodes.new("ShaderNodeMapping")
                    mp.inputs["Scale"].default_value = (12.0, 2.2, 6.0)
                    ns = nt.nodes.new("ShaderNodeTexNoise")
                    ns.inputs["Scale"].default_value = 14.0
                    ns.inputs["Detail"].default_value = 8.0
                    ns.inputs["Roughness"].default_value = 0.65
                    ns.inputs["Distortion"].default_value = 0.45
                    rmp = nt.nodes.new("ShaderNodeValToRGB")
                    rmp.color_ramp.elements[0].position = 0.25
                    rmp.color_ramp.elements[0].color = (max(0.18, rough - 0.07),) * 3 + (1.0,)
                    rmp.color_ramp.elements[1].position = 0.78
                    rmp.color_ramp.elements[1].color = (min(0.85, rough + 0.08),) * 3 + (1.0,)
                    bmp = nt.nodes.new("ShaderNodeBump")
                    bmp.inputs["Strength"].default_value = bump_s
                    bmp.inputs["Distance"].default_value = 0.0015
                    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
                    nt.links.new(mp.outputs["Vector"], ns.inputs["Vector"])
                    nt.links.new(ns.outputs["Fac"], rmp.inputs["Fac"])
                    nt.links.new(rmp.outputs["Color"], bsdf.inputs["Roughness"])
                    nt.links.new(ns.outputs["Fac"], bmp.inputs["Height"])
                    nt.links.new(bmp.outputs["Normal"], bsdf.inputs["Normal"])
                except Exception:
                    pass
            return mat

        caisson_wood_pale = make_carved_wood_mat("Caisson_Spiral_WoodPale", (0.84, 0.75, 0.62, 1.0), (0.76, 0.66, 0.53, 1.0), rough=0.42, bump_s=0.05, coat=0.08)
        caisson_wood_mid  = make_carved_wood_mat("Caisson_Spiral_WoodMid",  (0.70, 0.57, 0.42, 1.0), (0.60, 0.47, 0.33, 1.0), rough=0.48, bump_s=0.07, coat=0.04)
        caisson_wood_deep = make_carved_wood_mat("Caisson_Spiral_WoodDeep", (0.45, 0.34, 0.23, 1.0), (0.36, 0.27, 0.18, 1.0), rough=0.58, bump_s=0.05, coat=0.02)

        # Center carved blonde-wood Phoenix medallion material (packed so .blend & 1F.glb stay self-contained)
        caisson_phoenix_mat = bpy.data.materials.new(name="Caisson_Phoenix_Medallion")
        caisson_phoenix_mat.use_nodes = True
        _p_nt = caisson_phoenix_mat.node_tree
        _p_bsdf = _p_nt.nodes.get("Principled BSDF")
        if _p_bsdf is not None:
            _p_bsdf.inputs["Base Color"].default_value = (0.84, 0.75, 0.62, 1.0)
            _p_bsdf.inputs["Metallic"].default_value = 0.0
            _p_bsdf.inputs["Roughness"].default_value = 0.44
            if "Coat Weight" in _p_bsdf.inputs:
                _p_bsdf.inputs["Coat Weight"].default_value = 0.08
            _p_tc = _p_nt.nodes.new("ShaderNodeTexCoord")

            def _load_packed_tex(fname, non_color=False):
                _tp = os.path.join(OUT_DIR, "textures", fname)
                _im = bpy.data.images.load(_tp, check_existing=True)
                if non_color:
                    _im.colorspace_settings.name = "Non-Color"
                try:
                    _im.pack()
                except Exception:
                    pass
                _tn = _p_nt.nodes.new("ShaderNodeTexImage")
                _tn.image = _im
                _tn.extension = "EXTEND"
                _p_nt.links.new(_p_tc.outputs["UV"], _tn.inputs["Vector"])
                return _tn

            _tn_col = _load_packed_tex("tex_caisson_phoenix_wood.png", non_color=False)
            _tn_rgh = _load_packed_tex("tex_caisson_phoenix_rough.png", non_color=True)
            _tn_nrm = _load_packed_tex("tex_caisson_phoenix_normal.png", non_color=True)
            _p_nrm_node = _p_nt.nodes.new("ShaderNodeNormalMap")
            _p_nrm_node.inputs["Strength"].default_value = 1.40
            _p_nt.links.new(_tn_col.outputs["Color"], _p_bsdf.inputs["Base Color"])
            _p_nt.links.new(_tn_rgh.outputs["Color"], _p_bsdf.inputs["Roughness"])
            _p_nt.links.new(_tn_nrm.outputs["Color"], _p_nrm_node.inputs["Color"])
            _p_nt.links.new(_p_nrm_node.outputs["Normal"], _p_bsdf.inputs["Normal"])

        bm_pale = bmesh.new()
        bm_mid  = bmesh.new()
        bm_deep = bmesh.new()
        bm_led  = bmesh.new()

        def bm_poly_ring(bm, pts_out, pts_in, z0, z1, smooth_sides=False):
            n = len(pts_out)
            ob = [bm.verts.new((ccx + px, ccy + py, z_1f + z0)) for px, py in pts_out]
            ot = [bm.verts.new((ccx + px, ccy + py, z_1f + z1)) for px, py in pts_out]
            ib = [bm.verts.new((ccx + px, ccy + py, z_1f + z0)) for px, py in pts_in]
            it = [bm.verts.new((ccx + px, ccy + py, z_1f + z1)) for px, py in pts_in]
            for i in range(n):
                j = (i + 1) % n
                f1 = bm.faces.new([ob[i], ob[j], ot[j], ot[i]])
                f2 = bm.faces.new([ib[j], ib[i], it[i], it[j]])
                f3 = bm.faces.new([ot[i], ot[j], it[j], it[i]])
                f4 = bm.faces.new([ib[i], ib[j], ob[j], ob[i]])
                f1.smooth = smooth_sides
                f2.smooth = smooth_sides

        def sq_pts(half):
            return [(-half, -half), (half, -half), (half, half), (-half, half)]

        def circ_pts(radius, segs=64):
            return [(radius * math.cos(2.0 * math.pi * k / segs), radius * math.sin(2.0 * math.pi * k / segs)) for k in range(segs)]

        def add_quad_prism(bm, pts4, z0, z1):
            vb = [bm.verts.new((ccx + px, ccy + py, z_1f + z0)) for px, py in pts4]
            vt = [bm.verts.new((ccx + px, ccy + py, z_1f + z1)) for px, py in pts4]
            bm.faces.new(list(reversed(vb)))
            bm.faces.new(vt)
            for i in range(4):
                j = (i + 1) % 4
                bm.faces.new([vb[i], vb[j], vt[j], vt[i]])

        # 1. Outer Square Molding, Enclosure Shaft & Watertight Carved Spandrel Corners (z: 2.586..2.960)
        bm_poly_ring(bm_pale, sq_pts(0.516), sq_pts(0.498), 2.590, 2.960)
        bm_poly_ring(bm_pale, sq_pts(0.506), sq_pts(0.474), 2.590, 2.630)

        n_sp = 64
        sp_in, sp_out = [], []
        for k in range(n_sp):
            a = 2.0 * math.pi * k / n_sp
            ca, sa = math.cos(a), math.sin(a)
            s_max = max(abs(ca), abs(sa), 1e-6)
            sp_out.append((0.482 * ca / s_max, 0.482 * sa / s_max))
            sp_in.append((0.454 * ca, 0.454 * sa))
        bm_poly_ring(bm_pale, sp_out, sp_in, 2.606, 2.630)

        # Subtle carved corner spandrel scroll reliefs inside the 4 corner triangles
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                for idx_c, (dcx, dcy, dr, ang0, span) in enumerate([
                    (0.422, 0.422, 0.032, 0.0, 1.4),
                    (0.428, 0.340, 0.022, 0.3, 1.6),
                    (0.340, 0.428, 0.022, -0.3, 1.6),
                ]):
                    for s_i in range(4):
                        u_a = ang0 + span * (s_i / 4.0)
                        u_b = ang0 + span * ((s_i + 1) / 4.0)
                        pxa = sx * (dcx + dr * math.cos(u_a) * 0.65)
                        pya = sy * (dcy + dr * math.sin(u_a) * 0.65)
                        pxb = sx * (dcx + dr * math.cos(u_b) * 0.65)
                        pyb = sy * (dcy + dr * math.sin(u_b) * 0.65)
                        tx, ty = -(pyb - pya), (pxb - pxa)
                        t_l = max(math.hypot(tx, ty), 1e-5)
                        tx, ty = 0.008 * tx / t_l, 0.008 * ty / t_l
                        add_quad_prism(bm_mid, [(pxa - tx, pya - ty), (pxb - tx, pyb - ty), (pxb + tx, pyb + ty), (pxa + tx, pya + ty)], 2.601, 2.607)

        # 2. Heavy Circular Outer Wooden Bezel (R: 0.472 -> 0.428, proud below 2.590 ceiling) + Concealed Uplight LED
        bm_poly_ring(bm_pale, circ_pts(0.472, 64), circ_pts(0.428, 64), 2.586, 2.636, smooth_sides=True)
        bm_poly_ring(bm_mid,  circ_pts(0.436, 64), circ_pts(0.426, 64), 2.626, 2.640, smooth_sides=True)
        bm_poly_ring(bm_led,  circ_pts(0.442, 48), circ_pts(0.432, 48), 2.638, 2.645, smooth_sides=True)

        # 3. 16-Tier Stepped Helical Concentric Dome + Scalloped Cloud Dentils + 16 Cantilevered Spiral Dougong Ribs
        n_arms = 16
        n_tiers = 16
        d_ang = 2.0 * math.pi / n_arms

        tier_r = []
        tier_z = []
        tier_twist = []
        for k in range(n_tiers):
            tk = k / float(n_tiers - 1)
            rk = 0.426 - (0.426 - 0.206) * (tk ** 0.92)
            zk = 2.626 + 0.294 * (1.0 - (1.0 - tk) ** 1.48)
            tw = math.radians(6.4) * k  # +96 deg total clockwise swirl inward when looking UP
            tier_r.append(rk)
            tier_z.append(zk)
            tier_twist.append(tw)

        def cyl_arc_prism(bm, r0, r1, a0, a1, z0, z1, sub_a=2):
            pts_out, pts_in = [], []
            for s in range(sub_a + 1):
                aa = a0 + (a1 - a0) * (s / float(sub_a))
                ca, sa = math.cos(aa), math.sin(aa)
                pts_out.append((r1 * ca, r1 * sa))
                pts_in.append((r0 * ca, r0 * sa))
            verts_b_out = [bm.verts.new((ccx + x, ccy + y, z_1f + z0)) for x, y in pts_out]
            verts_t_out = [bm.verts.new((ccx + x, ccy + y, z_1f + z1)) for x, y in pts_out]
            verts_b_in  = [bm.verts.new((ccx + x, ccy + y, z_1f + z0)) for x, y in pts_in]
            verts_t_in  = [bm.verts.new((ccx + x, ccy + y, z_1f + z1)) for x, y in pts_in]
            for s in range(sub_a):
                bm.faces.new([verts_b_in[s + 1], verts_b_in[s], verts_t_in[s], verts_t_in[s + 1]])
                bm.faces.new([verts_b_out[s], verts_b_out[s + 1], verts_t_out[s + 1], verts_t_out[s]])
                bm.faces.new([verts_t_in[s], verts_t_out[s], verts_t_out[s + 1], verts_t_in[s + 1]])
                bm.faces.new([verts_b_out[s], verts_b_in[s], verts_b_in[s + 1], verts_b_out[s + 1]])
            bm.faces.new([verts_b_in[0], verts_b_out[0], verts_t_out[0], verts_t_in[0]])
            bm.faces.new([verts_b_out[-1], verts_b_in[-1], verts_t_in[-1], verts_t_out[-1]])

        for k in range(n_tiers):
            tk = k / float(n_tiers - 1)
            rk = tier_r[k]
            zk = tier_z[k]
            z_top = (tier_z[k + 1] + 0.014) if (k + 1 < n_tiers) else (zk + 0.020)
            tw = tier_twist[k]
            sc = 0.36 + 0.64 * (1.0 - tk)

            for ia in range(n_arms):
                a0 = ia * d_ang + tw
                a1 = (ia + 1) * d_ang + tw

                # Recessed shadow riser + horizontal timber lintel beam + 4 carved scalloped dentil teeth per bay
                cyl_arc_prism(bm_deep, rk + 0.008, rk + 0.019, a0, a1, zk, z_top, sub_a=2)
                cyl_arc_prism(bm_mid,  rk, rk + 0.025, a0, a1, zk, zk + 0.011, sub_a=2)
                for di in range(4):
                    fa0 = a0 + d_ang * (0.12 + di * 0.21)
                    fa1 = fa0 + d_ang * 0.13
                    dh = 0.0065 * sc
                    cyl_arc_prism(bm_pale, rk + 0.001, rk + 0.008, fa0, fa1, zk - dh, zk + 0.001, sub_a=1)

                # Cantilevered curved wooden spiral dougong bracket blade (螺旋昂翼) along arm ia at tier k
                r_root = rk + 0.014
                r_len = 0.068 * sc
                z_root = zk + 0.010
                drop_z = 0.026 * sc
                stations = []
                for js in range(4):
                    u = js / 3.0
                    rr_s = r_root - r_len * u
                    aa_s = a0 + math.radians(8.5 * sc) * (u ** 1.15)
                    zz_s = z_root - drop_z * (u ** 0.85) + (0.004 * sc if js == 3 else 0.0)
                    hw = (0.0085 * (1.0 - 0.74 * u)) * sc
                    hh = (0.0220 * (1.0 - 0.76 * u)) * sc
                    rx, ry = math.cos(aa_s), math.sin(aa_s)
                    tx, ty = -ry, rx
                    v0 = bm_pale.verts.new((ccx + rr_s * rx - hw * tx, ccy + rr_s * ry - hw * ty, z_1f + zz_s - hh * 0.5))
                    v1 = bm_pale.verts.new((ccx + rr_s * rx + hw * tx, ccy + rr_s * ry + hw * ty, z_1f + zz_s - hh * 0.5))
                    v2 = bm_pale.verts.new((ccx + rr_s * rx + hw * tx, ccy + rr_s * ry + hw * ty, z_1f + zz_s + hh * 0.5))
                    v3 = bm_pale.verts.new((ccx + rr_s * rx - hw * tx, ccy + rr_s * ry - hw * ty, z_1f + zz_s + hh * 0.5))
                    stations.append((v0, v1, v2, v3))
                for js in range(3):
                    for q in range(4):
                        qn = (q + 1) % 4
                        f = bm_pale.faces.new([stations[js][q], stations[js][qn], stations[js + 1][qn], stations[js + 1][q]])
                        f.smooth = True
                bm_pale.faces.new([stations[0][3], stations[0][2], stations[0][1], stations[0][0]])
                bm_pale.faces.new([stations[-1][0], stations[-1][1], stations[-1][2], stations[-1][3]])

                # Crisp recessed dark shadow notch under each bracket root for high-contrast depth
                aa_n = a0 + math.radians(2.0 * sc)
                rxn, ryn = math.cos(aa_n), math.sin(aa_n)
                txn, tyn = -ryn, rxn
                rnb, rnf = rk + 0.012, rk - 0.004 * sc
                hnw = 0.007 * sc
                add_quad_prism(
                    bm_deep,
                    [
                        (rnb * rxn - hnw * txn, rnb * ryn - hnw * tyn),
                        (rnb * rxn + hnw * txn, rnb * ryn + hnw * tyn),
                        (rnf * rxn + hnw * txn, rnf * ryn + hnw * tyn),
                        (rnf * rxn - hnw * txn, rnf * ryn - hnw * tyn),
                    ],
                    zk - 0.004 * sc,
                    zk + 0.006 * sc,
                )

        # 4. Central Enlarged Bead Ring + High-Relief 3D Displaced Phoenix Medallion (410mm dia, disp=42mm) + 3D Descending Head
        bm_poly_ring(bm_pale, circ_pts(0.216, 64), circ_pts(0.202, 64), 2.898, 2.926, smooth_sides=True)

        bm_phx = bmesh.new()
        uv_layer = bm_phx.loops.layers.uv.new("UVMap")
        h_path = os.path.join(OUT_DIR, "textures", "tex_caisson_phoenix_height.png")
        img_h = bpy.data.images.load(h_path, check_existing=True)
        img_h.colorspace_settings.name = "Non-Color"
        hw, hh = img_h.size[0], img_h.size[1]
        h_arr = np.asarray(img_h.pixels[:], dtype=np.float32).reshape(hh, hw, 4)[:, :, 0]

        nr_p, na_p = 56, 112
        r_phx = 0.205
        z_base_p = 2.922
        z_back_p = 2.948
        disp_max = 0.042

        def sample_h_uv(u, v):
            ix = min(hw - 1, max(0, int(round(u * (hw - 1)))))
            iy = min(hh - 1, max(0, int(round(v * (hh - 1)))))
            return float(h_arr[iy, ix])

        # Center vertex
        h_c = sample_h_uv(0.5, 0.5)
        v_center = bm_phx.verts.new((ccx, ccy, z_1f + z_base_p - disp_max * h_c))

        rings_front = []
        rings_uv = []
        for ir in range(1, nr_p + 1):
            frac = ir / float(nr_p)
            rr = r_phx * frac
            rim_fade = 1.0 if frac <= 0.92 else max(0.0, (1.0 - frac) / 0.08)
            row_v, row_uv = [], []
            for ia in range(na_p):
                a = 2.0 * math.pi * ia / na_p
                lx = rr * math.cos(a)
                ly = rr * math.sin(a)
                # Corridor (+X Right, -Y Top) & Closeup (roll_up=-Y) consistent un-mirrored orientation:
                u = 0.5 + lx / (2.0 * r_phx)
                v = 0.5 - ly / (2.0 * r_phx)
                hv = sample_h_uv(u, v)
                pz = z_base_p - disp_max * hv * rim_fade
                row_v.append(bm_phx.verts.new((ccx + lx, ccy + ly, z_1f + pz)))
                row_uv.append((u, v))
            rings_front.append(row_v)
            rings_uv.append(row_uv)

        # Center fan (-Z facing down)
        for ia in range(na_p):
            ian = (ia + 1) % na_p
            f = bm_phx.faces.new([v_center, rings_front[0][ian], rings_front[0][ia]])
            f.smooth = True
            for lp, uv in zip(f.loops, [(0.5, 0.5), rings_uv[0][ian], rings_uv[0][ia]]):
                lp[uv_layer].uv = uv

        # Concentric polar rings (-Z facing down)
        for ir in range(nr_p - 1):
            for ia in range(na_p):
                ian = (ia + 1) % na_p
                f = bm_phx.faces.new([rings_front[ir][ia], rings_front[ir][ian], rings_front[ir + 1][ian], rings_front[ir + 1][ia]])
                f.smooth = True
                uvs = [rings_uv[ir][ia], rings_uv[ir][ian], rings_uv[ir + 1][ian], rings_uv[ir + 1][ia]]
                for lp, uv in zip(f.loops, uvs):
                    lp[uv_layer].uv = uv

        # Flat watertight perimeter skirt & top backing cap (z_back_p = 2.944)
        back_ring = [
            bm_phx.verts.new((ccx + r_phx * math.cos(2.0 * math.pi * ia / na_p), ccy + r_phx * math.sin(2.0 * math.pi * ia / na_p), z_1f + z_back_p))
            for ia in range(na_p)
        ]
        for ia in range(na_p):
            ian = (ia + 1) % na_p
            fs = bm_phx.faces.new([rings_front[-1][ia], rings_front[-1][ian], back_ring[ian], back_ring[ia]])
            fs.smooth = False
            for lp in fs.loops:
                lp[uv_layer].uv = (0.0, 0.0)
        f_cap = bm_phx.faces.new(back_ring)
        f_cap.smooth = False
        for lp in f_cap.loops:
            lp[uv_layer].uv = (0.0, 0.0)

        bmesh.ops.recalc_face_normals(bm_phx, faces=bm_phx.faces[:])
        sharp_p = [e for e in bm_phx.edges if len(e.link_faces) == 2 and e.link_faces[0].smooth != e.link_faces[1].smooth]
        if sharp_p:
            bmesh.ops.split_edges(bm_phx, edges=sharp_p)
        m_phx = bpy.data.meshes.new("1F_Living_Ceiling_Caisson_Phoenix")
        bm_phx.to_mesh(m_phx)
        bm_phx.free()
        o_phx = bpy.data.objects.new("1F_Living_Ceiling_Caisson_Phoenix", m_phx)
        o_phx.data.materials.append(caisson_phoenix_mat)
        link_obj(o_phx, col_1f)

        # 4b. High-Relief 3D Downward-Protruding Sculpted Wooden Phoenix Head, S-Neck, Beak & Three-Plume Crest
        # (`高空俯冲盘凤立体龙头质感`): emerges cleanly from neck locus (lx~-0.012, ly~-0.028) & drops 62mm below relief!
        bm_hd = bmesh.new()

        def _loft_tube(bm, pts_r_segs, smooth=True):
            ring_vs = []
            n_pt = len(pts_r_segs)
            for idx_t, (px, py, pz, rx_m, rz_m) in enumerate(pts_r_segs):
                p0 = pts_r_segs[max(0, idx_t - 1)]
                p1 = pts_r_segs[min(n_pt - 1, idx_t + 1)]
                tx, ty, tz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
                tl = max(math.hypot(tx, ty, tz), 1e-6)
                tx, ty, tz = tx / tl, ty / tl, tz / tl
                # Robust perpendicular frame (side axis along XY cross up=(0,0,1), else X)
                ux, uy = -ty, tx
                ul = math.hypot(ux, uy)
                if ul < 1e-4:
                    ux, uy = 1.0, 0.0
                else:
                    ux, uy = ux / ul, uy / ul
                bx, by, bz = ty * 0.0 - tz * uy, tz * ux - tx * 0.0, tx * uy - ty * ux
                bl = max(math.hypot(bx, by, bz), 1e-6)
                bx, by, bz = bx / bl, by / bl, bz / bl
                n_s = 14
                rv = []
                for k in range(n_s):
                    a = 2.0 * math.pi * k / float(n_s)
                    ca, sa = math.cos(a), math.sin(a)
                    vx = ccx + px + rx_m * ca * ux + rz_m * sa * bx
                    vy = ccy + py + rx_m * ca * uy + rz_m * sa * by
                    vz = z_1f + pz + rz_m * sa * bz
                    rv.append(bm.verts.new((vx, vy, vz)))
                ring_vs.append(rv)
            n_s = len(ring_vs[0])
            for idx_t in range(n_pt - 1):
                r0, r1 = ring_vs[idx_t], ring_vs[idx_t + 1]
                for k in range(n_s):
                    kn = (k + 1) % n_s
                    f = bm.faces.new([r0[k], r0[kn], r1[kn], r1[k]])
                    f.smooth = smooth
            bm.faces.new(ring_vs[0][::-1])
            bm.faces.new(ring_vs[-1])

        # S-curved protruding muscular neck -> deep carved head dome (drop reaches z_base_p - 0.062)
        z_neck0 = z_base_p - 0.020
        neck_pts = [
            (-0.016, -0.012, z_neck0,        0.022, 0.016),
            (-0.024, -0.042, z_neck0 - 0.014, 0.018, 0.015),
            (-0.010, -0.068, z_neck0 - 0.032, 0.016, 0.015),
            ( 0.008, -0.068, z_neck0 - 0.042, 0.019, 0.017),  # proud sculpted head dome (-62mm total!)
            ( 0.020, -0.062, z_neck0 - 0.044, 0.014, 0.013),
        ]
        _loft_tube(bm_hd, neck_pts, smooth=True)
        # Upper hooked Phoenix beak & fierce lower mandible angled downward toward dining table
        _loft_tube(bm_hd, [
            (0.016, -0.064, z_neck0 - 0.043, 0.008, 0.007),
            (0.032, -0.056, z_neck0 - 0.047, 0.006, 0.005),
            (0.046, -0.048, z_neck0 - 0.053, 0.002, 0.002),
        ], smooth=True)
        _loft_tube(bm_hd, [
            (0.016, -0.060, z_neck0 - 0.040, 0.005, 0.004),
            (0.034, -0.052, z_neck0 - 0.045, 0.002, 0.002),
        ], smooth=True)
        # Three sweeping backward-arched 3D carved crown plumes (`三翎立体凤冠`)
        for c_off_x, c_off_y, c_len in ((0.0, 0.0, 1.0), (-0.008, 0.010, 0.92), (-0.015, 0.020, 0.80)):
            _loft_tube(bm_hd, [
                (0.002 + c_off_x * 0.4, -0.072 + c_off_y * 0.4, z_neck0 - 0.038, 0.0065, 0.0055),
                (-0.026 + c_off_x, -0.095 + c_off_y, z_neck0 - 0.030, 0.0055 * c_len, 0.0045 * c_len),
                (-0.058 + c_off_x * 1.2, -0.102 + c_off_y * 1.1, z_neck0 - 0.018, 0.0038 * c_len, 0.0032 * c_len),
                (-0.080 + c_off_x * 1.2, -0.088 + c_off_y * 1.1, z_neck0 - 0.010, 0.0050, 0.0040),
            ], smooth=True)
        bmesh.ops.recalc_face_normals(bm_hd, faces=bm_hd.faces[:])
        m_hd = bpy.data.meshes.new("1F_Living_Ceiling_Caisson_Phoenix3DHead")
        bm_hd.to_mesh(m_hd)
        bm_hd.free()
        o_hd = bpy.data.objects.new("1F_Living_Ceiling_Caisson_Phoenix3DHead", m_hd)
        o_hd.data.materials.append(caisson_wood_pale)
        link_obj(o_hd, col_1f)

        # Finalize carved wood & LED watertight meshes prefixed with 1F_Living_Ceiling_Caisson_
        for sfx, bm_s, mat_s in (
            ("WoodPale", bm_pale, caisson_wood_pale),
            ("WoodMid",  bm_mid,  caisson_wood_mid),
            ("WoodDeep", bm_deep, caisson_wood_deep),
            ("LED",      bm_led,  warm_led),
        ):
            bmesh.ops.recalc_face_normals(bm_s, faces=bm_s.faces[:])
            sharp_s = [e for e in bm_s.edges if len(e.link_faces) == 2 and e.link_faces[0].smooth != e.link_faces[1].smooth]
            if sharp_s:
                bmesh.ops.split_edges(bm_s, edges=sharp_s)
            m_s = bpy.data.meshes.new(f"1F_Living_Ceiling_Caisson_{sfx}")
            bm_s.to_mesh(m_s)
            bm_s.free()
            o_s = bpy.data.objects.new(f"1F_Living_Ceiling_Caisson_{sfx}", m_s)
            o_s.data.materials.append(mat_s)
            link_obj(o_s, col_1f)

    build_1f_dining_caisson_zaojing()
    for _d_dlx in [-4250.0, -4020.0, -2770.0, -2540.0]:
        add_cyl_mm(f"1F_Living_Ceiling_DiningDL_{int(abs(_d_dlx))}", _d_dlx, -680.0, 26.0, z_1f + 2.582, z_1f + 2.590, warm_led, col_1f, segs=20)
    # - 1F Toilet Only (2000 x 1257mm, x: -1488..+512, y: -5520..-4263; 马桶背靠厨房西墙 x=-1488 面向东 +X)
    add_box_mm("1F_Toilet_Base", -1478, -778, -5215, -4755, zf_1f, z_1f + 0.42, MATS["Sanitary_White"], col_1f, r_corner=90.0)
    add_box_mm("1F_Toilet_Seat", -1258, -758, -5195, -4775, z_1f + 0.422, z_1f + 0.46, MATS["Sanitary_White"], col_1f, r_corner=85.0)
    add_box_mm("1F_Toilet_Tank", -1478, -1268, -5215, -4755, z_1f + 0.422, z_1f + 0.78, MATS["Sanitary_White"], col_1f, r_corner=35.0)
    # - 1F Living Room: Open Symmetrical "(  )" White Boucle Curved Sofas + Sculpted Split-Lotus Ceiling Canopy & Gold-Leaf Chandelier
    def build_1f_living_ring_sofa_and_tree():
        scx_mm, scy_mm = 2723.5, -2750.0
        scx_m, scy_m = scx_mm * MM, scy_mm * MM

        def add_open_arc_profile(name, deg0, deg1, n_seg, profile_rz, mat, smooth=True, cap_ends=True):
            mesh_r = bpy.data.meshes.new(name)
            bm_r = bmesh.new()
            rings = []
            for k in range(n_seg + 1):
                t = k / float(n_seg)
                a = math.radians(deg0 + (deg1 - deg0) * t)
                ca, sa = math.cos(a), math.sin(a)
                ring = []
                for rr_mm, zz_rel in profile_rz:
                    ring.append(bm_r.verts.new(((scx_mm + rr_mm * ca) * MM, (scy_mm + rr_mm * sa) * MM, z_1f + zz_rel)))
                rings.append(ring)
            np_len = len(profile_rz)
            for k in range(n_seg):
                r0, r1 = rings[k], rings[k + 1]
                for pi in range(np_len):
                    pin = (pi + 1) % np_len
                    f = bm_r.faces.new([r0[pi], r1[pi], r1[pin], r0[pin]])
                    f.smooth = smooth
            if cap_ends and np_len >= 3:
                f_a = bm_r.faces.new(rings[0][::-1])
                f_b = bm_r.faces.new(rings[-1])
                f_a.smooth = False
                f_b.smooth = False
                for fc in (f_a, f_b):
                    if len(fc.verts) > 4:
                        bmesh.ops.triangulate(bm_r, faces=[fc], quad_method='BEAUTY', ngon_method='BEAUTY')
            bmesh.ops.recalc_face_normals(bm_r, faces=bm_r.faces[:])
            if smooth:
                sharp_r = [e for e in bm_r.edges if len(e.link_faces) == 2 and (e.link_faces[0].smooth != e.link_faces[1].smooth or e.link_faces[0].normal.dot(e.link_faces[1].normal) < 0.72)]
                if sharp_r:
                    bmesh.ops.split_edges(bm_r, edges=sharp_r)
            bm_r.to_mesh(mesh_r)
            bm_r.free()
            obj_r = bpy.data.objects.new(name, mesh_r)
            obj_r.data.materials.append(mat)
            link_obj(obj_r, col_1f)
            return obj_r

        # 1. Circular Radial Black-and-White Contemporary Art Rug
        add_cyl_mm("1F_Living_Rug_Circular", scx_mm, scy_mm, 1750.0, z_1f + 0.003, z_1f + 0.015, MATS["Living_Radial_BW_Rug"], col_1f, segs=64)

        # 2. Two Open Parentheses "(  )" White Boucle Curved Sofas (facing inward across open central corridor)
        toe_prof = [(920.0, 0.005), (1460.0, 0.005), (1460.0, 0.055), (920.0, 0.055)]
        seat_prof = [
            (890.0, 0.055), (1485.0, 0.055), (1505.0, 0.110), (1505.0, 0.340),
            (1470.0, 0.398), (1380.0, 0.415), (930.0, 0.415), (870.0, 0.385), (860.0, 0.230), (872.0, 0.095),
        ]
        back_prof = [
            (1320.0, 0.405), (1505.0, 0.405), (1522.0, 0.520), (1508.0, 0.655),
            (1465.0, 0.715), (1390.0, 0.722), (1335.0, 0.675), (1315.0, 0.535),
        ]
        for s_tag, d0, d1 in (("ArcL", -56.0, 56.0), ("ArcR", 124.0, 236.0)):
            add_open_arc_profile(f"1F_Living_Sofa_{s_tag}_Base", d0, d1, 24, toe_prof, MATS["OLO_ToeKick_Black"], smooth=False)
            add_open_arc_profile(f"1F_Living_Sofa_{s_tag}_Seat", d0, d1, 28, seat_prof, MATS["Sofa_White_Boucle"], smooth=True)
            add_open_arc_profile(f"1F_Living_Sofa_{s_tag}_Back", d0, d1, 28, back_prof, MATS["Sofa_White_Boucle"], smooth=True)
            # Rounded vertical armrest/end bolster cushions at both ends of each crescent
            for e_i, deg_end in enumerate((d0, d1), 1):
                ae = math.radians(deg_end)
                ex = scx_mm + 1190.0 * math.cos(ae)
                ey = scy_mm + 1190.0 * math.sin(ae)
                bm_e = bmesh.new()
                bmesh.ops.create_uvsphere(bm_e, u_segments=20, v_segments=12, radius=1.0)
                rot_e = mathutils.Matrix.Rotation(ae, 4, 'Z')
                for v in bm_e.verts:
                    p = mathutils.Vector((v.co.x * 0.295, v.co.y * 0.085, v.co.z * 0.165))
                    pr = rot_e @ p
                    v.co = (ex * MM + pr.x, ey * MM + pr.y, z_1f + 0.245 + pr.z)
                for f in bm_e.faces:
                    f.smooth = True
                bmesh.ops.recalc_face_normals(bm_e, faces=bm_e.faces[:])
                me = bpy.data.meshes.new(f"1F_Living_Sofa_{s_tag}_Cap_{e_i}")
                bm_e.to_mesh(me)
                bm_e.free()
                oe = bpy.data.objects.new(f"1F_Living_Sofa_{s_tag}_Cap_{e_i}", me)
                oe.data.materials.append(MATS["Sofa_White_Boucle"])
                link_obj(oe, col_1f)

            # 3 soft plush throw cushions nestled along the inner curved backrest
            d_mid = 0.5 * (d0 + d1)
            for p_i, p_deg in enumerate((d_mid - 30.0, d_mid, d_mid + 30.0), 1):
                a = math.radians(p_deg)
                px = scx_mm + 1230.0 * math.cos(a)
                py = scy_mm + 1230.0 * math.sin(a)
                bm_p = bmesh.new()
                bmesh.ops.create_icosphere(bm_p, subdivisions=3, radius=0.160)
                for v in bm_p.verts:
                    v.co.x *= 1.15
                    v.co.y *= 0.62
                    v.co.z *= 0.88
                rot_m = mathutils.Matrix.Rotation(a + math.pi * 0.5, 4, 'Z') @ mathutils.Matrix.Rotation(math.radians(16.0), 4, 'X')
                for v in bm_p.verts:
                    co_r = rot_m @ v.co
                    v.co = (px * MM + co_r.x, py * MM + co_r.y, z_1f + 0.525 + co_r.z)
                for f in bm_p.faces:
                    f.smooth = True
                bmesh.ops.recalc_face_normals(bm_p, faces=bm_p.faces[:])
                mp = bpy.data.meshes.new(f"1F_Living_Sofa_{s_tag}_Pillow_{p_i}")
                bm_p.to_mesh(mp)
                bm_p.free()
                op = bpy.data.objects.new(f"1F_Living_Sofa_{s_tag}_Pillow_{p_i}", mp)
                op.data.materials.append(MATS["Sofa_White_Boucle"])
                link_obj(op, col_1f)

        # 3. Sculptural Botanical Golden-Leaf & 9-Petal Porcelain Magnolia Cascade Chandelier (mounted flush to z=2.570 flat central disc)
        add_cyl_mm("1F_Living_Sofa_Chandelier_Canopy", scx_mm, scy_mm, 45.0, z_1f + 2.555, z_1f + 2.572, MATS["Chandelier_Antique_Gold"], col_1f, segs=32)

        rng_ch = random.Random(20261123)
        bm_br = bmesh.new()
        bm_lf = bmesh.new()
        bm_bl = bmesh.new()
        bm_lt = bmesh.new()

        def eval_cubic_bezier(pts, t):
            u = 1.0 - t
            return (
                (u * u * u) * pts[0]
                + (3.0 * u * u * t) * pts[1]
                + (3.0 * u * t * t) * pts[2]
                + (t * t * t) * pts[3]
            )

        def add_spline_branch(ctrl_pts, r0, r1, n_steps=6, segs=5):
            vecs = [mathutils.Vector(p) for p in ctrl_pts]
            if len(vecs) == 3:
                vecs = [vecs[0], vecs[0].lerp(vecs[1], 0.66), vecs[1].lerp(vecs[2], 0.34), vecs[2]]
            pts = [eval_cubic_bezier(vecs, i / float(n_steps)) for i in range(n_steps + 1)]
            rings_t = []
            for idx, pt in enumerate(pts):
                if idx == 0:
                    tang = pts[1] - pt
                elif idx == len(pts) - 1:
                    tang = pt - pts[-2]
                else:
                    tang = pts[idx + 1] - pts[idx - 1]
                tv = tang.normalized() if tang.length > 1e-6 else mathutils.Vector((0.0, 0.0, -1.0))
                ref = mathutils.Vector((0.0, 1.0, 0.0)) if abs(tv.y) < 0.85 else mathutils.Vector((1.0, 0.0, 0.0))
                u_ax = tv.cross(ref).normalized()
                v_ax = tv.cross(u_ax).normalized()
                rad = r0 + (r1 - r0) * (idx / float(n_steps))
                ring = []
                for s in range(segs):
                    ang_s = 2.0 * math.pi * s / float(segs)
                    off = (u_ax * math.cos(ang_s) + v_ax * math.sin(ang_s)) * rad
                    ring.append(bm_br.verts.new(pt + off))
                rings_t.append(ring)
            for idx in range(len(rings_t) - 1):
                ra, rb = rings_t[idx], rings_t[idx + 1]
                for s in range(segs):
                    sn = (s + 1) % segs
                    bm_br.faces.new([ra[s], ra[sn], rb[sn], rb[s]]).smooth = True
            bm_br.faces.new(rings_t[-1]).smooth = True
            return pts

        def add_sculpted_leaf(pos, yaw, pitch, roll, length=0.068, width=0.028):
            rot = (
                mathutils.Matrix.Rotation(yaw, 4, 'Z')
                @ mathutils.Matrix.Rotation(pitch, 4, 'X')
                @ mathutils.Matrix.Rotation(roll, 4, 'Y')
            )
            pts_loc = [
                mathutils.Vector((0.0, 0.0, 0.0)),
                mathutils.Vector((-0.36 * width, 0.28 * length, 0.05 * length)),
                mathutils.Vector((0.0,           0.30 * length, -0.024 * length)),
                mathutils.Vector((0.36 * width,  0.28 * length, 0.05 * length)),
                mathutils.Vector((-0.48 * width, 0.64 * length, 0.07 * length)),
                mathutils.Vector((0.0,           0.66 * length, -0.020 * length)),
                mathutils.Vector((0.48 * width,  0.64 * length, 0.07 * length)),
                mathutils.Vector((0.0,           1.00 * length, -0.09 * length)),
            ]
            p0 = mathutils.Vector(pos)
            v = [bm_lf.verts.new(p0 + (rot @ p)) for p in pts_loc]
            for fverts in (
                [v[0], v[1], v[2]],
                [v[0], v[2], v[3]],
                [v[1], v[4], v[5], v[2]],
                [v[2], v[5], v[6], v[3]],
                [v[4], v[7], v[5]],
                [v[5], v[7], v[6]],
            ):
                bm_lf.faces.new(fverts).smooth = True

        def add_leaf_spray(pos, base_yaw, base_pitch, n_leaves=3, scale=1.0):
            for li in range(n_leaves):
                fan = (li - 0.5 * (n_leaves - 1)) * 0.55
                add_sculpted_leaf(
                    pos,
                    base_yaw + fan + rng_ch.uniform(-0.18, 0.18),
                    base_pitch + rng_ch.uniform(-0.22, 0.18),
                    rng_ch.uniform(-0.55, 0.55),
                    length=scale * rng_ch.uniform(0.054, 0.084),
                    width=scale * rng_ch.uniform(0.023, 0.035),
                )

        def add_magnolia_blossom(pos, yaw, tilt, scale=1.0):
            # 2-whorl sculpted porcelain magnolia: 3 inner cupped petals + 6 outer flaring petals + calyx + warm core bulb
            p0 = mathutils.Vector(pos)
            ax_rot = mathutils.Matrix.Rotation(yaw + math.pi * 0.5, 4, 'Z') @ mathutils.Matrix.Rotation(tilt, 4, 'X')

            # Small antique-gold 5-sepal calyx cradling flower base
            for ks in range(5):
                sa_rot = ax_rot @ mathutils.Matrix.Rotation(2.0 * math.pi * ks / 5.0, 4, 'Z') @ mathutils.Matrix.Rotation(math.radians(-62.0), 4, 'X')
                s_pts = [
                    mathutils.Vector((0.0, 0.0, 0.0)),
                    mathutils.Vector((-0.008 * scale, 0.016 * scale, 0.002 * scale)),
                    mathutils.Vector((0.0, 0.026 * scale, -0.002 * scale)),
                    mathutils.Vector((0.008 * scale, 0.016 * scale, 0.002 * scale)),
                ]
                bm_br.faces.new([bm_br.verts.new(p0 + (sa_rot @ sp)) for sp in s_pts]).smooth = True

            # 2 whorls of cupped spoon petals
            whorls = [
                # (n_pet, phase, flare_deg, len_s, wid_s)
                (3, 0.0,            26.0, 0.068 * scale, 0.024 * scale),
                (6, math.pi / 6.0,  52.0, 0.082 * scale, 0.027 * scale),
            ]
            for n_pet, phase, flare_deg, plen, pwid in whorls:
                for kp in range(n_pet):
                    p_ang = phase + 2.0 * math.pi * kp / float(n_pet) + rng_ch.uniform(-0.08, 0.08)
                    prot = ax_rot @ mathutils.Matrix.Rotation(p_ang, 4, 'Z') @ mathutils.Matrix.Rotation(math.radians(90.0 - flare_deg), 4, 'X')
                    # Local +Y is length, +Z cups inward toward flower axis
                    p_pts = [
                        mathutils.Vector((0.0,            0.0,          0.0)),
                        mathutils.Vector((-0.34 * pwid,   0.30 * plen,  0.007 * scale)),
                        mathutils.Vector((0.0,            0.28 * plen, -0.003 * scale)),
                        mathutils.Vector((0.34 * pwid,    0.30 * plen,  0.007 * scale)),
                        mathutils.Vector((-0.44 * pwid,   0.68 * plen,  0.014 * scale)),
                        mathutils.Vector((0.0,            0.66 * plen,  0.003 * scale)),
                        mathutils.Vector((0.44 * pwid,    0.68 * plen,  0.014 * scale)),
                        mathutils.Vector((0.0,            1.00 * plen,  0.005 * scale)),
                    ]
                    pv = [bm_bl.verts.new(p0 + (prot @ pp)) for pp in p_pts]
                    for fverts in (
                        [pv[0], pv[1], pv[2]],
                        [pv[0], pv[2], pv[3]],
                        [pv[1], pv[4], pv[5], pv[2]],
                        [pv[2], pv[5], pv[6], pv[3]],
                        [pv[4], pv[7], pv[5]],
                        [pv[5], pv[7], pv[6]],
                    ):
                        bm_bl.faces.new(fverts).smooth = True

            # Warm glowing stamen core bulb inside cup
            bulb_center = p0 + (ax_rot @ mathutils.Vector((0.0, 0.0, 0.028 * scale)))
            tmp_l = bmesh.new()
            bmesh.ops.create_icosphere(tmp_l, subdivisions=1, radius=0.018 * scale)
            vmap = {v: bm_lt.verts.new(bulb_center + v.co) for v in tmp_l.verts}
            for fc in tmp_l.faces:
                bm_lt.faces.new([vmap[v] for v in fc.verts]).smooth = True
            tmp_l.free()

        # 1) Three intertwining central climbing vines from canopy down to pointed tail (z: 2.565 -> 1.255)
        for vi in range(3):
            v_ang0 = 2.0 * math.pi * vi / 3.0
            v_pts = [
                (scx_m + 0.010 * math.cos(v_ang0),        scy_m + 0.010 * math.sin(v_ang0),        z_1f + 2.565),
                (scx_m + 0.032 * math.cos(v_ang0 + 1.4),  scy_m + 0.032 * math.sin(v_ang0 + 1.4),  z_1f + 2.220),
                (scx_m + 0.028 * math.cos(v_ang0 + 2.8),  scy_m + 0.028 * math.sin(v_ang0 + 2.8),  z_1f + 1.760),
                (scx_m + 0.005 * math.cos(v_ang0 + 4.1),  scy_m + 0.005 * math.sin(v_ang0 + 4.1),  z_1f + 1.255),
            ]
            spine_pts = add_spline_branch(v_pts, r0=0.0045, r1=0.0018, n_steps=10, segs=6)
            for si, sp in enumerate(spine_pts[1:-1], 1):
                t_s = si / float(len(spine_pts) - 1)
                s_sc = 0.65 if (t_s < 0.16 or t_s > 0.84) else 0.92
                add_leaf_spray(
                    sp,
                    v_ang0 + si * 0.95,
                    math.radians(-26.0 - 20.0 * t_s),
                    n_leaves=3 if 0.18 < t_s < 0.86 else 2,
                    scale=s_sc,
                )

        # 2) 34 arched botanical branches + secondary twigs in inverted-teardrop cascade (z: 2.52 -> 1.24)
        tiers = [
            # (z_stem, rad_m, z_tip, n_branches, sub_twigs, leaf_scale, blossom_slots)
            (2.52, 0.085, 2.40, 3, False, 0.68, ()),
            (2.47, 0.210, 2.31, 4, False, 0.84, (0, 2)),
            (2.33, 0.315, 2.16, 5, True,  0.96, (1, 3)),
            (2.16, 0.385, 1.98, 6, True,  1.05, (0, 2, 4)),
            (1.98, 0.400, 1.79, 6, True,  1.02, (1, 3, 5)),
            (1.79, 0.275, 1.60, 5, True,  0.90, (0, 2, 4)),
            (1.60, 0.155, 1.41, 3, False, 0.78, ()),
            (1.42, 0.060, 1.24, 2, False, 0.64, ()),
        ]
        # Force prominent +Y front orientation bias (around +90 deg) for select blooms so they face the camera richly
        for t_idx, (z_st, rad_m, z_tip, n_br, do_sub, lf_sc, bl_slots) in enumerate(tiers):
            for bi in range(n_br):
                ang = (2.0 * math.pi * bi / float(n_br)) + t_idx * 0.68 + rng_ch.uniform(-0.14, 0.14)
                ca, sa = math.cos(ang), math.sin(ang)
                tang_x, tang_y = -sa, ca
                swirl = (1.0 if (bi % 2 == 0) else -1.0) * 0.045 * rad_m * 2.5
                p0 = (scx_m + 0.015 * ca, scy_m + 0.015 * sa, z_1f + z_st)
                p1 = (
                    scx_m + rad_m * 0.38 * ca + tang_x * swirl,
                    scy_m + rad_m * 0.38 * sa + tang_y * swirl,
                    z_1f + z_st + 0.035 - 0.04 * (t_idx > 4),
                )
                p2 = (
                    scx_m + rad_m * 0.76 * ca - tang_x * swirl * 0.5,
                    scy_m + rad_m * 0.76 * sa - tang_y * swirl * 0.5,
                    z_1f + 0.38 * z_st + 0.62 * z_tip + 0.015,
                )
                p3 = (scx_m + rad_m * ca, scy_m + rad_m * sa, z_1f + z_tip)
                b_pts = add_spline_branch([p0, p1, p2, p3], r0=0.0042, r1=0.0016, n_steps=6, segs=5)

                # Leaf clusters along main branch & tip
                add_leaf_spray(b_pts[2], ang - 0.55, math.radians(-16.0), n_leaves=3, scale=lf_sc * 0.92)
                add_leaf_spray(b_pts[4], ang + 0.45, math.radians(-24.0), n_leaves=3, scale=lf_sc * 0.96)
                if bi in bl_slots:
                    # Tilt outward ~38-58 deg so wide magnolia petals & core face viewer cleanly
                    tilt_deg = 36.0 + t_idx * 4.5 + rng_ch.uniform(-5.0, 6.0)
                    add_magnolia_blossom(b_pts[-1], ang, math.radians(tilt_deg), scale=rng_ch.uniform(0.88, 1.12))
                    add_leaf_spray(b_pts[-2], ang, math.radians(-28.0), n_leaves=3, scale=lf_sc * 0.85)
                else:
                    add_leaf_spray(b_pts[-1], ang, math.radians(-32.0), n_leaves=4, scale=lf_sc)

                # Secondary forked offshoot twig on main crown/belly branches for dense botanical volume
                if do_sub:
                    sub_ang = ang + (0.58 if bi % 2 == 0 else -0.58)
                    sca, ssa = math.cos(sub_ang), math.sin(sub_ang)
                    sp0 = b_pts[2]
                    sp_tip = mathutils.Vector((
                        sp0.x + 0.135 * lf_sc * sca,
                        sp0.y + 0.135 * lf_sc * ssa,
                        sp0.z - rng_ch.uniform(0.08, 0.14),
                    ))
                    sp1 = sp0.lerp(sp_tip, 0.45) + mathutils.Vector((0.0, 0.0, 0.025))
                    sp2 = sp0.lerp(sp_tip, 0.80)
                    s_pts = add_spline_branch([sp0, sp1, sp2, sp_tip], r0=0.0028, r1=0.0012, n_steps=4, segs=4)
                    add_leaf_spray(s_pts[2], sub_ang + 0.4, math.radians(-24.0), n_leaves=3, scale=lf_sc * 0.88)
                    add_leaf_spray(s_pts[-1], sub_ang, math.radians(-36.0), n_leaves=3, scale=lf_sc * 0.92)

        print(
            f"[CHANDELIER] branches={len(bm_br.verts)}v leaves={len(bm_lf.verts)}v "
            f"blossoms={len(bm_bl.verts)}v bulbs={len(bm_lt.verts)}v "
            f"total={len(bm_br.verts)+len(bm_lf.verts)+len(bm_bl.verts)+len(bm_lt.verts)}v"
        )

        for bm_part, m_name, mat_part in [
            (bm_br, "1F_Living_Sofa_Chandelier_Branches", MATS["Chandelier_Antique_Gold"]),
            (bm_lf, "1F_Living_Sofa_Chandelier_Leaves",   MATS["Chandelier_Antique_Gold"]),
            (bm_bl, "1F_Living_Sofa_Chandelier_Blossoms", MATS["Chandelier_Magnolia_Porcelain"]),
            (bm_lt, "1F_Living_Sofa_Chandelier_Bulbs",    MATS["Chandelier_Bulb_Glow"]),
        ]:
            bmesh.ops.recalc_face_normals(bm_part, faces=bm_part.faces[:])
            mesh_p = bpy.data.meshes.new(m_name)
            bm_part.to_mesh(mesh_p)
            bm_part.free()
            obj_p = bpy.data.objects.new(m_name, mesh_p)
            obj_p.data.materials.append(mat_part)
            if m_name in ("1F_Living_Sofa_Chandelier_Blossoms", "1F_Living_Sofa_Chandelier_Bulbs"):
                obj_p.visible_shadow = False
            link_obj(obj_p, col_1f)

        ch_ldata = bpy.data.lights.new(name="1F_Living_Chandelier_PointLight", type='POINT')
        ch_ldata.energy = 28.0
        ch_ldata.color = (1.0, 0.90, 0.72)
        ch_ldata.shadow_soft_size = 0.35
        ch_lobj = bpy.data.objects.new("1F_Living_Chandelier_PointLight", ch_ldata)
        ch_lobj.location = (scx_m, scy_m, z_1f + 1.98)
        link_obj(ch_lobj, col_1f)

    build_1f_living_ring_sofa_and_tree()

    # - 1F Kaspar Foyer Partition Screen (卡斯帕的玄关, 420 x 1807mm: x: 4695..6502, y: -2170..-1750, next to Ventilation Shaft Window)
    #   Matches reference photo (media_1793051800333_90002acd.jpg):
    #   * Outer Inverted-U Portal Frame reaching ceiling (East leg x: 6290..6502, West leg x: 4695..4907, Top header z: 2.68..2.94m)
    #   * Two Floating Stepped Vertical Wings suspended at z: 0.52..2.62m (leaving bottom z: 0..0.52m and center vertical slot x: 5435..5762 OPEN!)
    #   * Two nested C-shaped stepped relief borders on each wing
    #   * Central Square Book-Matched Pandora/Green-Black Luxury Stone Plaque (x: 5210..5987, z: 1.18..2.04m)
    k_mat = MATS["Kaspar_Pure_White"]
    # 1) Outer Inverted-U Portal Frame
    add_box_mm("1F_Kaspar_Frame_LegE",   6290, 6502, -2170, -1750, zf_1f, z_1f + 2.94, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Frame_LegW",   4695, 4907, -2170, -1750, zf_1f, z_1f + 2.94, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Frame_Header", 4695, 6502, -2170, -1750, z_1f + 2.68, z_1f + 2.94, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Frame_SubTop", 4907, 6290, -2130, -1790, z_1f + 2.56, z_1f + 2.68, k_mat, col_1f)
    # 2) Two Floating Stepped Vertical Wings (suspended at z: 0.52..2.62m; center gap x: 5435..5762 is open!)
    add_box_mm("1F_Kaspar_Wing_E", 5762, 6295, -2135, -1785, z_1f + 0.52, z_1f + 2.62, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Wing_W", 4902, 5435, -2135, -1785, z_1f + 0.52, z_1f + 2.62, k_mat, col_1f)
    # 3) Nested C-shaped Stepped Relief Borders on East Wing (x: 5762..6155) & West Wing (x: 5042..5435)
    #    Outer relief step (z: 0.98..2.24m)
    add_box_mm("1F_Kaspar_Relief1_E_Top", 5762, 6160, -2152, -1768, z_1f + 2.13, z_1f + 2.24, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Relief1_E_Bot", 5762, 6160, -2152, -1768, z_1f + 0.98, z_1f + 1.09, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Relief1_E_V",   6055, 6160, -2152, -1768, z_1f + 1.09, z_1f + 2.13, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Relief1_W_Top", 5037, 5435, -2152, -1768, z_1f + 2.13, z_1f + 2.24, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Relief1_W_Bot", 5037, 5435, -2152, -1768, z_1f + 0.98, z_1f + 1.09, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Relief1_W_V",   5037, 5142, -2152, -1768, z_1f + 1.09, z_1f + 2.13, k_mat, col_1f)
    #    Inner relief step (z: 1.09..2.13m)
    add_box_mm("1F_Kaspar_Relief2_E_Top", 5762, 6055, -2165, -1755, z_1f + 2.04, z_1f + 2.13, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Relief2_E_Bot", 5762, 6055, -2165, -1755, z_1f + 1.09, z_1f + 1.18, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Relief2_E_V",   5987, 6055, -2165, -1755, z_1f + 1.18, z_1f + 2.04, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Relief2_W_Top", 5142, 5435, -2165, -1755, z_1f + 2.04, z_1f + 2.13, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Relief2_W_Bot", 5142, 5435, -2165, -1755, z_1f + 1.09, z_1f + 1.18, k_mat, col_1f)
    add_box_mm("1F_Kaspar_Relief2_W_V",   5142, 5210, -2165, -1755, z_1f + 1.18, z_1f + 2.04, k_mat, col_1f)
    # 4) Central Square Book-Matched Luxury Stone Plaque (x: 5210..5987, z: 1.18..2.04m)
    add_box_mm("1F_Kaspar_Stone_Frame", 5204, 5993, -2176, -1744, z_1f + 1.174, z_1f + 2.046, MATS["Stair_Bronze_Iron"], col_1f)
    add_uv_front_box_mm(
        "1F_Kaspar_Center_Stone",
        5210, 5987, -2182, -1738, z_1f + 1.18, z_1f + 2.04,
        0.0, 1.0, 0.0, 1.0,
        MATS["Kaspar_Center_Stone"], col_1f
    )
    # add_box_mm("1F_Kaspar_Stone_MidSeam", 5596, 5601, -2184, -1736, z_1f + 1.18, z_1f + 2.04, MATS["Stair_Bronze_Iron"], col_1f) # single half-slab (rev. 2026-11-03)
    # - 1F Living Room TV Cabinet (rev. 2026-10-28): 11 panels across x 1350..6470
    #   Col 1 full-height door | 8 fold doors over the hearth (1830..5527.8) | 2 full-height right columns (5527.8..5990, 5990..6470)
    #   All doors share ONE continuous ocean-mural image (tex_tv_ocean_mural.jpg) mapped over x 1350..6468, z 0..2.45m
    #   (generated from tvcab_spec.py; numbers are mm except z in m)
    add_box_mm("1F_Living_TVCab_Back_L", 1350.0, 1830.0, 1505, 1524, zf_1f, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Back_R2", 5527.8, 5990.0, 1505, 1524, zf_1f, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Back_R", 5990.0, 6470.0, 1505, 1524, zf_1f, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Back_Mid", 1830.0, 5527.8, 1505, 1524, z_1f + 0.500, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Back_Gray", 1830.0, 5527.8, 1510, 1524, z_1f + 0.180, z_1f + 0.500, MATS["Wall_Struct"], col_1f)
    add_box_mm("1F_Living_TVCab_V0", 1350.0, 1372.0, 1165, 1508, zf_1f, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_V1", 1818.0, 1840.0, 1165, 1508, zf_1f, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_V2", 2771.0, 2793.0, 1165, 1508, z_1f + 0.500, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_V3", 4564.8, 4586.8, 1165, 1508, z_1f + 0.500, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_V4b", 5516.8, 5538.8, 1165, 1508, zf_1f, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_V4", 5980.0, 6002.0, 1165, 1508, zf_1f, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_V5", 6448.0, 6470.0, 1165, 1508, zf_1f, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Plinth_L", 1350.0, 1840.0, 1168, 1508, zf_1f, z_1f + 0.040, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Plinth_R2", 5516.8, 5980.0, 1168, 1508, zf_1f, z_1f + 0.040, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Plinth_R", 5980.0, 6470.0, 1168, 1508, zf_1f, z_1f + 0.040, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C1_0", 1372.0, 1818.0, 1165, 1508, z_1f + 0.040, z_1f + 0.062, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C6_0", 5538.8, 5980.0, 1165, 1508, z_1f + 0.040, z_1f + 0.062, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C5_0", 6002.0, 6448.0, 1165, 1508, z_1f + 0.040, z_1f + 0.062, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C1_1", 1372.0, 1818.0, 1165, 1508, z_1f + 0.500, z_1f + 0.522, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C6_1", 5538.8, 5980.0, 1165, 1508, z_1f + 0.500, z_1f + 0.522, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C5_1", 6002.0, 6448.0, 1165, 1508, z_1f + 0.500, z_1f + 0.522, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C2_1", 1840.0, 2771.0, 1165, 1508, z_1f + 0.500, z_1f + 0.522, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C4_1", 4586.8, 5516.8, 1165, 1508, z_1f + 0.500, z_1f + 0.522, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C3_1", 2793.0, 4564.8, 1165, 1508, z_1f + 0.500, z_1f + 0.522, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C1_2", 1372.0, 1818.0, 1165, 1508, z_1f + 0.890, z_1f + 0.912, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C6_2", 5538.8, 5980.0, 1165, 1508, z_1f + 0.890, z_1f + 0.912, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C5_2", 6002.0, 6448.0, 1165, 1508, z_1f + 0.890, z_1f + 0.912, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C2_2", 1840.0, 2771.0, 1165, 1508, z_1f + 0.890, z_1f + 0.912, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C4_2", 4586.8, 5516.8, 1165, 1508, z_1f + 0.890, z_1f + 0.912, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C1_3", 1372.0, 1818.0, 1165, 1508, z_1f + 1.280, z_1f + 1.302, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C6_3", 5538.8, 5980.0, 1165, 1508, z_1f + 1.280, z_1f + 1.302, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C5_3", 6002.0, 6448.0, 1165, 1508, z_1f + 1.280, z_1f + 1.302, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C2_3", 1840.0, 2771.0, 1165, 1508, z_1f + 1.280, z_1f + 1.302, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C4_3", 4586.8, 5516.8, 1165, 1508, z_1f + 1.280, z_1f + 1.302, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C1_4", 1372.0, 1818.0, 1165, 1508, z_1f + 1.670, z_1f + 1.692, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C6_4", 5538.8, 5980.0, 1165, 1508, z_1f + 1.670, z_1f + 1.692, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C5_4", 6002.0, 6448.0, 1165, 1508, z_1f + 1.670, z_1f + 1.692, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C2_4", 1840.0, 2771.0, 1165, 1508, z_1f + 1.670, z_1f + 1.692, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C4_4", 4586.8, 5516.8, 1165, 1508, z_1f + 1.670, z_1f + 1.692, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C3_4", 2793.0, 4564.8, 1165, 1508, z_1f + 1.670, z_1f + 1.692, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C1_5", 1372.0, 1818.0, 1165, 1508, z_1f + 2.060, z_1f + 2.082, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C6_5", 5538.8, 5980.0, 1165, 1508, z_1f + 2.060, z_1f + 2.082, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C5_5", 6002.0, 6448.0, 1165, 1508, z_1f + 2.060, z_1f + 2.082, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C2_5", 1840.0, 2771.0, 1165, 1508, z_1f + 2.060, z_1f + 2.082, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C4_5", 4586.8, 5516.8, 1165, 1508, z_1f + 2.060, z_1f + 2.082, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C3_5", 2793.0, 4564.8, 1165, 1508, z_1f + 2.060, z_1f + 2.082, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C1_6", 1372.0, 1818.0, 1165, 1508, z_1f + 2.428, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C6_6", 5538.8, 5980.0, 1165, 1508, z_1f + 2.428, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C5_6", 6002.0, 6448.0, 1165, 1508, z_1f + 2.428, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C2_6", 1840.0, 2771.0, 1165, 1508, z_1f + 2.428, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C4_6", 4586.8, 5516.8, 1165, 1508, z_1f + 2.428, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Sh_C3_6", 2793.0, 4564.8, 1165, 1508, z_1f + 2.428, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_C3_MidDiv", 3667.9, 3689.9, 1165, 1508, z_1f + 1.692, z_1f + 2.060, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_C3_TopDiv1", 3371.9, 3393.9, 1165, 1508, z_1f + 2.082, z_1f + 2.428, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_C3_TopDiv2", 3963.9, 3985.9, 1165, 1508, z_1f + 2.082, z_1f + 2.428, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Trough_Bot", 1840.0, 5516.8, 1125, 1510, zf_1f, z_1f + 0.030, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Trough_FrontL", 1840.0, 3676.9, 1168, 1190, z_1f + 0.030, z_1f + 0.190, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Trough_FrontR", 3680.9, 5516.8, 1168, 1190, z_1f + 0.030, z_1f + 0.190, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Trough_Back", 1840.0, 5516.8, 1488, 1510, z_1f + 0.030, z_1f + 0.190, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Trough_Div_0", 1830.0, 1850.0, 1147, 1488, z_1f + 0.030, z_1f + 0.188, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Trough_Div_1", 2442.8, 2462.8, 1147, 1488, z_1f + 0.030, z_1f + 0.188, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Trough_Div_2", 3055.6, 3075.6, 1147, 1488, z_1f + 0.030, z_1f + 0.188, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Trough_Div_3", 3668.4, 3688.4, 1147, 1488, z_1f + 0.030, z_1f + 0.188, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Trough_Div_4", 4281.2, 4301.2, 1147, 1488, z_1f + 0.030, z_1f + 0.188, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Trough_Div_5", 4894.0, 4914.0, 1147, 1488, z_1f + 0.030, z_1f + 0.188, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_Trough_Div_6", 5506.8, 5526.8, 1147, 1488, z_1f + 0.030, z_1f + 0.188, MATS["OLO_Cab_White"], col_1f)
    # 1F Living Room TV Cabinet Doors & Wave Plinth (rev. 2026-11-04):
    # Panoramic Deep Ocean Mural mapped continuously across ALL doors from x 1350 to 6468 (total W=5118mm, H=2.45m)
    x_mural_start = 1350.0
    x_mural_end = 6468.0
    w_mural = x_mural_end - x_mural_start
    mural_mat = MATS["TV_Ocean_Mural"]

    # 1) Left Outer Bay (slightly longer full-height door, z: zf_1f..2.45m)
    u1_l = (1350.0 - x_mural_start) / w_mural
    u2_l = (1826.0 - x_mural_start) / w_mural
    add_uv_front_box_mm("1F_Living_TVCab_OuterDoor_L", 1350.0, 1826.0, 1138, 1160, zf_1f, z_1f + 2.450, u1_l, u2_l, 0.0, 1.0, mural_mat, col_1f)
    add_box_mm("1F_Living_TVCab_Handle_L", 1812.0, 1818.0, 1132, 1138, z_1f + 1.05, z_1f + 1.25, MATS["Gold_Brass"], col_1f)

    # 2) Center 8 Folding Doors with Deep Ocean Mural (x: 1830 .. 5527.8, z: 0.490 .. 2.45m)
    # Restores the crisp 240mm open horizontal niche (空档, z: 0.250 .. 0.490m) above the wave-shaped travertine plinth!
    x_fold_start = 1830.0
    x_fold_end = 5527.8
    w_fold = (x_fold_end - x_fold_start) / 8.0
    v1_fold = 0.490 / 2.450  # vertical alignment matching full-height doors
    for i in range(8):
        x1 = x_fold_start + i * w_fold + 2.0
        x2 = x_fold_start + (i + 1) * w_fold - 2.0
        u1 = (x1 - x_mural_start) / w_mural
        u2 = (x2 - x_mural_start) / w_mural
        add_uv_front_box_mm(f"1F_Living_TVCab_FoldDoor_{i+1}", x1, x2, 1138, 1160, z_1f + 0.490, z_1f + 2.450, u1, u2, v1_fold, 1.0, mural_mat, col_1f)
        if i < 7:
            sx = x_fold_start + (i + 1) * w_fold
            add_box_mm(f"1F_Living_TVCab_FoldSeam_{i+1}", sx - 2.0, sx + 2.0, 1142, 1162, z_1f + 0.490, z_1f + 2.450, MATS["OLO_ToeKick_Black"], col_1f)

    # 3) Right Outer Bay 1 (slightly longer full-height door, z: zf_1f..2.45m)
    u1_r1 = (5531.8 - x_mural_start) / w_mural
    u2_r1 = (5987.0 - x_mural_start) / w_mural
    add_uv_front_box_mm("1F_Living_TVCab_OuterDoor_R2", 5531.8, 5987.0, 1138, 1160, zf_1f, z_1f + 2.450, u1_r1, u2_r1, 0.0, 1.0, mural_mat, col_1f)
    add_box_mm("1F_Living_TVCab_Handle_R2", 5542.0, 5548.0, 1132, 1138, z_1f + 1.05, z_1f + 1.25, MATS["Gold_Brass"], col_1f)

    # 4) Right Outer Bay 2 (Single full-height shoe cabinet door, width 474mm, z: zf_1f..2.45m)
    # Perfectly symmetrical to Left Outer Bay (width 476mm) and Right Bay 1 (width 455mm), completely seamless with ZERO extra horizontal/vertical lines
    u1_s = (5994.0 - x_mural_start) / w_mural
    u2_s = (6468.0 - x_mural_start) / w_mural
    add_uv_front_box_mm("1F_Living_TVCab_ShoeDoor_R", 5994.0, 6468.0, 1138, 1160, zf_1f, z_1f + 2.450, u1_s, u2_s, 0.0, 1.0, mural_mat, col_1f)
    add_box_mm("1F_Living_TVCab_ShoeHandle_R", 6000.0, 6006.0, 1132, 1138, z_1f + 1.05, z_1f + 1.25, MATS["Gold_Brass"], col_1f)

    add_box_mm("1F_Living_TVCab_OuterEnd_R", 6470.0, 6502.0, 1138, 1508, zf_1f, z_1f + 2.450, MATS["OLO_Cab_White"], col_1f)

    # 5) Organic S-wave Warm Beige Travertine Hearth Plinth + Open Horizontal Niche Above (米黄色洞石波浪地台与上方开放空档, rev. 2026-11-05):
    # - Plinth height = 250mm (z_1f .. z_1f + 0.250), organic wave front edge (y = 1095 +- 22mm)
    # - Open Horizontal Niche (空档) from z = 0.250m to 0.490m (240mm high clear gap between wave plinth and 8 folding doors!)
    # - Recessed dark bronze/charcoal niche back & side liners with concealed warm LED cove strip
    pts_hearth = []
    n_pts = 48
    for k in range(n_pts + 1):
        t = k / float(n_pts)
        hx = 1830.0 + (5527.8 - 1830.0) * t
        y_wave = 1092.0 - 22.0 * math.sin(2.0 * math.pi * t)
        pts_hearth.append((hx, y_wave))
    pts_hearth.append((5527.8, 1495.0))
    pts_hearth.append((1830.0, 1495.0))
    add_prism("1F_Living_TVCab_TravertineHearth", pts_hearth, zf_1f, z_1f + 0.250, MATS["Travertine_Beige"], col_1f)
    # Recessed Open Niche Liner (z: 0.250 .. 0.490m) directly above the wave plinth (matching warm white interior in reference)
    add_box_mm("1F_Living_TVCab_NicheWarmBack",  1830.0, 5527.8, 1390, 1495, z_1f + 0.250, z_1f + 0.490, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_NicheCeilLiner", 1830.0, 5527.8, 1155, 1495, z_1f + 0.482, z_1f + 0.490, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_NicheSideL",     1826.0, 1842.0, 1155, 1495, z_1f + 0.250, z_1f + 0.490, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_NicheSideR",     5515.8, 5531.8, 1155, 1495, z_1f + 0.250, z_1f + 0.490, MATS["OLO_Cab_White"], col_1f)
    add_box_mm("1F_Living_TVCab_NicheLED",       1850.0, 5507.8, 1210, 1228, z_1f + 0.478, z_1f + 0.483, MATS["Warm_LED_Glow"], col_1f)
    tv_mat = MATS["Pure_White_Ceiling"]
    # Left Stepped Pilasters & Concave Curved Wall Transition next to Spiral Staircase (matching 447 + 309 + 373mm in WechatIMG6.pdf)
    add_box_mm("1F_Living_Pilaster_W1", 222,  669, 1210, 1525, zf_1f, z_1f + 2.570, tv_mat, col_1f)
    add_box_mm("1F_Living_Pilaster_W2", 669,  978, 1085, 1525, zf_1f, z_1f + 2.570, tv_mat, col_1f)
    pts_concave = []
    for k in range(25):
        t = k / 24.0
        ang = math.radians(180.0 + 90.0 * t)
        # Smooth concave curve from (x=978, y=1085) to (x=1350, y=1265)
        cx_mm = 1350.0 + 372.0 * math.cos(ang)
        cy_mm = 1085.0 - 180.0 * math.sin(ang)
        pts_concave.append((cx_mm, cy_mm))
    pts_concave.extend([(1350.0, 1525.0), (978.0, 1525.0)])
    add_prism("1F_Living_CurvedWall", pts_concave, zf_1f, z_1f + 2.45, tv_mat, col_1f)
    # Upper cabinet header recessed at y=1220..1525mm connecting top of cabinet (z=2.45m) to horizontal soffit (z=2.570m) in unified plaster material
    add_box_mm("1F_Living_CabinetHeader", 978, 6502, 1220.0, 1525, z_1f + 2.45, z_1f + 2.570, tv_mat, col_1f)
    # 1F living room sculptural rock beside the TV wall (rev. 2026-10-28, generated by f1_rock_spec.py)
    def _rock_loft(cx, cy, z0, z1, rx, ry, sway_x, sway_y, seed, rings=18, segs=24, kind="stone"):
        """returns (verts[(x_mm, y_mm, z_m)], quads/tris faces) for a closed organic loft"""
        V = []
        F = []
        for k in range(rings + 1):
            t = k / float(rings)
            z = z0 + (z1 - z0) * t
            if kind == "egg":
                s = math.sin(math.pi * t) ** 0.85
            else:
                s = (0.70 + 0.30 * math.sin(math.pi * min(1.0, t * 1.2)) ** 0.7) * max(0.0, 1.0 - t ** 5) ** 0.45
                s *= 1.0 + 0.10 * math.sin(7.0 * t + seed) + 0.05 * math.sin(13.0 * t + 2.0 * seed)
            ox = cx + sway_x * math.sin(math.pi * t * 1.3 + seed)
            oy = cy + sway_y * math.sin(math.pi * t * 0.9 + 0.5 * seed)
            for j in range(segs):
                a = 2.0 * math.pi * j / segs
                n = 1.0
                if kind != "egg":
                    n += 0.10 * math.sin(3.0 * a + 5.0 * t + seed) + 0.06 * math.sin(5.0 * a - 3.0 * t + 2.0 * seed)
                V.append((ox + rx * s * n * math.cos(a), oy + ry * s * n * math.sin(a), z))
        for k in range(rings):
            for j in range(segs):
                a0 = k * segs + j
                a1 = k * segs + (j + 1) % segs
                b0 = (k + 1) * segs + j
                b1 = (k + 1) * segs + (j + 1) % segs
                F.append((a0, a1, b1, b0))
        cb = len(V); V.append((cx + sway_x * math.sin(seed), cy + sway_y * math.sin(0.5 * seed), z0))
        ct = len(V); V.append((cx + sway_x * math.sin(math.pi * 1.3 + seed), cy + sway_y * math.sin(math.pi * 0.9 + 0.5 * seed), z1))
        for j in range(segs):
            F.append((cb, (j + 1) % segs, j))
            F.append((ct, rings * segs + j, rings * segs + (j + 1) % segs))
        return V, F
    def _add_rock_mesh(rname, V, F, mat):
        me = bpy.data.meshes.new(rname)
        me.from_pydata([(x * MM, y * MM, z) for (x, y, z) in V], [], F)
        me.update()
        for poly in me.polygons:
            poly.use_smooth = True
        ob = bpy.data.objects.new(rname, me)
        ob.data.materials.append(mat)
        link_obj(ob, col_1f)
        return ob
    # Rock sculpture shifted +220mm in Y snugly hugging the curved wall (rev. 2026-11-04)
    add_cyl_mm("1F_Living_RockArt_Pedestal", 1150.0, 1150.0, 165.0, z_1f + 0.0050, z_1f + 0.5550, MATS["Marble_Green_Pedestal"], col_1f, segs=40)
    _V, _F = _rock_loft(1105.0, 1160.0, z_1f + 0.5450, z_1f + 1.8050, 125.0, 88.0, 35.0, 14.0, 0.7, kind="stone")
    _add_rock_mesh("1F_Living_RockArt_StoneA", _V, _F, MATS["Travertine_Stone"])
    _V, _F = _rock_loft(1220.0, 1170.0, z_1f + 0.5450, z_1f + 1.4750, 100.0, 75.0, 30.0, 12.0, 2.3, kind="stone")
    _add_rock_mesh("1F_Living_RockArt_StoneB", _V, _F, MATS["Travertine_Stone"])
    _V, _F = _rock_loft(1165.0, 1115.0, z_1f + 0.5450, z_1f + 0.9550, 118.0, 72.0, 14.0, 8.0, 4.1, kind="stone")
    _add_rock_mesh("1F_Living_RockArt_StoneC", _V, _F, MATS["Travertine_Stone"])
    _V, _F = _rock_loft(1170.0, 1065.0, z_1f + 1.1950, z_1f + 1.3550, 55.0, 40.0, 0.0, 0.0, 0.0, kind="egg")
    _add_rock_mesh("1F_Living_RockArt_EggLight_1", _V, _F, MATS["Rock_Egg_Glow"])
    _V, _F = _rock_loft(1185.0, 1070.0, z_1f + 1.0150, z_1f + 1.1650, 52.0, 38.0, 0.0, 0.0, 0.0, kind="egg")
    _add_rock_mesh("1F_Living_RockArt_EggLight_2", _V, _F, MATS["Rock_Egg_Glow"])
    # - 1F Living Room Sculpted Organic Wave Ceiling & Flying Birds Art Installation (1F_Living_Ceiling_*)
    #   Per user requirements:
    #   1) "这里波浪延伸过去": Wave ceiling extends completely over the right side (x: 2220..6502mm),
    #      covering the area above the right TV cabinet doors and reaching the East wall/window!
    #   2) "天花板上的波浪形是面对电视柜延伸到右手边。是不延伸到面对电视柜背后的空间，只延伸到玄关处":
    #      In Y: waves span y = -1750 .. 1100mm (strictly living room zone in front of TV cabinet).
    #      Behind y = -1750mm: flat ceiling over crossing, and Kaspar ring cove over foyer.
    #   3) "一楼电视机柜上的波浪天花板上挂上这些图片上的飞鸟":
    #      Flock of sculpted translucent frosted white flying birds soaring beneath the wave ceiling!
    ceil_mat = MATS["Pure_White_Ceiling"]

    # 1. Unified Monolithic Plaster Ceiling (ALL parts share 100% the same physical gypsum material `ceil_mat`):
    # - Corridor flat ceiling (x: -1480..978mm, seamlessly continuing into WaveShell at x=978mm)
    add_box_mm("1F_Living_Ceiling_FlatW",    -1480,  978, -5520, 1525, z_1f + 2.570, z_1f + 3.12, ceil_mat, col_1f)
    # - North flat soffit over curved wall & left columns C1..C2 (x: 978..2500mm, y: 880..1525mm, z: 2.570..3.12m)
    add_box_mm("1F_Living_Ceiling_FlatN_W",    978, 2500,   880, 1525, z_1f + 2.570, z_1f + 3.12, ceil_mat, col_1f)
    # - East upper wall border at z = 2.742m..3.12m
    add_box_mm("1F_Living_Ceiling_BorderE",   6470, 6502, -5520, 1220, z_1f + 2.742, z_1f + 3.12, ceil_mat, col_1f)
    # - South ceiling border behind living room with ENLARGED OUTWARD-CONVEX pure-white circular ring (NO gold ribs!)
    def build_border_s_with_recess():
        bx0, bx1 = 978.0, 4695.0
        by0, by1 = -5520.0, -1750.0
        rcx, rcy = 2723.5, -2750.0
        angs = [-math.pi + (2.0 * math.pi * k) / 128.0 for k in range(128)]
        for cpx, cpy in ((bx1, by1), (bx0, by1), (bx0, by0), (bx1, by0)):
            angs.append(math.atan2(cpy - rcy, cpx - rcx))
        angs.sort()
        u_angs = []
        for th in angs:
            if not u_angs or abs(th - u_angs[-1]) > 1e-4:
                u_angs.append(th)

        # Flat central disc (r <= 688mm) + inner shadow groove (688..700) + outer LED groove (940..954)
        add_cyl_mm("1F_Living_Ceiling_ChandelierRecessCap", rcx, rcy, 688.0, z_1f + 2.570, z_1f + 3.120, ceil_mat, col_1f, segs=128)
        c_prof = [
            ("rect", 3.120, False),
            (688.0,  3.120, False),
            (688.0,  2.579, False),
            (700.0,  2.579, False),
            (700.0,  2.570, False),
            (940.0,  2.570, False),
            (940.0,  2.579, False),
            (954.0,  2.579, False),
            (954.0,  2.570, False),
            ("rect", 2.570, False),
        ]
        bm_bs = bmesh.new()
        rings_bs = []
        for th in u_angs:
            ct, st = math.cos(th), math.sin(th)
            tx = (bx1 - rcx) / ct if ct > 1e-8 else ((bx0 - rcx) / ct if ct < -1e-8 else 1e9)
            ty = (by1 - rcy) / st if st > 1e-8 else ((by0 - rcy) / st if st < -1e-8 else 1e9)
            t_rect = min(tx, ty)
            ring = []
            for r_spec, zz_rel, _ in c_prof:
                rr = t_rect if r_spec == "rect" else r_spec
                ring.append(bm_bs.verts.new(((rcx + rr * ct) * MM, (rcy + rr * st) * MM, z_1f + zz_rel)))
            rings_bs.append(ring)
        n_th = len(rings_bs)
        n_pr = len(c_prof)
        for k in range(n_th):
            kn = (k + 1) % n_th
            r0, r1 = rings_bs[k], rings_bs[kn]
            for pi in range(n_pr):
                pin = (pi + 1) % n_pr
                fc = bm_bs.faces.new([r0[pi], r1[pi], r1[pin], r0[pin]])
                fc.smooth = False
        bmesh.ops.recalc_face_normals(bm_bs, faces=bm_bs.faces[:])
        m_bs = bpy.data.meshes.new("1F_Living_Ceiling_BorderS")
        bm_bs.to_mesh(m_bs)
        bm_bs.free()
        o_bs = bpy.data.objects.new("1F_Living_Ceiling_BorderS", m_bs)
        o_bs.data.materials.append(ceil_mat)
        link_obj(o_bs, col_1f)

        # Enlarged OUTWARD-CONVEX (外凸) smooth circular ceiling ring: r_in=700mm, r_out=940mm (OD 1.88m), bulging down 10.5cm
        n_cseg = 128
        n_pconv = 24
        conv_pts = []
        for k in range(n_pconv + 1):
            t_c = k / float(n_pconv)
            rr_c = 700.0 + 240.0 * t_c
            zz_c = 2.570 - 0.105 * (math.sin(math.pi * t_c) ** 0.82)
            conv_pts.append((rr_c, zz_c))
        bm_cv = bmesh.new()
        cv_rings = []
        for k in range(n_cseg):
            ang_c = 2.0 * math.pi * k / float(n_cseg)
            ca, sa = math.cos(ang_c), math.sin(ang_c)
            cv_rings.append([bm_cv.verts.new(((rcx + rr * ca) * MM, (rcy + rr * sa) * MM, z_1f + zz)) for rr, zz in conv_pts])
        for k in range(n_cseg):
            kn = (k + 1) % n_cseg
            r0, r1 = cv_rings[k], cv_rings[kn]
            for pi in range(n_pconv):
                bm_cv.faces.new([r0[pi], r0[pi + 1], r1[pi + 1], r1[pi]]).smooth = True
            # Close upper seam at z=2.570 between r=940 and r=700 cleanly
            bm_cv.faces.new([r0[n_pconv], r0[0], r1[0], r1[n_pconv]]).smooth = False
        bmesh.ops.recalc_face_normals(bm_cv, faces=bm_cv.faces[:])
        m_cv = bpy.data.meshes.new("1F_Living_Ceiling_ConvexRing")
        bm_cv.to_mesh(m_cv)
        bm_cv.free()
        o_cv = bpy.data.objects.new("1F_Living_Ceiling_ConvexRing", m_cv)
        o_cv.data.materials.append(ceil_mat)
        link_obj(o_cv, col_1f)

        # Concealed warm halo LED tucked inside outer perimeter shadow groove (r=941..953mm, ZERO gold radial ribs!)
        bm_rl = bmesh.new()
        led_prof = [(941.0, 2.572), (953.0, 2.572), (953.0, 2.578), (941.0, 2.578)]
        l_rings = [[bm_rl.verts.new(((rcx + rr * math.cos(2*math.pi*k/128)) * MM, (rcy + rr * math.sin(2*math.pi*k/128)) * MM, z_1f + zz)) for rr, zz in led_prof] for k in range(128)]
        for k in range(128):
            kn = (k + 1) % 128
            for pi in range(4):
                pin = (pi + 1) % 4
                bm_rl.faces.new([l_rings[k][pi], l_rings[kn][pi], l_rings[kn][pin], l_rings[k][pin]]).smooth = True
        bmesh.ops.recalc_face_normals(bm_rl, faces=bm_rl.faces[:])
        m_rl = bpy.data.meshes.new("1F_Living_Ceiling_ChandelierRecessLED")
        bm_rl.to_mesh(m_rl)
        bm_rl.free()
        o_rl = bpy.data.objects.new("1F_Living_Ceiling_ChandelierRecessLED", m_rl)
        o_rl.data.materials.append(MATS["Warm_LED_Glow"])
        link_obj(o_rl, col_1f)

    build_border_s_with_recess()

    # 2. Continuous Monolithic Wave Ceiling & Bulkhead Fascia (x: 978..6502mm):
    #    - Flat left ceiling zone (x: 978..2500mm): z = 2.570m (smoothly tangent at x=2500mm)
    #    - Gentle C1 cosine curved transition (x: 2500..2980mm): rises smoothly from z=2.570m to z=2.805m
    #    - Crisp architectural boundary reveal line (x: 2980..3002mm, "波浪和平直天花板缓和界线处是有线条的"):
    #      recessed shadow seam at z=2.835m stepping cleanly into the first wave crest at x=3002mm (z=2.785m)
    #    - High-curvature harmonic cosine wave zone (x: 3002..6502mm): z = 2.686 + 0.099*cos(4*pi*t) with 2 deep downward wave valleys
    #      at x=3812mm (z=2.587m, over TV niche) & x=5432mm (z=2.587m, over right bookcase), and crests at x=3002, 4622, 6242mm (z=2.785m).
    def get_wave_ceiling_z(x_mm, y_mm=860.0):
        z_flat = 2.570
        z_cove_top = 2.805
        z_crest = 2.785
        z_valley = 2.587
        z_mid = 0.5 * (z_crest + z_valley)
        amp = 0.5 * (z_crest - z_valley)
        if x_mm <= 2500.0:
            z_base = z_flat
        elif x_mm <= 2980.0:
            u = (x_mm - 2500.0) / 480.0
            z_base = z_flat + (z_cove_top - z_flat) * 0.5 * (1.0 - math.cos(math.pi * u))
        elif x_mm <= 3002.0:
            # Crisp architectural seam line at the top of the gentle curved transition
            z_base = 2.835
        else:
            t = (x_mm - 3002.0) / 3240.0
            z_base = z_mid + amp * math.cos(4.0 * math.pi * t)
        return z_1f + z_base

    def build_wave_ceiling_and_fascia(col):
        # Fine continuous X sampling across flat zone (978..2500), gentle C1 curve (2500..2980), seam line (2980..3002), and wave (3002..6502)
        x_pts = []
        for i in range(24):
            x_pts.append(978.0 + (2500.0 - 978.0) * (i / 24.0))
        for i in range(56):
            x_pts.append(2500.0 + (2980.0 - 2500.0) * (i / 55.0))
        x_pts.extend([2980.5, 2991.0, 3001.5, 3002.0])
        for i in range(180):
            x_pts.append(3002.5 + (6502.0 - 3002.5) * (i / 179.0))

        # A. Unified Vertical Bulkhead Fascia & Soffit (x = 2500..6502mm, y = 880..1525mm)
        #    Tapers smoothly to zero height at x=2500mm (no left step seam) and follows the exact wave contour!
        x_f_pts = [xm for xm in x_pts if xm >= 2500.0]
        mesh_f = bpy.data.meshes.new("1F_Living_Ceiling_BulkheadFascia")
        bm_f = bmesh.new()
        y_f0 = 880.0 * MM
        y_f1 = 1525.0 * MM
        z_bot = z_1f + 2.570
        z_top_list = [max(z_bot + 0.001, get_wave_ceiling_z(xm, 880.0) - 0.005) for xm in x_f_pts]
        vf_front_bot = [bm_f.verts.new((xm * MM, y_f0, z_bot)) for xm in x_f_pts]
        vf_front_top = [bm_f.verts.new((xm * MM, y_f0, zt)) for xm, zt in zip(x_f_pts, z_top_list)]
        vf_back_bot  = [bm_f.verts.new((xm * MM, y_f1, z_bot)) for xm in x_f_pts]
        vf_back_top  = [bm_f.verts.new((xm * MM, y_f1, z_1f + 3.10)) for xm in x_f_pts]
        for i in range(len(x_f_pts) - 1):
            f_front = bm_f.faces.new([vf_front_bot[i], vf_front_bot[i+1], vf_front_top[i+1], vf_front_top[i]])
            f_front.smooth = True
            f_soffit = bm_f.faces.new([vf_back_bot[i], vf_front_bot[i], vf_front_bot[i+1], vf_back_bot[i+1]])
            f_soffit.smooth = False
            f_top = bm_f.faces.new([vf_front_top[i], vf_front_top[i+1], vf_back_top[i+1], vf_back_top[i]])
            f_top.smooth = False
            f_back = bm_f.faces.new([vf_back_bot[i], vf_back_top[i], vf_back_top[i+1], vf_back_bot[i+1]])
            f_back.smooth = False
        bm_f.faces.new([vf_front_bot[0], vf_front_top[0], vf_back_top[0], vf_back_bot[0]])
        bm_f.faces.new([vf_front_bot[-1], vf_back_bot[-1], vf_back_top[-1], vf_front_top[-1]])
        bmesh.ops.recalc_face_normals(bm_f, faces=bm_f.faces[:])
        bm_f.to_mesh(mesh_f)
        bm_f.free()
        obj_f = bpy.data.objects.new("1F_Living_Ceiling_BulkheadFascia", mesh_f)
        obj_f.data.materials.append(ceil_mat)
        link_obj(obj_f, col)

        # B. Continuous Monolithic Ceiling Shell (x = 978..6502mm, y = -1750..880mm)
        mesh_w = bpy.data.meshes.new("1F_Living_Ceiling_WaveShell")
        bm_w = bmesh.new()
        n_y = 24
        y_pts = [-1750.0 + (880.0 - (-1750.0)) * (j / float(n_y)) for j in range(n_y + 1)]
        z_top = z_1f + 3.12

        bot_grid = []
        for j, ym in enumerate(y_pts):
            row = [bm_w.verts.new((xm * MM, ym * MM, get_wave_ceiling_z(xm, ym))) for xm in x_pts]
            bot_grid.append(row)
        lip_front = [bm_w.verts.new((xm * MM, -1750.0 * MM, z_1f + 2.570)) for xm in x_pts]
        top_front = [bm_w.verts.new((xm * MM, y_pts[0] * MM, z_top)) for xm in x_pts]
        top_back  = [bm_w.verts.new((xm * MM, y_pts[-1] * MM, z_top)) for xm in x_pts]

        for j in range(n_y):
            for i in range(len(x_pts) - 1):
                f_b = bm_w.faces.new([bot_grid[j][i], bot_grid[j+1][i], bot_grid[j+1][i+1], bot_grid[j][i+1]])
                xm_mid = 0.5 * (x_pts[i] + x_pts[i+1])
                f_b.smooth = not (2980.0 <= xm_mid <= 3002.5)
        for i in range(len(x_pts) - 1):
            if x_pts[i+1] > 2500.0:
                f_lip_s = bm_w.faces.new([lip_front[i], bot_grid[0][i], bot_grid[0][i+1], lip_front[i+1]])
                f_lip_s.smooth = False
            bm_w.faces.new([top_front[i], top_front[i+1], top_back[i+1], top_back[i]])
            bm_w.faces.new([bot_grid[-1][i], top_back[i], top_back[i+1], bot_grid[-1][i+1]])

        bmesh.ops.recalc_face_normals(bm_w, faces=bm_w.faces[:])
        bm_w.to_mesh(mesh_w)
        bm_w.free()
        obj_w = bpy.data.objects.new("1F_Living_Ceiling_WaveShell", mesh_w)
        obj_w.data.materials.append(ceil_mat)
        link_obj(obj_w, col)
        return obj_w

    build_wave_ceiling_and_fascia(col_1f)

    # 5 Subtle recessed circular downlights matching reference render positions (2 on flat left ceiling, 3 on wave crests):
    for _dl_idx, (_dl_x, _dl_y) in enumerate([(1080.0, 200.0), (1480.0, 200.0), (3120.0, 200.0), (4622.0, 200.0), (6242.0, 200.0)], 1):
        _dl_z = get_wave_ceiling_z(_dl_x, _dl_y)
        add_cyl_mm(f"1F_Living_Ceiling_Downlight_{_dl_idx}_Trim", _dl_x, _dl_y, 26.0, _dl_z - 0.002, _dl_z + 0.008, MATS["Wall_Struct"], col_1f, segs=24)
        add_cyl_mm(f"1F_Living_Ceiling_Downlight_{_dl_idx}_Core", _dl_x, _dl_y, 16.0, _dl_z - 0.001, _dl_z + 0.010, MATS["Warm_LED_Glow"], col_1f, segs=24)

    # 1F Kaspar Foyer Dropped Flat Ceiling over Ventilation Shaft (South of y = -1750, x: 4695..6502, flush at z=2.570m; ring removed!)
    add_box_mm("1F_Kaspar_Ceiling_FlatPlate", 4695.0, 6502.0, -5520.0, -1750.0, z_1f + 2.570, z_1f + 2.94, ceil_mat, col_1f)

    # Sculptural Flying Birds Chandelier Art Installation (飞鸟艺术吊灯群, rev. 2026-11-06 v7):
    # - "飞鸟再大一些": Enlarged wingspan 330..420mm (average 370mm, substantial presence & glowing frosted wings)
    # - "一阵一阵的": 3 distinct migratory wave clusters (Wave 1 at West, Wave 2 at Center, Wave 3 at East/Window) with rhythmic breathing gaps
    # - "高度低一些": Lower soaring altitude z = 1.60..2.08m (overhead eye level, 60..120cm clearance to wave ceiling)
    # - "鸟儿要从右边往左飞": Strong Westward migration current (-X), heading strictly facing West
    # - "前后双吊线": Fore and aft vertical brass suspension wires rising to ceiling surface with brass rose caps
    def add_flying_bird(bname, cx_mm, cy_mm, cz_m, yaw_deg, pitch_deg, roll_deg, span_mm=370.0, flap_mode=0, col=col_1f):
        mesh_b = bpy.data.meshes.new(f"{bname}_Wings")
        bm_b = bmesh.new()
        n_s, n_c = 28, 8
        half_span = span_mm * 0.5
        thick_m = 0.0038

        def _wing_elevation_mm(abs_u, mode):
            if mode == 0:
                # Arched Bowed Glide (弓形展翅/弓背 - 用户要求：有的鸟儿翅膀要稍微弓起来弯着)
                # 显著弓形起翘：手腕关节处高拱+48mm，翼尖优雅后掠微扣
                return 48.0 * math.sin(math.pi * (abs_u ** 0.70)) * (1.0 - 0.25 * abs_u) - 6.0 * (abs_u ** 2.0)
            elif mode == 1:
                # Elevated V-Stroke (高昂V字扬翅)
                return 18.0 * math.sin(math.pi * abs_u) + 52.0 * (abs_u ** 1.35)
            elif mode == 2:
                # Down-Cupped Vault (抱翅俯冲/微弯弧)
                return 32.0 * math.sin(math.pi * (abs_u ** 0.75)) - 22.0 * (abs_u ** 1.6)
            else:
                # Level Gliding Soar (平展掠翔)
                return 18.0 * math.sin(math.pi * (abs_u ** 0.85)) + 8.0 * (abs_u ** 1.2)

        top_grid = []
        bot_grid = []
        for s_i in range(n_s + 1):
            u = -1.0 + 2.0 * s_i / float(n_s)
            abs_u = abs(u)
            # Gentle streamlined wing planform (subtle wrist curve, delicate tapered wingtip)
            y_le = -18.0 - 32.0 * math.sin(math.pi * (abs_u ** 0.78)) + 64.0 * (abs_u ** 1.85)
            chord_base = 38.0 + 78.0 * math.sin(math.pi * (abs_u ** 0.70)) * ((1.0 - abs_u) ** 0.42)
            feather_scallop = 0.0
            if 0.20 < abs_u < 0.98:
                feather_scallop = 5.8 * abs(math.sin(7.0 * math.pi * abs_u)) * (1.0 - 0.3 * abs_u)
            loc_ch = max(14.0, chord_base + feather_scallop)

            z_arch = _wing_elevation_mm(abs_u, flap_mode)
            row_top = []
            row_bot = []
            for c_i in range(n_c + 1):
                v = c_i / float(n_c)
                z_cam = 4.8 * math.sin(math.pi * (v ** 0.75)) * (1.0 - 0.45 * abs_u)
                lx = (u * half_span) * MM
                ly = (y_le + v * loc_ch) * MM
                lz = (z_arch + z_cam) * MM
                t_edge = thick_m * (0.50 + 0.50 * math.sin(math.pi * v))
                row_top.append(bm_b.verts.new((lx, ly, lz + 0.5 * t_edge)))
                row_bot.append(bm_b.verts.new((lx, ly, lz - 0.5 * t_edge)))
            top_grid.append(row_top)
            bot_grid.append(row_bot)

        for s_i in range(n_s):
            for c_i in range(n_c):
                bm_b.faces.new([top_grid[s_i][c_i], top_grid[s_i+1][c_i], top_grid[s_i+1][c_i+1], top_grid[s_i][c_i+1]])
                bm_b.faces.new([bot_grid[s_i][c_i+1], bot_grid[s_i+1][c_i+1], bot_grid[s_i+1][c_i], bot_grid[s_i][c_i]])
            bm_b.faces.new([top_grid[s_i][0], bot_grid[s_i][0], bot_grid[s_i+1][0], top_grid[s_i+1][0]])
            bm_b.faces.new([top_grid[s_i+1][n_c], bot_grid[s_i+1][n_c], bot_grid[s_i][n_c], top_grid[s_i][n_c]])
        for c_i in range(n_c):
            bm_b.faces.new([top_grid[0][c_i+1], bot_grid[0][c_i+1], bot_grid[0][c_i], top_grid[0][c_i]])
            bm_b.faces.new([top_grid[n_s][c_i], bot_grid[n_s][c_i], bot_grid[n_s][c_i+1], top_grid[n_s][c_i+1]])

        bmesh.ops.recalc_face_normals(bm_b, faces=bm_b.faces[:])
        bm_b.to_mesh(mesh_b)
        bm_b.free()
        for p in mesh_b.polygons:
            p.use_smooth = True
        obj_w = bpy.data.objects.new(f"{bname}_Wings", mesh_b)
        obj_w.data.materials.append(MATS["Frosted_Acrylic_Bird"])
        obj_w.location = (cx_mm * MM, cy_mm * MM, cz_m)
        obj_w.rotation_euler = (math.radians(pitch_deg), math.radians(roll_deg), math.radians(yaw_deg))
        link_obj(obj_w, col)

        # Golden Brass Spine Clip (length 88mm, radius 8.5/7.0mm)
        mesh_clip = bpy.data.meshes.new(f"{bname}_BrassClip")
        bm_c = bmesh.new()
        bmesh.ops.create_cone(bm_c, cap_ends=True, cap_tris=False, segments=16, radius1=0.0085, radius2=0.0070, depth=0.088)
        for v in bm_c.verts:
            vy, vz = v.co.z - 0.003, -v.co.y - 0.001
            v.co.y, v.co.z = vy, vz
        bmesh.ops.recalc_face_normals(bm_c, faces=bm_c.faces[:])
        bm_c.to_mesh(mesh_clip)
        bm_c.free()
        for p in mesh_clip.polygons:
            p.use_smooth = True
        obj_clip = bpy.data.objects.new(f"{bname}_BrassClip", mesh_clip)
        obj_clip.data.materials.append(MATS["Gold_Brass"])
        obj_clip.location = (cx_mm * MM, cy_mm * MM, cz_m)
        obj_clip.rotation_euler = (math.radians(pitch_deg), math.radians(roll_deg), math.radians(yaw_deg))
        link_obj(obj_clip, col)

        # Warm LED glowing core
        add_cyl_mm(f"{bname}_LEDCore", cx_mm, cy_mm, 5.5, cz_m - 0.004, cz_m + 0.008, MATS["Bird_LED_Glow"], col, segs=12)

        # Ultra-fine twin vertical suspension wires rising directly to ceiling surface per original reference photos
        # Two vertical wires attach to the front (+24mm) and rear (-24mm) of the golden brass spine clip
        yaw_rad = math.radians(yaw_deg)
        sin_y = math.sin(yaw_rad)
        cos_y = math.cos(yaw_rad)
        xf_mm = cx_mm - 24.0 * sin_y
        yf_mm = cy_mm + 24.0 * cos_y
        xr_mm = cx_mm + 24.0 * sin_y
        yr_mm = cy_mm - 24.0 * cos_y

        zf_ceil = get_wave_ceiling_z(xf_mm, yf_mm)
        zr_ceil = get_wave_ceiling_z(xr_mm, yr_mm)

        # Dual vertical brass suspension wires (diameter 1.9mm)
        add_cyl_mm(f"{bname}_WireF", xf_mm, yf_mm, 0.95, cz_m + 0.008, zf_ceil, MATS["Gold_Brass"], col, segs=8)
        add_cyl_mm(f"{bname}_WireR", xr_mm, yr_mm, 0.95, cz_m + 0.008, zr_ceil, MATS["Gold_Brass"], col, segs=8)
        # Ceiling mounting brass rose caps
        add_cyl_mm(f"{bname}_CapF", xf_mm, yf_mm, 4.5, zf_ceil - 0.003, zf_ceil + 0.002, MATS["Gold_Brass"], col, segs=12)
        add_cyl_mm(f"{bname}_CapR", xr_mm, yr_mm, 4.5, zr_ceil - 0.003, zr_ceil + 0.002, MATS["Gold_Brass"], col, segs=12)

    # Pure Organic S-Curve Flock (S形优雅行进编队, 沿流线走廊同宽度2~3只并排, 19只流线排布, rev. 2026-11-07 v11):
    # - "后退一步，现在四周的环境一点点都没有了": 相机后退至 y=-3.50m (x=3.65m, z=1.35m)，完美复现左侧螺旋楼梯弧形扶手、立柱、通道与右侧落地窗全景。
    # - "顶上的天花板也不对": 天花板重塑为 380mm 深下潜的连贯双波浪桶状曲面 (波谷 z=2.68m, 波峰 z=3.06m)，彻底消除瓦楞生硬感，呈现与原图一致的柔光立体穹顶。
    # - "鸟儿可以同宽度上有2，3个": 每一处集群在流线宽度方向均有 2~3 只并排齐飞，错落有致，羽翼弓背展翅。
    def generate_organic_s_flock():
        def s_curve_center_y(x):
            t = (x - 2550.0) / (5900.0 - 2550.0)
            return -100.0 + 280.0 * math.sin(2.0 * math.pi * t)

        pods_spec = [
            # Pod 0: Front West Leader & Wingman (2 birds abreast, flap_mode=0 弓形展翅)
            [
                (2550.0, -80.0, 1.94, 345.0, 0),
                (2670.0,  70.0, 1.90, 310.0, 1),
            ],
            # Pod 1: West Wing Escort (3 birds abreast along S-curve bend)
            [
                (3000.0, -140.0, 1.86, 300.0, 0),
                (3120.0,    0.0, 1.90, 325.0, 2),
                (3240.0,  130.0, 1.84, 290.0, 3),
            ],
            # Pod 2: TV Niche Swell (3 birds abreast swooping North towards TV wall, overlapping cabinet upper zone)
            [
                (3600.0, -130.0, 1.82, 315.0, 0),
                (3720.0,   10.0, 1.87, 330.0, 3),
                (3840.0,  140.0, 1.80, 295.0, 2),
            ],
            # Pod 3: Mid-Chamber Center Link (3 birds abreast crossing center)
            [
                (4180.0, -110.0, 1.92, 310.0, 1),
                (4280.0,   10.0, 1.98, 325.0, 0),
                (4380.0,  120.0, 1.94, 295.0, 3),
            ],
            # Pod 4: Right Bookcase Swell (3 birds abreast swooping South towards living room)
            [
                (4750.0, -140.0, 1.86, 305.0, 3),
                (4880.0,    0.0, 1.90, 335.0, 0),
                (5010.0,  130.0, 1.84, 290.0, 2),
            ],
            # Pod 5: Window Approach (3 birds abreast)
            [
                (5350.0, -120.0, 1.96, 310.0, 1),
                (5480.0,   10.0, 2.00, 325.0, 0),
                (5600.0,  120.0, 1.97, 285.0, 3),
            ],
            # Pod 6: East Window Tail Guard (2 birds abreast entering from window ceiling)
            [
                (5800.0,  -80.0, 2.02, 295.0, 0),
                (5920.0,   70.0, 2.06, 310.0, 1),
            ],
        ]

        birds = []
        for pod in pods_spec:
            for bx, by_offset, bz, bspan, bmode in pod:
                cy = s_curve_center_y(bx) + by_offset
                t = (bx - 2550.0) / (5900.0 - 2550.0)

                # Tangent along S-curve
                vx = -1.0
                vy_tan = -(280.0 * 2.0 * math.pi / 3350.0) * math.cos(2.0 * math.pi * t)
                vz = -0.04 * math.cos(2.0 * math.pi * t)

                yaw = math.degrees(math.atan2(vx, -vy_tan))
                pitch = math.degrees(math.atan2(vz, math.sqrt(vx*vx + vy_tan*vy_tan)))
                roll = -vy_tan * 18.0

                birds.append({
                    'pos': (bx, cy, bz),
                    'span': bspan,
                    'mode': bmode,
                    'yaw': yaw,
                    'pitch': pitch,
                    'roll': roll
                })
        return birds

    s_flock = generate_organic_s_flock()
    for b_idx, b in enumerate(s_flock):
        bx, by, bz = b['pos']
        add_flying_bird(f"1F_Living_Bird_{b_idx+1}", bx, by, z_1f + bz, b['yaw'], b['pitch'], b['roll'], span_mm=b['span'], flap_mode=b['mode'], col=col_1f)

    # 1F Front-Door Exterior Private Courtyard (Building 56 Unit 103, calibrated to Zone 4 Master CAD 置信四区地下室桩图)
    # Front yard outside 1F_Main_Entry_Door: X=-12600..-7155 (5.45m), Y=-8200..+1765 (9.97m); S side garden wraps Kitchen/Toilet/Living
    def _build_1f_courtyard():
        gmat, smat, wmat = MATS["Plant_Bamboo_Green"], MATS["Travertine_Stone"], MATS["Wall_Panel_Cream"]
        fmat, dmat, lmat = MATS["Stair_Bronze_Iron"], MATS["Cabinet_Walnut"], MATS["Warm_LED_Glow"]
        cmat = MATS["Marble_Fishbelly"]
        # Non-overlapping lawn beds & exterior terrace slabs
        add_box_mm("1F_Courtyard_Lawn_FN", -12420.0, -7155.0, -1100.0, 1585.0, z_1f - 0.15, z_1f - 0.030, gmat, col_1f)
        add_box_mm("1F_Courtyard_Lawn_FPathS", -9000.0, -7155.0, -4600.0, -3200.0, z_1f - 0.15, z_1f - 0.030, gmat, col_1f)
        add_box_mm("1F_Courtyard_Lawn_FM", -12420.0, -9000.0, -4600.0, -2900.0, z_1f - 0.15, z_1f - 0.030, gmat, col_1f)
        add_box_mm("1F_Courtyard_Lawn_SideW", -7155.0, -1488.0, -8020.0, -5070.0, z_1f - 0.15, z_1f - 0.030, gmat, col_1f)
        add_box_mm("1F_Courtyard_Lawn_SideM", -1488.0, 743.0, -8020.0, -5520.0, z_1f - 0.15, z_1f - 0.030, gmat, col_1f)
        add_box_mm("1F_Courtyard_Lawn_SideE", 743.0, 6440.0, -8020.0, -5760.0, z_1f - 0.15, z_1f - 0.030, gmat, col_1f)
        add_box_mm("1F_Courtyard_Lawn_SECorner", -12420.0, -7155.0, -8020.0, -7600.0, z_1f - 0.15, z_1f - 0.030, gmat, col_1f)
        add_box_mm("1F_Courtyard_Lawn_SWGap", -9400.0, -7155.0, -7600.0, -4600.0, z_1f - 0.15, z_1f - 0.030, gmat, col_1f)
        add_box_mm("1F_Courtyard_Lawn_WGap", -12420.0, -12100.0, -7600.0, -4600.0, z_1f - 0.15, z_1f - 0.030, gmat, col_1f)
        # Raised stone entry porch outside 1F_Main_Entry_Door (-9000..-7155, -3200..-1100) + entry path to West gate
        add_box_mm("1F_Courtyard_EntryPorch", -9000.0, -7155.0, -3200.0, -1100.0, z_1f - 0.15, z_1f - 0.012, cmat, col_1f)
        add_box_mm("1F_Courtyard_PathBase", -12510.0, -9000.0, -2900.0, -1300.0, z_1f - 0.15, z_1f - 0.028, smat, col_1f)
        for _pi, _px in enumerate((-12350.0, -11650.0, -10950.0, -10250.0, -9550.0), 1):
            add_box_mm(f"1F_Courtyard_SteppingStone_{_pi}", _px, _px + 560.0, -2750.0, -1450.0, z_1f - 0.028, z_1f - 0.008, cmat, col_1f, r_corner=16.0)
        # Outdoor wooden lounge deck terrace (SW courtyard: -12100..-9400, -7600..-4600) + table & 2 slatted benches
        add_box_mm("1F_Courtyard_WoodDeck", -12100.0, -9400.0, -7600.0, -4600.0, z_1f - 0.15, z_1f - 0.008, dmat, col_1f)
        add_box_mm("1F_Courtyard_GardenTableTop", -11250.0, -10250.0, -6500.0, -5700.0, z_1f + 0.68, z_1f + 0.72, smat, col_1f, r_corner=24.0)
        add_box_mm("1F_Courtyard_GardenTableLeg1", -11120.0, -11050.0, -6400.0, -5800.0, z_1f - 0.008, z_1f + 0.68, fmat, col_1f)
        add_box_mm("1F_Courtyard_GardenTableLeg2", -10450.0, -10380.0, -6400.0, -5800.0, z_1f - 0.008, z_1f + 0.68, fmat, col_1f)
        add_box_mm("1F_Courtyard_Bench_W", -11800.0, -11400.0, -6500.0, -5700.0, z_1f + 0.38, z_1f + 0.43, dmat, col_1f, r_corner=12.0)
        add_box_mm("1F_Courtyard_Bench_W_Leg", -11720.0, -11480.0, -6420.0, -5780.0, z_1f - 0.008, z_1f + 0.38, fmat, col_1f)
        add_box_mm("1F_Courtyard_Bench_E", -10100.0, -9700.0, -6500.0, -5700.0, z_1f + 0.38, z_1f + 0.43, dmat, col_1f, r_corner=12.0)
        add_box_mm("1F_Courtyard_Bench_E_Leg", -10020.0, -9780.0, -6420.0, -5780.0, z_1f - 0.008, z_1f + 0.38, fmat, col_1f)
        # Perimeter dwarf walls (180mm thick) + coping + 5 horizontal bronze privacy louver slats (0.80..1.42m)
        _cwall_segs = [
            ("WN", -12600.0, -12420.0, -1300.0, 1765.0),
            ("WS", -12600.0, -12420.0, -8200.0, -2900.0),
            ("N",  -12420.0, -5794.0,   1585.0,  1765.0),
            ("S",  -12420.0,  6620.0,  -8200.0, -8020.0),
            ("E",    6440.0,  6620.0,  -8020.0, -5760.0),
        ]
        for _cw_id, _wx0, _wx1, _wy0, _wy1 in _cwall_segs:
            add_box_mm(f"1F_Courtyard_Wall_{_cw_id}", _wx0, _wx1, _wy0, _wy1, z_1f - 0.15, z_1f + 0.68, wmat, col_1f)
            add_box_mm(f"1F_Courtyard_WallCap_{_cw_id}", _wx0 - 15.0, _wx1 + 15.0, _wy0 - 15.0, _wy1 + 15.0, z_1f + 0.68, z_1f + 0.72, smat, col_1f)
            # Horizontal bronze fence rails above masonry coping
            for _ri, _rz in enumerate((0.84, 0.98, 1.12, 1.26, 1.40), 1):
                if abs(_wx1 - _wx0) < 250.0:
                    _rx0, _rx1, _ry0, _ry1 = _wx0 + 70.0, _wx1 - 70.0, _wy0, _wy1
                else:
                    _rx0, _rx1, _ry0, _ry1 = _wx0, _wx1, _wy0 + 70.0, _wy1 - 70.0
                add_box_mm(f"1F_Courtyard_FenceRail_{_cw_id}_{_ri}", _rx0, _rx1, _ry0, _ry1, z_1f + _rz, z_1f + _rz + 0.026, fmat, col_1f)
            # Slim fence posts every ~2m
            if abs(_wx1 - _wx0) < 250.0:
                _n_p = max(2, int((_wy1 - _wy0) / 2000.0) + 1)
                for _pi in range(_n_p):
                    _py = _wy0 + 30.0 + (_wy1 - _wy0 - 60.0) * _pi / max(1, _n_p - 1)
                    add_box_mm(f"1F_Courtyard_Post_{_cw_id}_{_pi+1}", _wx0 + 60.0, _wx1 - 60.0, _py - 25.0, _py + 25.0, z_1f + 0.72, z_1f + 1.44, fmat, col_1f)
            else:
                _n_p = max(2, int((_wx1 - _wx0) / 2000.0) + 1)
                for _pi in range(_n_p):
                    _px = _wx0 + 30.0 + (_wx1 - _wx0 - 60.0) * _pi / max(1, _n_p - 1)
                    add_box_mm(f"1F_Courtyard_Post_{_cw_id}_{_pi+1}", _px - 25.0, _px + 25.0, _wy0 + 60.0, _wy1 - 60.0, z_1f + 0.72, z_1f + 1.44, fmat, col_1f)
        # Double courtyard entry gate at X=-12600, Y=-2900..-1300
        add_box_mm("1F_Courtyard_GatePillar_S", -12660.0, -12360.0, -3050.0, -2750.0, z_1f - 0.15, z_1f + 1.65, smat, col_1f)
        add_box_mm("1F_Courtyard_GatePillar_N", -12660.0, -12360.0, -1450.0, -1150.0, z_1f - 0.15, z_1f + 1.65, smat, col_1f)
        add_box_mm("1F_Courtyard_Gate_Door_S", -12530.0, -12490.0, -2745.0, -2105.0, z_1f + 0.04, z_1f + 1.45, fmat, col_1f)
        add_box_mm("1F_Courtyard_Gate_Door_N", -12530.0, -12490.0, -2095.0, -1455.0, z_1f + 0.04, z_1f + 1.45, fmat, col_1f)
        add_box_mm("1F_Courtyard_Gate_Handle_S", -12550.0, -12470.0, -2160.0, -2130.0, z_1f + 0.92, z_1f + 1.12, MATS["Gold_Brass"], col_1f)
        add_box_mm("1F_Courtyard_Gate_Handle_N", -12550.0, -12470.0, -2070.0, -2040.0, z_1f + 0.92, z_1f + 1.12, MATS["Gold_Brass"], col_1f)
        # Perimeter planters, stylized bamboo greenery & 4 warm LED garden bollards
        add_box_mm("1F_Courtyard_Planter_N", -12400.0, -7200.0, 950.0, 1570.0, z_1f - 0.03, z_1f + 0.36, wmat, col_1f)
        add_box_mm("1F_Courtyard_Planter_S", -12400.0, 4800.0, -8005.0, -7450.0, z_1f - 0.03, z_1f + 0.36, wmat, col_1f)
        for _bi, _bx in enumerate((-11600.0, -10400.0, -9200.0, -8000.0), 1):
            add_cyl_mm(f"1F_Courtyard_BambooN_Stem_{_bi}", _bx, 1260.0, 38.0, z_1f + 0.36, z_1f + 2.10, gmat, col_1f, segs=12)
            add_box_mm(f"1F_Courtyard_BambooN_Canopy_{_bi}", _bx - 260.0, _bx + 260.0, 1020.0, 1500.0, z_1f + 1.45, z_1f + 2.35, gmat, col_1f, r_corner=80.0)
        for _bi, _bx in enumerate((-11400.0, -8600.0, -4800.0, -1200.0, 2400.0), 1):
            add_cyl_mm(f"1F_Courtyard_BambooS_Stem_{_bi}", _bx, -7720.0, 38.0, z_1f + 0.36, z_1f + 2.05, gmat, col_1f, segs=12)
            add_box_mm(f"1F_Courtyard_BambooS_Canopy_{_bi}", _bx - 260.0, _bx + 260.0, -7960.0, -7480.0, z_1f + 1.40, z_1f + 2.25, gmat, col_1f, r_corner=80.0)
        for _li, (_lx, _ly) in enumerate(((-12150.0, -2950.0), (-12150.0, -1250.0), (-9200.0, -3050.0), (-9200.0, -1150.0)), 1):
            add_box_mm(f"1F_Courtyard_BollardPost_{_li}", _lx - 45.0, _lx + 45.0, _ly - 45.0, _ly + 45.0, z_1f - 0.02, z_1f + 0.54, fmat, col_1f)
            add_box_mm(f"1F_Courtyard_BollardGlow_{_li}", _lx - 38.0, _lx + 38.0, _ly - 38.0, _ly + 38.0, z_1f + 0.54, z_1f + 0.62, lmat, col_1f)
    _build_1f_courtyard()

    # 1F -> 2F Spiral Stair: Steps 16..30 spiral COUNTER-CLOCKWISE from +25° (ENE on 1F) to +265° (S landing on 2F)
    build_spiral_stair_flight("1F_To_2F_Spiral", 0.0, 0.0, 470.0, 1430.0, 25.0, 265.0, z_1f, 3.30, 15, col_1f)
    # 1F CAD linework removed per user requirement: 没有黑线。全部都是浅青色水晶石
    # add_cad_linework_curve(msp, "1F", p_1f["xr"], p_1f["yr"], *p_1f["orig"], z_1f + 0.008, col_1f)

    # =========================================================================
    # FLOOR 4: 2F_二层 (Second Floor Bedrooms, z0 = +3.30m, h = 2.83m)
    # =========================================================================
    col_2f = bpy.data.collections.new("2F_二层")
    bpy.context.scene.collection.children.link(col_2f)
    cols["2F_Plan"] = col_2f
    p_2f = PLANS["2F_Plan"]
    z_2f, h_2f = p_2f["z0"], p_2f["h"]
    zf_2f = z_2f + 0.005

    add_box_mm("2F_Slab_Washing", -8980, -6871, -1480, 1020, z_2f - 0.15, z_2f, MATS["Slab_Wood"], col_2f)
    add_box_mm("2F_Slab_Child_Balcony", -6869, -3480, -2660, 380, z_2f - 0.15, z_2f, MATS["Slab_Wood"], col_2f)
    add_box_mm("2F_Slab_ChildWIC", -5270, -3480, -4560, -2660, z_2f - 0.15, z_2f, MATS["Slab_Wood"], col_2f)
    add_box_mm("2F_Slab_SW_Laundry", -6869, -5270, -4560, -2660, z_2f - 0.15, z_2f, MATS["Slab_Tile_Bath"], col_2f)
    add_box_mm("2F_Slab_Child_EntryHall", -3480, -1552, -2660, -1605, z_2f - 0.15, z_2f, MATS["Slab_Wood"], col_2f)
    add_box_mm("2F_Slab_ChildBath", -3480, -1552, -1605, 380, z_2f - 0.15, z_2f, MATS["Slab_Tile_Bath"], col_2f)
    add_box_mm("2F_Slab_MasterBath", -3490, -542, -5400, -2682, z_2f - 0.15, z_2f, MATS["Slab_Tile_Bath"], col_2f)
    add_box_mm("2F_Slab_WIC", -540, 1640, -5400, -2682, z_2f - 0.15, z_2f, MATS["Slab_Wood"], col_2f)
    add_box_mm("2F_Slab_MasterBed", 1642, 6622, -5400, -1782, z_2f - 0.15, z_2f, MATS["Slab_Wood"], col_2f)
    add_box_mm("2F_Slab_ParentRoom", 650, 6622, -1780, 1580, z_2f - 0.15, z_2f, MATS["Slab_Wood"], col_2f)
    add_box_mm("2F_Slab_Crossing_S", -1550, 1640, -2680, -1620, z_2f - 0.15, z_2f, MATS["Slab_Wood"], col_2f)
    add_box_mm("2F_Slab_Crossing_E", -125, 648, -1618, -480, z_2f - 0.15, z_2f, MATS["Slab_Wood"], col_2f)
    add_box_mm("2F_Stair_Glass_Rail", -1480, -400, -1650, -1600, zf_2f, z_2f + 1.05, MATS["Window_Glass"], col_2f)
    add_box_mm("2F_Stair_Glass_Rail_E", 450, 648, -500, -460, zf_2f, z_2f + 1.05, MATS["Window_Glass"], col_2f)

    c2f_cutouts = [
        (-9090, -8890, -1580,   940), # NW Tatami W full-height floor-to-ceiling glass
        (-9090, -6850, -1590, -1395), # NW Tatami S full-height floor-to-ceiling glass
        (-7020, -6820, -4660, -2300), # SW Laundry W full-height glass + balcony door
        (-7010, -5340, -4660, -4465), # SW Laundry S full-height glass
        (-3615, -3360, -5280, -4630), # MasterBath win
        ( 6495,  6755, -5280, -2140), # MasterBed win (aligned flush to 1F East wall 6502..6742)
        ( 6495,  6755, -1340,  1130), # ParentRoom win (aligned flush to 1F East wall 6502..6742)
        (-1635, -1480, -2523, -1723), # ChildRoom door
        (-3260, -2550, -1660, -1550), # ChildBath door
        (-4775, -4155, -2720, -2600), # ChildWIC door
        ( 1568,  1723, -2700, -1895), # MasterBed door (calibrated +213mm East -> MasterBed 4788mm)
        ( 1355,  1510, -1410,  -580), # ParentRoom door
        ( 1640,  2450,  -495,  -355), # ParentBath door
        ( -615,  -445, -4540, -3485), # WIC Bath door
    ]
    build_manifold_walls(msp, "2F_Plan", p_2f["xr"], p_2f["yr"], *p_2f["orig"], z_2f + 0.002, h_2f, c2f_cutouts, col_2f)

    # Full floor-to-ceiling exterior curtain glass (h1_sill=0.00, h2_win=2.500) for NW Tatami & SW Laundry
    build_window("2F_Win_Washing_W",  -9000, -8920, -1480,   935, z_2f + 0.002, h_2f, 0.00, 2.500, col_2f)
    build_window("2F_Win_Washing_S",  -8960, -6870, -1525, -1445, z_2f + 0.002, h_2f, 0.00, 2.500, col_2f)
    add_box_mm("2F_Win_Washing_CornerPost", -9005, -8920, -1530, -1445, z_2f + 0.002, z_2f + 2.500, MATS["Window_Frame"], col_2f)
    build_window("2F_Win_Balcony_W",  -6955, -6880, -4550, -3450, z_2f + 0.002, h_2f, 0.00, 2.500, col_2f)
    build_window("2F_Win_Balcony_WN", -6955, -6880, -2620, -2305, z_2f + 0.002, h_2f, 0.00, 2.500, col_2f)
    build_window("2F_Win_Balcony_S",  -6920, -5345, -4595, -4515, z_2f + 0.002, h_2f, 0.00, 2.500, col_2f)
    add_box_mm("2F_Win_Balcony_CornerPost", -6960, -6880, -4600, -4515, z_2f + 0.002, z_2f + 2.500, MATS["Window_Frame"], col_2f)
    build_window("2F_Win_MasterBath", -3609, -3369, -5280, -4630, z_2f + 0.002, h_2f, 0.86, 1.75, col_2f)
    build_window("2F_Win_MasterBed",   6502,  6742, -5280, -2140, z_2f + 0.002, h_2f, 0.30, 2.05, col_2f)
    build_window("2F_Win_ParentRoom",  6502,  6742, -1340,  1130, z_2f + 0.002, h_2f, 0.20, 2.20, col_2f)

    # Operable out-swinging glass door (2F_Door_SW_Balcony, X=-6955..-6880, Y=-3450..-2620, swung 32 deg out toward -X steel balcony)
    def _build_sw_balcony_door():
        dx0, dx1, dy0, dy1 = -6955.0, -6880.0, -3450.0, -2620.0
        zd0, zd1 = z_2f + 0.002, z_2f + 2.500
        fmat, gmat, hmat = MATS["Window_Frame"], MATS["Window_Glass"], MATS["B2_Chrome_Silver"]
        add_box_mm("2F_Door_SW_Balcony_Header", dx0, dx1, dy0, dy1, zd1, z_2f + h_2f, MATS["Wall_Struct"], col_2f)
        add_box_mm("2F_Door_SW_Balcony_TopFrame", dx0, dx1, dy0, dy1, zd1 - 0.042, zd1, fmat, col_2f)
        add_box_mm("2F_Door_SW_Balcony_Thresh", dx0, dx1, dy0, dy1, zd0, zd0 + 0.022, fmat, col_2f)
        add_box_mm("2F_Door_SW_Balcony_JambS", dx0, dx1, dy0, dy0 + 38.0, zd0 + 0.022, zd1 - 0.042, fmat, col_2f)
        add_box_mm("2F_Door_SW_Balcony_JambN", dx0, dx1, dy1 - 38.0, dy1, zd0 + 0.022, zd1 - 0.042, fmat, col_2f)
        hx, hy = -6940.0, dy0 + 38.0
        ang = math.radians(32.0)  # +Y local -> rotated toward -X (out onto steel balcony) & +Y
        ca, sa = math.cos(ang), math.sin(ang)
        def _rot_xy(lx, ly):
            return (hx - lx * ca - ly * sa, hy - lx * sa + ly * ca)
        def _add_rot_box(bname, lx0, lx1, ly0, ly1, zb0, zb1, bmat):
            pts = [_rot_xy(lx0, ly0), _rot_xy(lx1, ly0), _rot_xy(lx1, ly1), _rot_xy(lx0, ly1)]
            return add_prism(bname, pts, zb0, zb1, bmat, col_2f)
        lw = (dy1 - 38.0) - (dy0 + 38.0) - 8.0
        lz0, lz1 = zd0 + 0.028, zd1 - 0.048
        st = 52.0
        _add_rot_box("2F_Door_SW_Balcony_Leaf_StileS", -20.0, 20.0, 0.0, st, lz0, lz1, fmat)
        _add_rot_box("2F_Door_SW_Balcony_Leaf_StileN", -20.0, 20.0, lw - st, lw, lz0, lz1, fmat)
        _add_rot_box("2F_Door_SW_Balcony_Leaf_RailB", -20.0, 20.0, st, lw - st, lz0, lz0 + 0.075, fmat)
        _add_rot_box("2F_Door_SW_Balcony_Leaf_RailT", -20.0, 20.0, st, lw - st, lz1 - 0.055, lz1, fmat)
        _add_rot_box("2F_Door_SW_Balcony_Leaf_Glass", -6.0, 6.0, st, lw - st, lz0 + 0.075, lz1 - 0.055, gmat)
        _add_rot_box("2F_Door_SW_Balcony_Leaf_HandleIn", -38.0, -20.0, lw - 80.0, lw - 24.0, z_2f + 0.96, z_2f + 1.18, hmat)
        _add_rot_box("2F_Door_SW_Balcony_Leaf_HandleOut", 20.0, 38.0, lw - 80.0, lw - 24.0, z_2f + 0.96, z_2f + 1.18, hmat)
        for _hi, _hz in enumerate((zd0 + 0.35, zd0 + 1.25, zd1 - 0.35), 1):
            add_cyl_mm(f"2F_Door_SW_Balcony_Hinge_{_hi}", hx, hy, 9.0, _hz - 0.045, _hz + 0.045, hmat, col_2f, segs=12)
    _build_sw_balcony_door()

    # Exterior Steel-Frame Drying Balcony (2F_SteelBalcony_*, X=-8980..-6990, Y=-4580..-2320, max Z=z_2f+2.480)
    def _build_sw_steel_balcony():
        smat, dmat, gmat = MATS["Stair_Bronze_Iron"], MATS["Cabinet_Walnut"], MATS["Window_Glass"]
        rmat = MATS["B2_Chrome_Silver"]
        x0, x1, y0, y1 = -8980.0, -6990.0, -4580.0, -2320.0
        # Steel deck perimeter girders + transverse joists + cantilevered wall-anchor gussets
        add_box_mm("2F_SteelBalcony_GirderW", x0, x0 + 90.0, y0, y1, z_2f - 0.140, z_2f - 0.022, smat, col_2f)
        add_box_mm("2F_SteelBalcony_GirderE", x1 - 90.0, x1, y0, y1, z_2f - 0.140, z_2f - 0.022, smat, col_2f)
        add_box_mm("2F_SteelBalcony_GirderS", x0 + 90.0, x1 - 90.0, y0, y0 + 90.0, z_2f - 0.140, z_2f - 0.022, smat, col_2f)
        add_box_mm("2F_SteelBalcony_GirderN", x0 + 90.0, x1 - 90.0, y1 - 90.0, y1, z_2f - 0.140, z_2f - 0.022, smat, col_2f)
        for _ji, _jy in enumerate((-4120.0, -3670.0, -3220.0, -2770.0), 1):
            add_box_mm(f"2F_SteelBalcony_Joist_{_ji}", x0 + 90.0, x1 - 90.0, _jy - 35.0, _jy + 35.0, z_2f - 0.125, z_2f - 0.022, smat, col_2f)
        for _bi, _by in enumerate((-4480.0, -3450.0, -2420.0), 1):
            add_box_mm(f"2F_SteelBalcony_BracketTop_{_bi}", -7980.0, x1, _by - 35.0, _by + 35.0, z_2f - 0.240, z_2f - 0.140, smat, col_2f)
            add_box_mm(f"2F_SteelBalcony_BracketWall_{_bi}", -7100.0, x1, _by - 35.0, _by + 35.0, z_2f - 0.560, z_2f - 0.240, smat, col_2f)
            add_box_mm(f"2F_SteelBalcony_BracketDiag_{_bi}", -7780.0, -7100.0, _by - 28.0, _by + 28.0, z_2f - 0.420, z_2f - 0.240, smat, col_2f)
        # Slatted hardwood outdoor decking (12 slats along Y)
        n_slats = 12
        pitch_x = (x1 - 20.0 - (x0 + 40.0)) / n_slats
        for _si in range(n_slats):
            sx0 = x0 + 40.0 + _si * pitch_x + 8.0
            sx1 = x0 + 40.0 + (_si + 1) * pitch_x - 8.0
            add_box_mm(f"2F_SteelBalcony_Deck_{_si+1}", sx0, sx1, y0 + 40.0, y1 - 40.0, z_2f - 0.022, z_2f - 0.002, dmat, col_2f)
        # 4 slim corner steel columns + pergola top beams (z<=2.480)
        for _ci, (_cx, _cy) in enumerate(((x0 + 35.0, y0 + 35.0), (x0 + 35.0, y1 - 35.0), (x1 - 35.0, y0 + 35.0), (x1 - 35.0, y1 - 35.0)), 1):
            add_box_mm(f"2F_SteelBalcony_Col_{_ci}", _cx - 35.0, _cx + 35.0, _cy - 35.0, _cy + 35.0, z_2f - 0.140, z_2f + 2.480, smat, col_2f)
        add_box_mm("2F_SteelBalcony_TopBeamW", x0, x0 + 70.0, y0, y1, z_2f + 2.415, z_2f + 2.480, smat, col_2f)
        add_box_mm("2F_SteelBalcony_TopBeamE", x1 - 70.0, x1, y0, y1, z_2f + 2.415, z_2f + 2.480, smat, col_2f)
        add_box_mm("2F_SteelBalcony_TopBeamS", x0 + 70.0, x1 - 70.0, y0, y0 + 70.0, z_2f + 2.415, z_2f + 2.480, smat, col_2f)
        add_box_mm("2F_SteelBalcony_TopBeamN", x0 + 70.0, x1 - 70.0, y1 - 70.0, y1, z_2f + 2.415, z_2f + 2.480, smat, col_2f)
        add_box_mm("2F_SteelBalcony_TopCrossS", x0 + 70.0, x1 - 70.0, -4280.0, -4220.0, z_2f + 2.415, z_2f + 2.470, smat, col_2f)
        add_box_mm("2F_SteelBalcony_TopCrossN", x0 + 70.0, x1 - 70.0, -2680.0, -2620.0, z_2f + 2.415, z_2f + 2.470, smat, col_2f)
        # Clear glass + slim steel guardrail on W/S/N edges (Z=0.00..1.10m)
        add_box_mm("2F_SteelBalcony_RailTopW", x0 + 15.0, x0 + 55.0, y0 + 70.0, y1 - 70.0, z_2f + 1.050, z_2f + 1.095, smat, col_2f)
        add_box_mm("2F_SteelBalcony_RailBotW", x0 + 20.0, x0 + 50.0, y0 + 70.0, y1 - 70.0, z_2f + 0.030, z_2f + 0.065, smat, col_2f)
        add_box_mm("2F_SteelBalcony_RailGlassW", x0 + 29.0, x0 + 41.0, y0 + 70.0, y1 - 70.0, z_2f + 0.065, z_2f + 1.050, gmat, col_2f)
        add_box_mm("2F_SteelBalcony_MidPostW", x0 + 18.0, x0 + 52.0, -3470.0, -3430.0, z_2f - 0.002, z_2f + 1.050, smat, col_2f)
        for _rtag, _ry in (("S", y0 + 35.0), ("N", y1 - 35.0)):
            add_box_mm(f"2F_SteelBalcony_RailTop{_rtag}", x0 + 70.0, x1 - 70.0, _ry - 20.0, _ry + 20.0, z_2f + 1.050, z_2f + 1.095, smat, col_2f)
            add_box_mm(f"2F_SteelBalcony_RailBot{_rtag}", x0 + 70.0, x1 - 70.0, _ry - 15.0, _ry + 15.0, z_2f + 0.030, z_2f + 0.065, smat, col_2f)
            add_box_mm(f"2F_SteelBalcony_RailGlass{_rtag}", x0 + 70.0, x1 - 70.0, _ry - 6.0, _ry + 6.0, z_2f + 0.065, z_2f + 1.050, gmat, col_2f)
            add_box_mm(f"2F_SteelBalcony_MidPost{_rtag}", -8005.0, -7965.0, _ry - 18.0, _ry + 18.0, z_2f - 0.002, z_2f + 1.050, smat, col_2f)
        # Dual suspended chrome drying rods + stylized hanging garments
        for _ri, _rx in enumerate((-8320.0, -7680.0), 1):
            add_box_mm(f"2F_SteelBalcony_DryDropS_{_ri}", _rx - 9.0, _rx + 9.0, -4260.0, -4242.0, z_2f + 2.165, z_2f + 2.415, rmat, col_2f)
            add_box_mm(f"2F_SteelBalcony_DryDropN_{_ri}", _rx - 9.0, _rx + 9.0, -2660.0, -2642.0, z_2f + 2.165, z_2f + 2.415, rmat, col_2f)
            add_box_mm(f"2F_SteelBalcony_DryRod_{_ri}", _rx - 14.0, _rx + 14.0, -4320.0, -2580.0, z_2f + 2.150, z_2f + 2.178, rmat, col_2f)
        _dry_items = [
            (-8320.0, -4020.0, -3520.0, 1.48, MATS["Bed_Linen"]),
            (-8320.0, -3380.0, -2880.0, 1.56, MATS["Bed_Throw"]),
            (-7680.0, -4060.0, -3600.0, 1.42, MATS["OLO_Cab_White"]),
            (-7680.0, -3420.0, -2940.0, 1.62, MATS["Sofa_Sage_Velvet"]),
        ]
        for _li, (_lx, _ly0, _ly1, _lz0, _lmat) in enumerate(_dry_items, 1):
            add_box_mm(f"2F_SteelBalcony_LaundryHang_{_li}", _lx - 32.0, _lx + 32.0, _ly0, _ly1, z_2f + _lz0, z_2f + 2.120, _lmat, col_2f, r_corner=10.0)
    _build_sw_steel_balcony()

    build_door("2F_Door_ChildRoom",  -1629, -1489, -2523, -1723, z_2f + 0.002, h_2f, 2.20, col_2f)
    build_door("2F_Door_ChildBath",  -3260, -2550, -1650, -1560, z_2f + 0.002, h_2f, 2.20, col_2f, is_toilet_glass=True)
    # Child Bedroom South Wall: Paneled Wall + Flush Invisible Door (隐形门) to Child WIC
    add_box_mm("2F_Door_ChildWIC_Header", -4775, -4155, -2709, -2609, z_2f + 2.500, z_2f + h_2f, MATS["Wall_New"], col_2f)
    add_box_mm("2F_ChildWall_Panel_L", -5916, -4778, -2608, -2592, zf_2f, z_2f + 2.500, MATS["Wall_Panel_Cream"], col_2f)
    add_box_mm("2F_ChildWall_Panel_R", -4152, -3468, -2608, -2592, zf_2f, z_2f + 2.500, MATS["Wall_Panel_Cream"], col_2f)
    for _gi, _gx in enumerate((-5348.0, -4777.0, -4153.0, -3810.0), 1):
        add_box_mm(f"2F_ChildWall_Groove_{_gi}", _gx - 1.5, _gx + 1.5, -2608.0, -2590.0, zf_2f, z_2f + 2.500, MATS["Dark_Bronze_Recess"], col_2f)
    add_box_mm("2F_ChildWall_Soffit", -5916, -3468, -2608, -2592, z_2f + 2.500, z_2f + h_2f, MATS["Wall_New"], col_2f)
    add_box_mm("2F_Door_ChildWIC_RevealT", -4775, -4155, -2634, -2591, z_2f + 2.496, z_2f + 2.500, MATS["Dark_Bronze_Recess"], col_2f)
    add_box_mm("2F_Door_ChildWIC_RevealL", -4775, -4772, -2634, -2591, zf_2f + 0.004, z_2f + 2.496, MATS["Dark_Bronze_Recess"], col_2f)
    add_box_mm("2F_Door_ChildWIC_RevealR", -4158, -4155, -2634, -2591, zf_2f + 0.004, z_2f + 2.496, MATS["Dark_Bronze_Recess"], col_2f)
    add_box_mm("2F_Door_ChildWIC_Leaf", -4772, -4158, -2632, -2592, zf_2f + 0.004, z_2f + 2.496, MATS["Wall_Panel_Cream"], col_2f)
    add_box_mm("2F_Door_ChildWIC_FlushPullN", -4212, -4196, -2593, -2589, z_2f + 0.960, z_2f + 1.180, MATS["Gold_Brass"], col_2f)
    add_box_mm("2F_Door_ChildWIC_FlushPullS", -4212, -4196, -2635, -2631, z_2f + 0.960, z_2f + 1.180, MATS["Gold_Brass"], col_2f)

    # Interior Clear Glass Laundry Entry Door (2F_Door_SW_LaundryEntry, X=-6848..-5916, Y=-2708..-2608)
    add_box_mm("2F_Door_SW_LaundryEntry_Header", -6848, -5916, -2708, -2608, z_2f + 2.500, z_2f + h_2f, MATS["Wall_New"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_TopFrame", -6848, -5916, -2700, -2616, z_2f + 2.465, z_2f + 2.500, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_JambL", -6848, -6818, -2700, -2616, z_2f + 0.005, z_2f + 2.465, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_JambR", -5946, -5916, -2700, -2616, z_2f + 0.005, z_2f + 2.465, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_Mullion", -6045, -6018, -2700, -2616, z_2f + 0.005, z_2f + 2.465, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_SidelightGlass", -6018, -5946, -2664, -2652, z_2f + 0.015, z_2f + 2.465, MATS["Window_Glass"], col_2f)
    _le_x0, _le_x1, _le_y0, _le_y1 = -6816.0, -6047.0, -2676.0, -2640.0
    _le_z0, _le_z1 = z_2f + 0.012, z_2f + 2.462
    add_box_mm("2F_Door_SW_LaundryEntry_Leaf_StileL", _le_x0, _le_x0 + 24.0, _le_y0, _le_y1, _le_z0, _le_z1, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_Leaf_StileR", _le_x1 - 24.0, _le_x1, _le_y0, _le_y1, _le_z0, _le_z1, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_Leaf_BotRail", _le_x0 + 24.0, _le_x1 - 24.0, _le_y0, _le_y1, _le_z0, _le_z0 + 0.024, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_Leaf_TopRail", _le_x0 + 24.0, _le_x1 - 24.0, _le_y0, _le_y1, _le_z1 - 0.024, _le_z1, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_Leaf_Glass", _le_x0 + 24.0, _le_x1 - 24.0, -2664.0, -2652.0, _le_z0 + 0.024, _le_z1 - 0.024, MATS["Window_Glass"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_Leaf_PullN", _le_x1 - 76.0, _le_x1 - 60.0, _le_y1 + 12.0, _le_y1 + 26.0, z_2f + 0.900, z_2f + 1.320, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_Leaf_PullS", _le_x1 - 76.0, _le_x1 - 60.0, _le_y0 - 26.0, _le_y0 - 12.0, z_2f + 0.900, z_2f + 1.320, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_Leaf_BrassN", _le_x1 - 72.0, _le_x1 - 64.0, _le_y1 + 24.0, _le_y1 + 28.0, z_2f + 0.940, z_2f + 1.280, MATS["Gold_Brass"], col_2f)
    add_box_mm("2F_Door_SW_LaundryEntry_Leaf_BrassS", _le_x1 - 72.0, _le_x1 - 64.0, _le_y0 - 28.0, _le_y0 - 24.0, z_2f + 0.940, z_2f + 1.280, MATS["Gold_Brass"], col_2f)
    build_door("2F_Door_MasterBed",   1574,  1714, -2700, -1895, z_2f + 0.002, h_2f, 2.20, col_2f)
    build_door("2F_Door_ParentRoom",  1361,  1501, -1410,  -580, z_2f + 0.002, h_2f, 2.20, col_2f)
    build_door("2F_Door_ParentBath",  1646,  2446,  -490,  -360, z_2f + 0.002, h_2f, 2.20, col_2f, is_toilet_glass=True)
    def build_double_sliding_glass_door(name, x1, x2, y1, y2, z_floor, h_wall, h_door, col):
        """Build center-meeting double-leaf top-hung sliding glass doors between 2F WIC and Master Bath."""
        xa, xb = min(x1, x2) + 2.0, max(x1, x2) - 2.0
        ya, yb = min(y1, y2) + 2.0, max(y1, y2) - 2.0
        xm = 0.5 * (xa + xb)
        ym = 0.5 * (ya + yb)
        z_top = z_floor + h_door
        frame_mat = MATS["Stair_Bronze_Iron"]
        recess_mat = MATS["Dark_Bronze_Recess"]
        glass_mat = MATS["Toilet_Frosted_Silk_Glass"]
        brass_mat = MATS["Gold_Brass"]

        if z_floor + h_wall - z_top > 0.02:
            add_box_mm(f"{name}_Header", xa, xb, ya, yb, z_top, z_floor + h_wall, MATS["Wall_New"], col)

        # Slim bronze side jambs, split top sliding track housing, recessed overhead track slot & flush threshold
        jf = 24.0
        add_box_mm(f"{name}_JambS", xa, xb, ya, ya + jf, z_floor + 0.004, z_top, frame_mat, col)
        add_box_mm(f"{name}_JambN", xa, xb, yb - jf, yb, z_floor + 0.004, z_top, frame_mat, col)
        add_box_mm(f"{name}_TopTrackE", xm + 18.0, xb, ya, yb, z_top - 0.038, z_top, frame_mat, col)
        add_box_mm(f"{name}_TopTrackW", xa, xm - 18.0, ya, yb, z_top - 0.038, z_top, frame_mat, col)
        add_box_mm(f"{name}_TopTrackSlotBack", xm - 18.0, xm + 18.0, ya, yb, z_top - 0.012, z_top, recess_mat, col)
        add_box_mm(f"{name}_FloorTrack", xm - 16.0, xm + 16.0, ya + jf, yb - jf, z_floor, z_floor + 0.006, frame_mat, col)

        # Two symmetrical center-meeting sliding leaves (4 mm center seam)
        st = 20.0
        lz0, lz1 = z_floor + 0.010, z_top - 0.036
        leaves = [
            ("LeafS", ya + jf + 2.0, ym - 2.0, ym - 46.0),
            ("LeafN", ym + 2.0, yb - jf - 2.0, ym + 46.0),
        ]
        for ltag, ly0, ly1, hy in leaves:
            add_box_mm(f"{name}_{ltag}_Stile1", xm - 16.0, xm + 16.0, ly0, ly0 + st, lz0, lz1, frame_mat, col)
            add_box_mm(f"{name}_{ltag}_Stile2", xm - 16.0, xm + 16.0, ly1 - st, ly1, lz0, lz1, frame_mat, col)
            add_box_mm(f"{name}_{ltag}_BotRail", xm - 16.0, xm + 16.0, ly0 + st, ly1 - st, lz0, lz0 + 0.024, frame_mat, col)
            add_box_mm(f"{name}_{ltag}_TopRail", xm - 16.0, xm + 16.0, ly0 + st, ly1 - st, lz1 - 0.024, lz1, frame_mat, col)
            pane_w_m = max(0.15, (ly1 - ly0 - 2.0 * st) * MM)
            pane_h_m = max(0.40, (lz1 - lz0 - 0.048))
            add_uv_side_box_mm(
                f"{name}_{ltag}_Glass", xm - 5.0, xm + 5.0, ly0 + st, ly1 - st, lz0 + 0.024, lz1 - 0.024,
                0.0, pane_w_m / 0.45, 0.0, pane_h_m / 0.90, glass_mat, col
            )
            # Visible top hanger roller carriages engaging the concealed overhead sliding rail
            for rk, ry_c in enumerate((ly0 + 80.0, ly1 - 80.0), 1):
                add_box_mm(f"{name}_{ltag}_Roller{rk}", xm - 11.0, xm + 11.0, ry_c - 18.0, ry_c + 18.0, lz1, z_top - 0.014, frame_mat, col)

            # Paired vertical blackened-bronze pulls on WIC (+X) and Master Bath (-X) faces + brass grip inlay
            add_box_mm(f"{name}_{ltag}_PullE", xm + 20.0, xm + 34.0, hy - 8.0, hy + 8.0, z_floor + 0.90, z_floor + 1.32, frame_mat, col)
            add_box_mm(f"{name}_{ltag}_PullW", xm - 34.0, xm - 20.0, hy - 8.0, hy + 8.0, z_floor + 0.90, z_floor + 1.32, frame_mat, col)
            add_box_mm(f"{name}_{ltag}_PullBrassE", xm + 32.0, xm + 35.0, hy - 3.0, hy + 3.0, z_floor + 0.93, z_floor + 1.29, brass_mat, col)
            add_box_mm(f"{name}_{ltag}_PullBrassW", xm - 35.0, xm - 32.0, hy - 3.0, hy + 3.0, z_floor + 0.93, z_floor + 1.29, brass_mat, col)
            for sgn_i, (sx0, sx1) in enumerate(((xm - 20.0, xm - 14.0), (xm + 14.0, xm + 20.0)), 1):
                for pk, pz in enumerate((z_floor + 0.94, z_floor + 1.28), 1):
                    add_box_mm(f"{name}_{ltag}_Post{sgn_i}_{pk}", sx0, sx1, hy - 5.0, hy + 5.0, pz - 0.005, pz + 0.005, frame_mat, col)

    build_double_sliding_glass_door("2F_Door_WIC_Bath", -610, -450, -4540, -3485, z_2f + 0.002, h_2f, 2.500, col_2f)

    # 2F Furniture & Fixtures (West/SW calibrated to Kujiale 装修图纸.dwg & 全屋定制_CAD)
    def add_cyl_x_mm(name, x0_mm, x1_mm, cy_mm, cz_m, r_mm, mat, col, segs=32):
        """Build a closed horizontal cylinder along X for appliance porthole drums & rotary dials."""
        xa, xb = min(x0_mm, x1_mm) * MM, max(x0_mm, x1_mm) * MM
        cy_m = cy_mm * MM
        r_m = r_mm * MM
        mesh_cx = bpy.data.meshes.new(name)
        bm_cx = bmesh.new()
        ring_a, ring_b = [], []
        for k in range(segs):
            ang = 2.0 * math.pi * k / segs
            py = cy_m + r_m * math.cos(ang)
            pz = cz_m + r_m * math.sin(ang)
            ring_a.append(bm_cx.verts.new((xa, py, pz)))
            ring_b.append(bm_cx.verts.new((xb, py, pz)))
        for k in range(segs):
            kn = (k + 1) % segs
            bm_cx.faces.new([ring_a[k], ring_b[k], ring_b[kn], ring_a[kn]])
        bm_cx.faces.new(list(reversed(ring_a)))
        bm_cx.faces.new(ring_b)
        bmesh.ops.recalc_face_normals(bm_cx, faces=bm_cx.faces[:])
        bm_cx.to_mesh(mesh_cx)
        bm_cx.free()
        obj_cx = bpy.data.objects.new(name, mesh_cx)
        obj_cx.data.materials.append(mat)
        for p in obj_cx.data.polygons:
            p.use_smooth = (abs(p.normal.x) < 0.7)
        link_obj(obj_cx, col)
        return obj_cx

    # 1A. NW Window Alcove: Tatami Platform + Hanging Wardrobe (5086/5088/5091/5093/5095, unified 2.50m datum)
    # Clear walls: West=-8918, East pier/opening=-6868, South=-1420, North=+960
    add_box_mm("2F_ChildTatami_ToeKick_E", -6935.0, -6895.0, -1415.0, 260.0, zf_2f, z_2f + 0.045, MATS["OLO_ToeKick_Black"], col_2f)
    add_box_mm("2F_ChildTatami_Plinth", -8910.0, -6935.0, -1415.0, 955.0, zf_2f, z_2f + 0.045, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_ChildTatami_Base", -8910.0, -6895.0, -1415.0, 955.0, z_2f + 0.045, z_2f + 0.415, MATS["Cabinet_Cream"], col_2f)
    for _td_i, (_dy0, _dy1) in enumerate(((-1395.0, -575.0), (-565.0, 255.0)), 1):
        add_box_mm(f"2F_ChildTatami_Drawer_{_td_i}", -6895.0, -6873.0, _dy0, _dy1, z_2f + 0.050, z_2f + 0.405, MATS["Cabinet_Walnut"], col_2f)
        _dym = 0.5 * (_dy0 + _dy1)
        add_box_mm(f"2F_ChildTatami_DrawerPull_{_td_i}", -6873.0, -6862.0, _dym - 110.0, _dym + 110.0, z_2f + 0.365, z_2f + 0.388, MATS["Stair_Bronze_Iron"], col_2f)

    # Walnut Tatami deck with 6 top-lift hatch seams (2x3 grid per 5095) + window-sill backrest trim
    add_box_mm("2F_ChildTatami_Top", -8910.0, -6873.0, -1415.0, 360.0, z_2f + 0.415, z_2f + 0.440, MATS["Cabinet_Walnut"], col_2f)
    add_box_mm("2F_ChildTatami_HatchSeam_X", -7894.0, -7888.0, -1410.0, 355.0, z_2f + 0.436, z_2f + 0.442, MATS["Cabinet_Charcoal"], col_2f)
    for _hy_i, _hy in enumerate((-823.0, -232.0), 1):
        add_box_mm(f"2F_ChildTatami_HatchSeam_Y{_hy_i}", -8905.0, -6878.0, _hy - 3.0, _hy + 3.0, z_2f + 0.436, z_2f + 0.442, MATS["Cabinet_Charcoal"], col_2f)
    add_box_mm("2F_ChildTatami_RimTrim_W", -8910.0, -8875.0, -1415.0, 360.0, z_2f + 0.440, z_2f + 0.460, MATS["Cabinet_Walnut"], col_2f)
    add_box_mm("2F_ChildTatami_RimTrim_S", -8875.0, -6875.0, -1415.0, -1380.0, z_2f + 0.440, z_2f + 0.460, MATS["Cabinet_Walnut"], col_2f)
    # Woven tatami mattress + 2 backrest cushions + low square tea table + 2 floor cushions
    add_box_mm("2F_ChildTatami_Mat", -8865.0, -6905.0, -1370.0, 340.0, z_2f + 0.440, z_2f + 0.485, MATS["Bed_Linen"], col_2f, r_corner=24.0)
    add_box_mm("2F_ChildTatami_BackCushion_L", -8560.0, -7940.0, 210.0, 345.0, z_2f + 0.485, z_2f + 0.785, MATS["Bed_Throw"], col_2f, r_corner=35.0)
    add_box_mm("2F_ChildTatami_BackCushion_R", -7860.0, -7240.0, 210.0, 345.0, z_2f + 0.485, z_2f + 0.785, MATS["Bed_Linen"], col_2f, r_corner=35.0)
    add_box_mm("2F_ChildTatami_TeaTable_Top", -8120.0, -7640.0, -840.0, -360.0, z_2f + 0.765, z_2f + 0.800, MATS["Cabinet_Walnut"], col_2f, r_corner=18.0)
    for _tl_i, (_lx, _ly) in enumerate(((-8085.0, -805.0), (-7675.0, -805.0), (-8085.0, -395.0), (-7675.0, -395.0)), 1):
        add_box_mm(f"2F_ChildTatami_TeaTable_Leg_{_tl_i}", _lx - 18.0, _lx + 18.0, _ly - 18.0, _ly + 18.0, z_2f + 0.485, z_2f + 0.765, MATS["Cabinet_Walnut"], col_2f)
    add_box_mm("2F_ChildTatami_Zabuton_W", -8600.0, -8180.0, -800.0, -400.0, z_2f + 0.485, z_2f + 0.540, MATS["Bed_Throw"], col_2f, r_corner=32.0)
    add_box_mm("2F_ChildTatami_Zabuton_E", -7580.0, -7160.0, -800.0, -400.0, z_2f + 0.485, z_2f + 0.540, MATS["Bed_Linen"], col_2f, r_corner=32.0)

    # North-Wall Tatami Hanging Wardrobe (X=-8910..-6875, Y=+360..+955, Z=0.440..2.500)
    _tw_z0, _tw_z1 = z_2f + 0.440, z_2f + 2.500
    add_box_mm("2F_ChildTatami_Wardrobe_FillerW", -8910.0, -8840.0, 360.0, 955.0, _tw_z0, _tw_z1, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_Back", -8840.0, -6875.0, 937.0, 955.0, _tw_z0, _tw_z1, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_SideR", -6893.0, -6875.0, 382.0, 937.0, _tw_z0, _tw_z1, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_Bot", -8840.0, -6893.0, 382.0, 937.0, _tw_z0, _tw_z0 + 0.020, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_Top", -8840.0, -6893.0, 382.0, 937.0, _tw_z1 - 0.020, _tw_z1, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_DivL", -8349.0, -8331.0, 385.0, 937.0, _tw_z0 + 0.020, _tw_z1 - 0.020, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_DivM", -7849.0, -7831.0, 405.0, 937.0, z_2f + 1.050, _tw_z1 - 0.020, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_DivR", -7349.0, -7331.0, 382.0, 937.0, _tw_z0 + 0.020, _tw_z1 - 0.020, MATS["Cabinet_Cream"], col_2f)
    # Left & center interior: upper chrome rod, 2x3 shelved cubbies, 2 internal drawer banks above bottom drop-flap
    add_box_mm("2F_ChildTatami_Wardrobe_RodL", -8822.0, -8358.0, 645.0, 670.0, z_2f + 2.340, z_2f + 2.365, MATS["B2_Chrome_Silver"], col_2f)
    for _si, _sz in enumerate((z_2f + 1.050, z_2f + 1.480, z_2f + 1.920, z_2f + 2.260), 1):
        add_box_mm(f"2F_ChildTatami_Wardrobe_Shelf_{_si}", -8331.0, -7349.0, 405.0, 937.0, _sz, _sz + 0.018, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_MidShelfBot", -8840.0, -7349.0, 385.0, 937.0, z_2f + 0.720, z_2f + 0.738, MATS["Cabinet_Cream"], col_2f)
    for _idi, (_ix0, _ix1) in enumerate(((-8832.0, -8354.0), (-8326.0, -7854.0), (-7826.0, -7354.0)), 1):
        add_box_mm(f"2F_ChildTatami_Wardrobe_InDrw_{_idi}", _ix0, _ix1, 415.0, 910.0, z_2f + 0.740, z_2f + 1.045, MATS["Cabinet_Walnut"], col_2f)
    # Bottom drop-down flap door (下翻门 per 5086, clearing bedding/cushions) + 3 upper hinged doors
    add_box_mm("2F_ChildTatami_Wardrobe_FlapDoor", -8838.0, -7342.0, 360.0, 382.0, z_2f + 0.445, z_2f + 0.720, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_FlapPull", -8190.0, -7990.0, 349.0, 360.0, z_2f + 0.692, z_2f + 0.706, MATS["Stair_Bronze_Iron"], col_2f)
    _tw_3doors = [(-8838.0, -8342.0), (-8338.0, -7842.0), (-7838.0, -7342.0)]
    for _di, (_dx0, _dx1) in enumerate(_tw_3doors):
        add_box_mm(f"2F_ChildTatami_Wardrobe_Door_{_di+1}", _dx0, _dx1, 360.0, 382.0, z_2f + 0.724, z_2f + 2.496, MATS["OLO_Cab_White"], col_2f)
        _hx = _dx1 - 26.0 if _di % 2 == 0 else _dx0 + 26.0
        add_box_mm(f"2F_ChildTatami_Wardrobe_Handle_{_di+1}", _hx - 5.0, _hx + 5.0, 349.0, 360.0, z_2f + 0.960, z_2f + 1.520, MATS["Stair_Bronze_Iron"], col_2f)
    # Right Showcase Hanging Bay (-7340..-6875): walnut liner, warm LED, brass rod, hanging garments, bronze-framed glass door
    add_box_mm("2F_ChildTatami_Wardrobe_ShowBack", -7331.0, -6893.0, 922.0, 937.0, _tw_z0 + 0.020, _tw_z1 - 0.020, MATS["Cabinet_Walnut"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_ShowShelf", -7331.0, -6893.0, 395.0, 922.0, z_2f + 2.120, z_2f + 2.140, MATS["Cabinet_Walnut"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_ShowLED", -7320.0, -7306.0, 895.0, 915.0, z_2f + 0.480, z_2f + 2.460, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_RodR", -7325.0, -6895.0, 645.0, 670.0, z_2f + 2.020, z_2f + 2.040, MATS["Gold_Brass"], col_2f)
    for _gi, (_gx0, _gx1, _gz0, _gmat) in enumerate(((-7285.0, -7205.0, 0.980, MATS["Bed_Throw"]), (-7160.0, -7080.0, 1.080, MATS["Bed_Linen"]), (-7035.0, -6955.0, 1.150, MATS["OLO_Cab_Greige"])), 1):
        add_box_mm(f"2F_ChildTatami_Garment_{_gi}", _gx0, _gx1, 520.0, 795.0, z_2f + _gz0, z_2f + 1.980, _gmat, col_2f, r_corner=12.0)
    # Bronze-framed full-height glass door on Right showcase bay (-7338..-6877, Y=360..382, Z=0.445..2.496)
    _gx_a, _gx_b, _gz_a, _gz_b = -7338.0, -6877.0, z_2f + 0.445, z_2f + 2.496
    add_box_mm("2F_ChildTatami_Wardrobe_GlassDoor_StileL", _gx_a, _gx_a + 22.0, 360.0, 382.0, _gz_a, _gz_b, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_GlassDoor_StileR", _gx_b - 22.0, _gx_b, 360.0, 382.0, _gz_a, _gz_b, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_GlassDoor_BotRail", _gx_a + 22.0, _gx_b - 22.0, 360.0, 382.0, _gz_a, _gz_a + 0.022, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_GlassDoor_TopRail", _gx_a + 22.0, _gx_b - 22.0, 360.0, 382.0, _gz_b - 0.022, _gz_b, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_GlassDoor_Pane", _gx_a + 22.0, _gx_b - 22.0, 366.0, 376.0, _gz_a + 0.022, _gz_b - 0.022, MATS["Window_Glass"], col_2f)
    add_box_mm("2F_ChildTatami_Wardrobe_GlassDoor_Handle", _gx_a + 6.0, _gx_a + 16.0, 349.0, 360.0, z_2f + 0.960, z_2f + 1.520, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_ChildTatami_Soffit", -8910.0, -6875.0, 360.0, 955.0, z_2f + 2.500, z_2f + h_2f, MATS["Pure_White_Ceiling"], col_2f)

    # Child Bedroom Sleeping Zone (18.12 m²)
    build_bed("2F_Child_Bed", -5986, -4186, -1740, 260, z_2f, "top", col_2f)
    add_box_mm("2F_Child_Night_L", -6580, -6020, -260, 255, zf_2f, zf_2f + 0.50, MATS["Cabinet_Walnut"], col_2f)
    add_box_mm("2F_Child_Night_R", -4150, -3590, -260, 255, zf_2f, zf_2f + 0.50, MATS["Cabinet_Walnut"], col_2f)

    # New Child Ensuite Bathroom (3.29 m²)
    add_box_mm("2F_ChildBath_Vanity", -3425, -2620, -220, 255, zf_2f, zf_2f + 0.84, MATS["Cabinet_Walnut"], col_2f)
    add_cyl_mm("2F_ChildBath_Basin", -3020, 15, 165, zf_2f + 0.842, zf_2f + 0.94, MATS["Sanitary_White"], col_2f)
    add_box_mm("2F_ChildBath_Mirror", -3380, -2660, 245, 258, zf_2f + 1.05, zf_2f + 2.05, MATS["Mirror_Silver"], col_2f)
    add_box_mm("2F_ChildBath_ShowerCurb", -2560, -1635, -755, -715, zf_2f, zf_2f + 0.05, MATS["Sanitary_White"], col_2f)
    add_box_mm("2F_ChildBath_ShowerGlass", -2560, -2542, -740, 255, zf_2f + 0.05, zf_2f + 2.10, MATS["Window_Glass"], col_2f)
    add_cyl_mm("2F_ChildBath_ShowerHead", -2090, 160, 95, zf_2f + 2.12, zf_2f + 2.15, MATS["Gold_Brass"], col_2f)
    add_box_mm("2F_ChildBath_Toilet", -2260, -1640, -1420, -1040, zf_2f, zf_2f + 0.42, MATS["Sanitary_White"], col_2f, r_corner=60.0)
    add_box_mm("2F_ChildBath_ToiletTank", -1830, -1640, -1420, -1040, zf_2f, zf_2f + 0.78, MATS["Sanitary_White"], col_2f, r_corner=30.0)

    # 1B. Child Walk-In Closet (2.93 m², zero pier clipping, unified 2.50m + ceiling soffits)
    add_box_mm("2F_ChildWIC_ToeKick_S", -5218.0, -3474.0, -4380.0, -3875.0, zf_2f, z_2f + 0.065, MATS["OLO_ToeKick_Black"], col_2f)
    add_box_mm("2F_ChildWIC_Cab_S", -5218.0, -3474.0, -4380.0, -3850.0, z_2f + 0.065, z_2f + 2.500, MATS["Cabinet_Cream"], col_2f)
    _cw_sdw = (-3474.0 - (-5218.0)) / 3.0
    for _si in range(3):
        _sx0 = -5218.0 + _si * _cw_sdw + 1.5
        _sx1 = -5218.0 + (_si + 1) * _cw_sdw - 1.5
        add_box_mm(f"2F_ChildWIC_Door_S{_si+1}", _sx0, _sx1, -3850.0, -3828.0, z_2f + 0.070, z_2f + 2.496, MATS["OLO_Cab_White"], col_2f)
        _shx = _sx1 - 26.0 if _si % 2 == 0 else _sx0 + 26.0
        add_box_mm(f"2F_ChildWIC_Handle_S{_si+1}", _shx - 5.0, _shx + 5.0, -3828.0, -3817.0, z_2f + 0.900, z_2f + 1.480, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_ChildWIC_ToeKick_E", -3975.0, -3474.0, -3825.0, -2714.0, zf_2f, z_2f + 0.065, MATS["OLO_ToeKick_Black"], col_2f)
    add_box_mm("2F_ChildWIC_Cab_E", -4000.0, -3474.0, -3825.0, -2714.0, z_2f + 0.065, z_2f + 2.500, MATS["Cabinet_Cream"], col_2f)
    _cw_edw = (-2714.0 - (-3825.0)) / 2.0
    for _ei in range(2):
        _ey0 = -3825.0 + _ei * _cw_edw + 1.5
        _ey1 = -3825.0 + (_ei + 1) * _cw_edw - 1.5
        add_box_mm(f"2F_ChildWIC_Door_E{_ei+1}", -4022.0, -4000.0, _ey0, _ey1, z_2f + 0.070, z_2f + 2.496, MATS["OLO_Cab_White"], col_2f)
        _ehy = _ey1 - 26.0 if _ei == 0 else _ey0 + 26.0
        add_box_mm(f"2F_ChildWIC_Handle_E{_ei+1}", -4033.0, -4022.0, _ehy - 5.0, _ehy + 5.0, z_2f + 0.900, z_2f + 1.480, MATS["Stair_Bronze_Iron"], col_2f)
    # West split around -4988 pier: South recessed wardrobe (-5218..-4840) + North shallow open shelves (-4982..-4795)
    add_box_mm("2F_ChildWIC_ToeKick_W", -5218.0, -4865.0, -3825.0, -3324.0, zf_2f, z_2f + 0.065, MATS["OLO_ToeKick_Black"], col_2f)
    add_box_mm("2F_ChildWIC_Cab_W", -5218.0, -4840.0, -3825.0, -3324.0, z_2f + 0.065, z_2f + 2.500, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_ChildWIC_Door_W1", -4840.0, -4818.0, -3823.0, -3326.0, z_2f + 0.070, z_2f + 2.496, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_ChildWIC_Handle_W1", -4818.0, -4807.0, -3360.0, -3350.0, z_2f + 0.900, z_2f + 1.480, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_ChildWIC_Cab_WN_Back", -4982.0, -4964.0, -3320.0, -2714.0, zf_2f, z_2f + 2.500, MATS["Shelf_Back_Linen"], col_2f)
    add_box_mm("2F_ChildWIC_Cab_WN_SideS", -4964.0, -4795.0, -3320.0, -3302.0, zf_2f, z_2f + 2.500, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_ChildWIC_Cab_WN_SideN", -4964.0, -4795.0, -2732.0, -2714.0, zf_2f, z_2f + 2.500, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_ChildWIC_Cab_WN_Top", -4964.0, -4795.0, -3302.0, -2732.0, z_2f + 2.480, z_2f + 2.500, MATS["Cabinet_Cream"], col_2f)
    for _wi_s, _wz_s in enumerate((0.460, 0.880, 1.300, 1.720, 2.120), 1):
        add_box_mm(f"2F_ChildWIC_Cab_WN_Shelf_{_wi_s}", -4964.0, -4798.0, -3302.0, -2732.0, z_2f + _wz_s, z_2f + _wz_s + 0.020, MATS["Cabinet_Walnut"], col_2f)
    add_box_mm("2F_ChildWIC_Cab_WN_LED", -4962.0, -4950.0, -3296.0, -2738.0, z_2f + 2.465, z_2f + 2.478, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_ChildWIC_Soffit_S", -5218.0, -3474.0, -4380.0, -3828.0, z_2f + 2.500, z_2f + h_2f, MATS["Pure_White_Ceiling"], col_2f)
    add_box_mm("2F_ChildWIC_Soffit_E", -4022.0, -3474.0, -3825.0, -2714.0, z_2f + 2.500, z_2f + h_2f, MATS["Pure_White_Ceiling"], col_2f)
    add_box_mm("2F_ChildWIC_Soffit_W1", -5218.0, -4818.0, -3825.0, -3324.0, z_2f + 2.500, z_2f + h_2f, MATS["Pure_White_Ceiling"], col_2f)
    add_box_mm("2F_ChildWIC_Soffit_W2", -4982.0, -4795.0, -3320.0, -2714.0, z_2f + 2.500, z_2f + h_2f, MATS["Pure_White_Ceiling"], col_2f)

    # 1C. SW Window Alcove: Stacked Washer + Dryer Tower (#41) + Utility Sink/Cabinets (#66) + South Win Low Cab (#47)
    # Clear walls: West win=-6848, South win=-4490, East pier(N)=-5450 (Y=-3320..-2708), East recess(S)=-5314 (Y=-4386..-3320)
    add_box_mm("2F_SW_Laundry_SideL", -6034.0, -5455.0, -3318.0, -3298.0, zf_2f, z_2f + 2.500, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_SW_Laundry_SideR", -6034.0, -5455.0, -2732.0, -2712.0, zf_2f, z_2f + 2.500, MATS["Cabinet_Cream"], col_2f)
    # Front-load Washer (Z=0.008..0.855, facing West -X, centered at Y=-3015)
    add_box_mm("2F_SW_Laundry_Washer_Base", -6005.0, -5460.0, -3294.0, -2736.0, z_2f + 0.008, z_2f + 0.036, MATS["OLO_ToeKick_Black"], col_2f)
    add_box_mm("2F_SW_Laundry_Washer", -6020.0, -5460.0, -3294.0, -2736.0, z_2f + 0.036, z_2f + 0.852, MATS["Sanitary_White"], col_2f)
    add_cyl_x_mm("2F_SW_Laundry_WasherBezel", -6042.0, -6018.0, -3015.0, z_2f + 0.425, 228.0, MATS["B2_Chrome_Silver"], col_2f, segs=32)
    add_cyl_x_mm("2F_SW_Laundry_WasherDoor", -6048.0, -6024.0, -3015.0, z_2f + 0.425, 212.0, MATS["OLO_Oven_DarkGlass"], col_2f, segs=32)
    add_cyl_x_mm("2F_SW_Laundry_WasherDrum", -6024.0, -5950.0, -3015.0, z_2f + 0.425, 158.0, MATS["Cabinet_Charcoal"], col_2f, segs=28)
    add_box_mm("2F_SW_Laundry_WasherLatch", -6050.0, -6036.0, -2825.0, -2790.0, z_2f + 0.395, z_2f + 0.455, MATS["B2_Chrome_Silver"], col_2f)
    add_box_mm("2F_SW_Laundry_WasherPanel", -6028.0, -6018.0, -3285.0, -2745.0, z_2f + 0.725, z_2f + 0.848, MATS["OLO_Oven_DarkGlass"], col_2f)
    add_cyl_x_mm("2F_SW_Laundry_WasherDialRim", -6036.0, -6026.0, -3015.0, z_2f + 0.788, 28.0, MATS["B2_Chrome_Silver"], col_2f, segs=24)
    add_cyl_x_mm("2F_SW_Laundry_WasherDial", -6044.0, -6034.0, -3015.0, z_2f + 0.788, 22.0, MATS["Cabinet_Charcoal"], col_2f, segs=24)
    add_box_mm("2F_SW_Laundry_WasherDetergent", -6026.0, -6018.0, -3280.0, -3130.0, z_2f + 0.735, z_2f + 0.838, MATS["OLO_Cab_White"], col_2f)
    # Walnut pull-out stacking shelf (Z=0.855..0.892)
    add_box_mm("2F_SW_Laundry_StackShelf", -6035.0, -5455.0, -3298.0, -2732.0, z_2f + 0.855, z_2f + 0.892, MATS["Cabinet_Walnut"], col_2f)
    add_box_mm("2F_SW_Laundry_StackPull", -6044.0, -6034.0, -3085.0, -2945.0, z_2f + 0.862, z_2f + 0.884, MATS["Stair_Bronze_Iron"], col_2f)
    # Stacked Heat-Pump Dryer (Z=0.892..1.740, facing West -X)
    add_box_mm("2F_SW_Laundry_Dryer", -6020.0, -5460.0, -3294.0, -2736.0, z_2f + 0.894, z_2f + 1.738, MATS["Sanitary_White"], col_2f)
    add_cyl_x_mm("2F_SW_Laundry_DryerBezel", -6042.0, -6018.0, -3015.0, z_2f + 1.295, 228.0, MATS["B2_Chrome_Silver"], col_2f, segs=32)
    add_cyl_x_mm("2F_SW_Laundry_DryerDoor", -6048.0, -6024.0, -3015.0, z_2f + 1.295, 212.0, MATS["OLO_Oven_DarkGlass"], col_2f, segs=32)
    add_cyl_x_mm("2F_SW_Laundry_DryerDrum", -6024.0, -5950.0, -3015.0, z_2f + 1.295, 158.0, MATS["Cabinet_Charcoal"], col_2f, segs=28)
    add_box_mm("2F_SW_Laundry_DryerLatch", -6050.0, -6036.0, -2825.0, -2790.0, z_2f + 1.265, z_2f + 1.325, MATS["B2_Chrome_Silver"], col_2f)
    add_box_mm("2F_SW_Laundry_DryerPanel", -6028.0, -6018.0, -3285.0, -2745.0, z_2f + 1.610, z_2f + 1.734, MATS["OLO_Oven_DarkGlass"], col_2f)
    add_cyl_x_mm("2F_SW_Laundry_DryerDialRim", -6036.0, -6026.0, -3015.0, z_2f + 1.672, 28.0, MATS["B2_Chrome_Silver"], col_2f, segs=24)
    add_cyl_x_mm("2F_SW_Laundry_DryerDial", -6044.0, -6034.0, -3015.0, z_2f + 1.672, 22.0, MATS["Cabinet_Charcoal"], col_2f, segs=24)
    add_box_mm("2F_SW_Laundry_DryerCondenser", -6026.0, -6018.0, -3280.0, -3130.0, z_2f + 1.620, z_2f + 1.724, MATS["OLO_Cab_White"], col_2f)
    # Overhead 2-Door Storage Cabinet (Z=1.742..2.500) + Soffit (2.500..2.830)
    add_box_mm("2F_SW_Laundry_UpperCab", -6012.0, -5455.0, -3298.0, -2732.0, z_2f + 1.742, z_2f + 2.500, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_SW_Laundry_UpperDoor_1", -6034.0, -6012.0, -3296.0, -3017.0, z_2f + 1.746, z_2f + 2.496, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_SW_Laundry_UpperDoor_2", -6034.0, -6012.0, -3013.0, -2734.0, z_2f + 1.746, z_2f + 2.496, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_SW_Laundry_UpperPull_1", -6045.0, -6034.0, -3055.0, -3045.0, z_2f + 1.770, z_2f + 2.020, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_SW_Laundry_UpperPull_2", -6045.0, -6034.0, -2985.0, -2975.0, z_2f + 1.770, z_2f + 2.020, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_SW_Laundry_Soffit", -6034.0, -5455.0, -3318.0, -2712.0, z_2f + 2.500, z_2f + h_2f, MATS["Pure_White_Ceiling"], col_2f)

    # East Wall (靠衣柜墙一侧, X=-5905..-5318, Y=-4475..-3320): Full-Height 2.50m Utility/Mop Storage Cabinet (杂物柜, NO SINK)
    add_box_mm("2F_SW_Utility_ToeKick", -5865.0, -5318.0, -4475.0, -3320.0, zf_2f, z_2f + 0.075, MATS["OLO_ToeKick_Black"], col_2f)
    add_box_mm("2F_SW_Utility_BaseCab", -5883.0, -5318.0, -4475.0, -3320.0, z_2f + 0.075, z_2f + 0.850, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_SW_Utility_BaseDoor_1", -5905.0, -5883.0, -4471.0, -3900.0, z_2f + 0.078, z_2f + 0.846, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_SW_Utility_BaseDoor_2", -5905.0, -5883.0, -3896.0, -3324.0, z_2f + 0.078, z_2f + 0.846, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_SW_Utility_BasePull_1", -5916.0, -5905.0, -3945.0, -3935.0, z_2f + 0.620, z_2f + 0.800, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_SW_Utility_BasePull_2", -5916.0, -5905.0, -3865.0, -3855.0, z_2f + 0.620, z_2f + 0.800, MATS["Stair_Bronze_Iron"], col_2f)
    # Mid-height Walnut Open Utility Counter/Niche (0.850..1.480) + detergent bottles + laundry basket
    add_box_mm("2F_SW_Utility_NicheDeck", -5905.0, -5318.0, -4475.0, -3320.0, z_2f + 0.850, z_2f + 0.880, MATS["Cabinet_Walnut"], col_2f)
    add_box_mm("2F_SW_Utility_NicheBack", -5334.0, -5318.0, -4475.0, -3320.0, z_2f + 0.880, z_2f + 1.480, MATS["Cabinet_Walnut"], col_2f)
    add_box_mm("2F_SW_Utility_NicheSideS", -5905.0, -5334.0, -4475.0, -4457.0, z_2f + 0.880, z_2f + 1.480, MATS["Cabinet_Walnut"], col_2f)
    add_box_mm("2F_SW_Utility_NicheSideN", -5905.0, -5334.0, -3338.0, -3320.0, z_2f + 0.880, z_2f + 1.480, MATS["Cabinet_Walnut"], col_2f)
    add_box_mm("2F_SW_Utility_NicheLED", -5370.0, -5348.0, -4445.0, -3350.0, z_2f + 1.472, z_2f + 1.480, MATS["Warm_LED_Glow"], col_2f)
    add_cyl_mm("2F_SW_Utility_Bottle_1", -5540.0, -4120.0, 40.0, z_2f + 0.880, z_2f + 1.110, MATS["Sanitary_White"], col_2f, segs=20)
    add_cyl_mm("2F_SW_Utility_Bottle_2", -5540.0, -3990.0, 35.0, z_2f + 0.880, z_2f + 1.070, MATS["Bed_Throw"], col_2f, segs=20)
    add_box_mm("2F_SW_Utility_Basket", -5760.0, -5420.0, -3760.0, -3420.0, z_2f + 0.880, z_2f + 1.120, MATS["Bed_Linen"], col_2f, r_corner=16.0)
    # Upper Enclosed Storage Cabinet (1.480..2.500) + Soffit (2.500..2.830)
    add_box_mm("2F_SW_Utility_WallCab", -5883.0, -5318.0, -4475.0, -3320.0, z_2f + 1.480, z_2f + 2.500, MATS["Cabinet_Cream"], col_2f)
    add_box_mm("2F_SW_Utility_WallDoor_1", -5905.0, -5883.0, -4471.0, -3900.0, z_2f + 1.484, z_2f + 2.496, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_SW_Utility_WallDoor_2", -5905.0, -5883.0, -3896.0, -3324.0, z_2f + 1.484, z_2f + 2.496, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_SW_Utility_WallPull_1", -5916.0, -5905.0, -3945.0, -3935.0, z_2f + 1.540, z_2f + 1.880, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_SW_Utility_WallPull_2", -5916.0, -5905.0, -3865.0, -3855.0, z_2f + 1.540, z_2f + 1.880, MATS["Stair_Bronze_Iron"], col_2f)
    add_box_mm("2F_SW_Utility_Soffit", -5905.0, -5318.0, -4475.0, -3320.0, z_2f + 2.500, z_2f + h_2f, MATS["Pure_White_Ceiling"], col_2f)

    # South Exterior Floor-to-Ceiling Glass Side (朝外玻璃那一侧, X=-6835..-5925, Y=-4480..-3910): Laundry Sink Vanity (洗手池)
    add_box_mm("2F_SW_WinCab_ToeKick", -6835.0, -5925.0, -4480.0, -3960.0, zf_2f, z_2f + 0.075, MATS["OLO_ToeKick_Black"], col_2f)
    add_box_mm("2F_SW_WinCab_Body", -6835.0, -5925.0, -4480.0, -3932.0, z_2f + 0.075, z_2f + 0.850, MATS["Cabinet_Cream"], col_2f)
    _wc_dw = (-5925.0 - (-6835.0)) / 3.0
    for _wi in range(3):
        _wx0 = -6835.0 + _wi * _wc_dw + 1.5
        _wx1 = -6835.0 + (_wi + 1) * _wc_dw - 1.5
        _wxm = 0.5 * (_wx0 + _wx1)
        add_box_mm(f"2F_SW_WinCab_Door_{_wi+1}", _wx0, _wx1, -3932.0, -3910.0, z_2f + 0.078, z_2f + 0.846, MATS["OLO_Cab_White"], col_2f)
        add_box_mm(f"2F_SW_WinCab_Pull_{_wi+1}", _wxm - 60.0, _wxm + 60.0, -3910.0, -3899.0, z_2f + 0.785, z_2f + 0.800, MATS["Stair_Bronze_Iron"], col_2f)
    # 4 non-overlapping Quartz countertop strips (Z=0.850..0.880) around true recessed ceramic basin (X=-6610..-6150, Y=-4390..-3995)
    add_box_mm("2F_SW_WinCab_Top_W", -6835.0, -6610.0, -4480.0, -3910.0, z_2f + 0.850, z_2f + 0.880, MATS["Sanitary_White"], col_2f)
    add_box_mm("2F_SW_WinCab_Top_E", -6150.0, -5925.0, -4480.0, -3910.0, z_2f + 0.850, z_2f + 0.880, MATS["Sanitary_White"], col_2f)
    add_box_mm("2F_SW_WinCab_Top_S", -6610.0, -6150.0, -4480.0, -4390.0, z_2f + 0.850, z_2f + 0.880, MATS["Sanitary_White"], col_2f)
    add_box_mm("2F_SW_WinCab_Top_N", -6610.0, -6150.0, -3995.0, -3910.0, z_2f + 0.850, z_2f + 0.880, MATS["Sanitary_White"], col_2f)
    # Recessed Ceramic Sink Bowl + Chrome Drain + Outward-Facing Brass Faucet (South glass side)
    add_box_mm("2F_SW_WinCab_BasinBot", -6610.0, -6150.0, -4390.0, -3995.0, z_2f + 0.720, z_2f + 0.735, MATS["Sanitary_White"], col_2f)
    add_box_mm("2F_SW_WinCab_BasinWallW", -6610.0, -6595.0, -4390.0, -3995.0, z_2f + 0.735, z_2f + 0.878, MATS["Sanitary_White"], col_2f)
    add_box_mm("2F_SW_WinCab_BasinWallE", -6165.0, -6150.0, -4390.0, -3995.0, z_2f + 0.735, z_2f + 0.878, MATS["Sanitary_White"], col_2f)
    add_box_mm("2F_SW_WinCab_BasinWallS", -6595.0, -6165.0, -4390.0, -4375.0, z_2f + 0.735, z_2f + 0.878, MATS["Sanitary_White"], col_2f)
    add_box_mm("2F_SW_WinCab_BasinWallN", -6595.0, -6165.0, -4010.0, -3995.0, z_2f + 0.735, z_2f + 0.878, MATS["Sanitary_White"], col_2f)
    add_cyl_mm("2F_SW_WinCab_Drain", -6380.0, -4190.0, 26.0, z_2f + 0.734, z_2f + 0.742, MATS["B2_Chrome_Silver"], col_2f, segs=24)
    add_cyl_mm("2F_SW_WinCab_Faucet", -6380.0, -4435.0, 14.0, z_2f + 0.880, z_2f + 1.180, MATS["Gold_Brass"], col_2f, segs=20)
    add_box_mm("2F_SW_WinCab_FaucetSpout", -6390.0, -6370.0, -4435.0, -4300.0, z_2f + 1.165, z_2f + 1.185, MATS["Gold_Brass"], col_2f)
    add_cyl_mm("2F_SW_WinCab_FaucetNozzle", -6380.0, -4305.0, 11.0, z_2f + 1.140, z_2f + 1.170, MATS["Gold_Brass"], col_2f, segs=16)
    add_box_mm("2F_SW_WinCab_FaucetLever", -6352.0, -6320.0, -4450.0, -4420.0, z_2f + 0.960, z_2f + 0.978, MATS["Gold_Brass"], col_2f)

    # Updated Master Bathroom (7.24 m², wet/dry partition)
    pts_tub = []
    for k in range(28):
        a = 2.0 * math.pi * k / 28.0
        pts_tub.append((-2653.0 + 370.0*math.cos(a), -4555.0 + 735.0*math.sin(a)))
    add_prism("2F_MasterBath_Tub", pts_tub, zf_2f, zf_2f + 0.58, MATS["Sanitary_White"], col_2f)
    add_box_mm("2F_MasterBath_ShowerGlass", -1595, -1575, -3760, -3411, zf_2f, zf_2f + 2.15, MATS["Window_Glass"], col_2f)
    add_cyl_mm("2F_MasterBath_ShowerHead", -2530, -2960, 100, zf_2f + 2.12, zf_2f + 2.15, MATS["Gold_Brass"], col_2f)
    add_box_mm("2F_MasterBath_Vanity", -1495, -615, -3360, -2850, zf_2f, zf_2f + 0.84, MATS["Cabinet_Walnut"], col_2f)
    add_cyl_mm("2F_MasterBath_Basin1", -1055, -3100, 180, zf_2f + 0.842, zf_2f + 0.94, MATS["Sanitary_White"], col_2f)
    add_box_mm("2F_MasterBath_Mirror", -1460, -650, -2862, -2850, zf_2f + 1.05, zf_2f + 2.05, MATS["Mirror_Silver"], col_2f)
    add_box_mm("2F_MasterBath_Toilet", -1320, -880, -5250, -4560, zf_2f, zf_2f + 0.42, MATS["Sanitary_White"], col_2f, r_corner=60.0)
    add_box_mm("2F_MasterBath_ToiletTank", -1320, -880, -5250, -5050, zf_2f, zf_2f + 0.78, MATS["Sanitary_White"], col_2f, r_corner=30.0)
    # W.I.C
    # add_box_mm("2F_WIC_Wardrobe_N", -440, 1355, -3350, -2810, zf_2f, z_2f + 2.35, MATS["Cabinet_Walnut"], col_2f)  # replaced by f2_wic_spec (rev. 2026-10-28)
    # add_box_mm("2F_WIC_Wardrobe_S", -440, 1355, -5240, -4700, zf_2f, z_2f + 2.35, MATS["Cabinet_Walnut"], col_2f)  # replaced by f2_wic_spec (rev. 2026-10-28)
    # add_box_mm("2F_WIC_Wardrobe_E",  820, 1355, -4695, -3355, zf_2f, z_2f + 2.35, MATS["Cabinet_Walnut"], col_2f)  # replaced by f2_wic_spec (rev. 2026-10-28)
    # 2F master walk-in closet v2: doorway from the bed + two facing wardrobe runs (rev. 2026-10-28, generated by f2_wic_spec.py)
    add_box_mm("2F_WIC_Partition_S", 1360.0, 1500.0, -5280.0, -5260.0, z_2f + 0.0000, z_2f + 2.8300, MATS["Wall_New"], col_2f)
    add_box_mm("2F_WIC_Partition_N2", 1360.0, 1500.0, -2850.0, -2846.0, z_2f + 0.0000, z_2f + 2.8300, MATS["Wall_New"], col_2f)
    def build_2f_wic_n_optical_wardrobe():
        # 2F Master Walk-In Closet North Run (swapped with South):
        # 4-door Pearlescent Optical Wood Shadow Wardrobe (`2500 mm` unified height + upper bulkhead `2.500..2.830`, facing South `-Y`)
        x0, x1 = -450.0, 1220.0
        yb_n, yf_n = -2850.0, -3450.0
        yc_f = -3428.0
        z0 = z_2f
        h_n = 2.500

        # Ceiling soffit/bulkhead above the 2500 mm North wardrobe and its adjacent 见光板 (z: 2.500..2.830)
        add_box_mm("2F_WIC_N_Bulkhead_Main", x0, x1, yf_n, yb_n, z0 + h_n, z0 + 2.830, MATS["Wall_New"], col_2f)
        add_box_mm("2F_WIC_N_Bulkhead_Pass", 1220.0, 1500.0, yf_n, yc_f, z0 + h_n, z0 + 2.830, MATS["Wall_New"], col_2f)

        # Hollow carcass (bottom plinth + base, top board, cheeks, center partition)
        add_box_mm("2F_WIC_N_BackWall", x0, x1, yb_n - 20.0, yb_n, z0, z0 + h_n, MATS["Shelf_Back_Linen"], col_2f)
        add_box_mm("2F_WIC_N_CheekL", x0, x0 + 18.0, yc_f, yb_n - 20.0, z0, z0 + h_n, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_WIC_N_CheekR", x1 - 18.0, x1, yc_f, yb_n - 20.0, z0, z0 + h_n, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_WIC_N_Plinth", x0 + 18.0, x1 - 18.0, yc_f + 18.0, yb_n - 20.0, z0, z0 + 0.045, MATS["OLO_ToeKick_Black"], col_2f)
        add_box_mm("2F_WIC_N_Bottom", x0 + 18.0, x1 - 18.0, yc_f, yb_n - 20.0, z0 + 0.045, z0 + 0.065, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_WIC_N_Top", x0, x1, yc_f, yb_n - 20.0, z0 + 2.475, z0 + h_n, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_WIC_N_PartCenter", 376.0, 394.0, yc_f, yb_n - 20.0, z0 + 0.065, z0 + 2.475, MATS["White_Shadow_Wood_Base"], col_2f)

        # Left Internal Module (-432..376): top shelf, hanging rod, shelf 0.89, 逐影系列首饰盒, 逐影系列裤抽, lower bay
        lx1, lx2 = -432.0, 376.0
        for s_i, sz_m in enumerate([0.890, 2.020], 1):
            add_box_mm(f"2F_WIC_N_ModL_Shelf_{s_i}", lx1, lx2, yc_f + 28.0, yb_n - 20.0, z0 + sz_m, z0 + sz_m + 0.020, MATS["White_Shadow_Wood_Base"], col_2f)
            add_box_mm(f"2F_WIC_N_ModL_LED_{s_i}", lx1 + 12.0, lx2 - 12.0, yb_n - 42.0, yb_n - 24.0, z0 + sz_m - 0.008, z0 + sz_m, MATS["Warm_LED_Glow"], col_2f)
        add_box_mm("2F_WIC_N_ModL_TopLED", lx1 + 12.0, lx2 - 12.0, yb_n - 42.0, yb_n - 24.0, z0 + 2.467, z0 + 2.475, MATS["Warm_LED_Glow"], col_2f)
        # Hanging rod under 2.020 shelf
        add_box_mm("2F_WIC_N_ModL_RodDropL", lx1 + 36.0, lx1 + 48.0, -3150.0, -3138.0, z0 + 1.905, z0 + 2.020, MATS["Gold_Brass"], col_2f)
        add_box_mm("2F_WIC_N_ModL_RodDropR", lx2 - 48.0, lx2 - 36.0, -3150.0, -3138.0, z0 + 1.905, z0 + 2.020, MATS["Gold_Brass"], col_2f)
        add_box_mm("2F_WIC_N_ModL_Rod", lx1 + 36.0, lx2 - 36.0, -3153.0, -3135.0, z0 + 1.895, z0 + 1.915, MATS["Gold_Brass"], col_2f)
        # 逐影系列首饰盒 (0.795..0.885)
        add_box_mm("2F_WIC_N_JewelryBox_Frame", lx1 + 8.0, lx2 - 8.0, yc_f + 24.0, yb_n - 28.0, z0 + 0.795, z0 + 0.885, MATS["Stair_Bronze_Iron"], col_2f)
        add_box_mm("2F_WIC_N_JewelryBox_Glass", lx1 + 14.0, lx2 - 14.0, yc_f + 32.0, yb_n - 36.0, z0 + 0.880, z0 + 0.888, MATS["Window_Glass"], col_2f)
        for dv_x in (-230.0, -28.0, 174.0):
            add_box_mm(f"2F_WIC_N_JewelryDiv_{int(dv_x)}", dv_x - 4.0, dv_x + 4.0, yc_f + 32.0, yb_n - 36.0, z0 + 0.805, z0 + 0.878, MATS["Gold_Brass"], col_2f)
        # 逐影系列裤抽 (0.700..0.790) with parallel brass trouser bars
        add_box_mm("2F_WIC_N_TrouserFrame", lx1 + 8.0, lx2 - 8.0, yc_f + 24.0, yb_n - 28.0, z0 + 0.700, z0 + 0.788, MATS["Stair_Bronze_Iron"], col_2f)
        for t_i in range(6):
            tx = lx1 + 65.0 + t_i * 120.0
            add_box_mm(f"2F_WIC_N_TrouserRod_{t_i+1}", tx - 5.0, tx + 5.0, yc_f + 38.0, yb_n - 40.0, z0 + 0.750, z0 + 0.770, MATS["Gold_Brass"], col_2f)

        # Right Internal Module (394..1202): 4 open upper compartments + slim accessory strip + lower 2-door mini cabinet
        rx1, rx2 = 394.0, 1202.0
        for r_i, rz_m in enumerate([0.890, 1.260, 1.640, 2.020], 1):
            add_box_mm(f"2F_WIC_N_ModR_Shelf_{r_i}", rx1, rx2, yc_f + 28.0, yb_n - 20.0, z0 + rz_m, z0 + rz_m + 0.020, MATS["White_Shadow_Wood_Base"], col_2f)
            add_box_mm(f"2F_WIC_N_ModR_LED_{r_i}", rx1 + 12.0, rx2 - 12.0, yb_n - 42.0, yb_n - 24.0, z0 + rz_m - 0.008, z0 + rz_m, MATS["Warm_LED_Glow"], col_2f)
        add_box_mm("2F_WIC_N_ModR_TopLED", rx1 + 12.0, rx2 - 12.0, yb_n - 42.0, yb_n - 24.0, z0 + 2.467, z0 + 2.475, MATS["Warm_LED_Glow"], col_2f)
        add_box_mm("2F_WIC_N_ModR_SlimShelf", rx1 + 6.0, rx2 - 6.0, yc_f + 26.0, yb_n - 24.0, z0 + 0.820, z0 + 0.840, MATS["White_Shadow_Wood_Base"], col_2f)
        # Lower 2-door internal mini cabinet (0.065..0.798, two round brass knobs facing -Y)
        add_box_mm("2F_WIC_N_ModR_MiniCabShelf", rx1, rx2, yc_f + 24.0, yb_n - 20.0, z0 + 0.785, z0 + 0.805, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_WIC_N_ModR_MiniDoorL", rx1 + 2.0, 796.0, yc_f + 24.0, yc_f + 44.0, z0 + 0.068, z0 + 0.782, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_WIC_N_ModR_MiniDoorR", 800.0, rx2 - 2.0, yc_f + 24.0, yc_f + 44.0, z0 + 0.068, z0 + 0.782, MATS["White_Shadow_Wood_Base"], col_2f)
        for kn_i, kn_x in enumerate((764.0, 832.0), 1):
            add_cyl_mm(f"2F_WIC_N_ModR_MiniKnob_{kn_i}", kn_x, yc_f + 20.0, 12.0, z0 + 0.715, z0 + 0.735, MATS["Gold_Brass"], col_2f, segs=16)

        # Exterior 4 Full-Height Pearlescent Optical Wood Shadow Doors (2500 mm, aspect-preserving seamless 0.50x0.75m tile)
        s_doors = [(-448.5, -34.0, 0.00), (-31.0, 383.5, 0.37), (386.5, 801.0, 0.71), (804.0, 1218.5, 0.19)]
        s_handle_xs = (-98.0, 16.0, 737.0, 851.0)
        for d_i, (dx1, dx2, u_off) in enumerate(s_doors, 1):
            w_m = abs(dx2 - dx1) * MM
            h_door_m = 2.482
            add_uv_front_box_mm(f"2F_WIC_N_Door_{d_i}", dx1, dx2, yf_n, yc_f, z0 + 0.010, z0 + 2.492, u_off, u_off + w_m / 0.50, 0.0, h_door_m / 0.75, MATS["Optical_Wood_Shadow_WIC"], col_2f)
            # Paired 48x48 mm brushed-brass square inset handles at waist height (1.115..1.163 m)
            hx1 = s_handle_xs[d_i - 1]
            hx2 = hx1 + 48.0
            hz0, hz1 = z0 + 1.115, z0 + 1.163
            add_box_mm(f"2F_WIC_N_Handle_{d_i}_Rim", hx1, hx2, yf_n - 3.0, yf_n + 2.0, hz0, hz1, MATS["Gold_Brass"], col_2f)
            add_box_mm(f"2F_WIC_N_Handle_{d_i}_Inlay", hx1 + 5.0, hx2 - 5.0, yf_n - 4.0, yf_n - 2.0, hz0 + 0.005, hz1 - 0.005, MATS["Dark_Bronze_Recess"], col_2f)
            add_box_mm(f"2F_WIC_N_Handle_{d_i}_Core", hx1 + 10.0, hx2 - 10.0, yf_n - 5.0, yf_n - 3.0, hz0 + 0.010, hz1 - 0.010, MATS["Optical_Wood_Shadow_WIC"], col_2f)

    build_2f_wic_n_optical_wardrobe()

    def build_2f_wic_s_mirror_wardrobe():
        # 2F Master Walk-In Closet South Run (swapped with North): 3-Door Tucson Semi-Transparent Mirror-Glass Wardrobe (unified 2.50m + bulkhead, x: -450..1220, y: -5260..-4660, facing North +Y)
        yb_s, yf_s = -5260.0, -4660.0
        z0 = z_2f
        h_s = 2.500

        # Ceiling soffit/bulkhead above 2500mm South wardrobe (z: 2.500..2.830)
        add_box_mm("2F_WIC_S_Bulkhead_Main", -450.0, 1220.0, yb_s, yf_s, z0 + h_s, z0 + h_2f, MATS["Wall_New"], col_2f)

        # Hollow warm-champagne interior carcass (2 internal partitions -> 3 equal CAD bays)
        add_box_mm("2F_WIC_S_BackWall", -450.0, 1220.0, yb_s, yb_s + 20.0, z0, z0 + h_s, MATS["Shelf_Back_Linen"], col_2f)
        add_box_mm("2F_WIC_S_CheekL", -450.0, -432.0, yb_s + 20.0, yf_s - 22.0, z0, z0 + h_s, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_WIC_S_CheekR", 1202.0, 1220.0, yb_s + 20.0, yf_s - 22.0, z0, z0 + h_s, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_WIC_S_Plinth", -432.0, 1202.0, yb_s + 20.0, yf_s - 42.0, z0, z0 + 0.064, MATS["OLO_ToeKick_Black"], col_2f)
        add_box_mm("2F_WIC_S_Bottom", -432.0, 1202.0, yb_s + 20.0, yf_s - 22.0, z0 + 0.064, z0 + 0.084, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_WIC_S_HeaderBand", -432.0, 1202.0, yb_s + 20.0, yf_s - 22.0, z0 + 2.436, z0 + 2.456, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_WIC_S_Top", -450.0, 1220.0, yb_s + 20.0, yf_s - 22.0, z0 + 2.456, z0 + h_s, MATS["White_Shadow_Wood_Base"], col_2f)
        for p_idx, (px1, px2) in enumerate([(98.0, 116.0), (654.0, 672.0)], 1):
            add_box_mm(f"2F_WIC_S_Part_{p_idx}", px1, px2, yb_s + 20.0, yf_s - 22.0, z0 + 0.084, z0 + 2.436, MATS["White_Shadow_Wood_Base"], col_2f)

        # 3 Exact CAD Bays: (Left: -432..98, Middle: 116..654, Right: 672..1202)
        cad_bays = [
            (1, -432.0, 98.0,   2.010, True),   # Left bay: upper shelf 2.010 + hanging + 2 drawers + lower bay
            (2,  116.0, 654.0,  2.080, True),   # Middle bay: HIGH upper shelf 2.080 + long coat hanging + 2 drawers + lower bay
            (3,  672.0, 1202.0, 2.010, False),  # Right bay: upper shelf 2.010 + hanging + mid shelf 0.802 + 2 stacked open trays (抽盒)
        ]
        for b_i, bx1, bx2, z_upper, has_drawers in cad_bays:
            # Upper shelf + under-shelf warm LED + top warm LED + corner vertical LEDs
            add_box_mm(f"2F_WIC_S_Bay{b_i}_UpperShelf", bx1, bx2, yb_s + 20.0, yf_s - 48.0, z0 + z_upper, z0 + z_upper + 0.022, MATS["White_Shadow_Wood_Base"], col_2f)
            add_box_mm(f"2F_WIC_S_Bay{b_i}_UpperLED", bx1 + 10.0, bx2 - 10.0, yb_s + 24.0, yb_s + 42.0, z0 + z_upper - 0.010, z0 + z_upper, MATS["Warm_LED_Glow"], col_2f)
            add_box_mm(f"2F_WIC_S_Bay{b_i}_TopLED", bx1 + 10.0, bx2 - 10.0, yb_s + 24.0, yb_s + 42.0, z0 + 2.426, z0 + 2.436, MATS["Warm_LED_Glow"], col_2f)
            add_box_mm(f"2F_WIC_S_Bay{b_i}_VertLED_L", bx1 + 2.0, bx1 + 10.0, yb_s + 20.0, yb_s + 32.0, z0 + 0.09, z0 + 2.42, MATS["Warm_LED_Glow"], col_2f)
            add_box_mm(f"2F_WIC_S_Bay{b_i}_VertLED_R", bx2 - 10.0, bx2 - 2.0, yb_s + 20.0, yb_s + 32.0, z0 + 0.09, z0 + 2.42, MATS["Warm_LED_Glow"], col_2f)

            # U-drop brass hanging rail right below upper shelf
            z_rod = z_upper - 0.130
            add_box_mm(f"2F_WIC_S_Bay{b_i}_RodDropL", bx1 + 36.0, bx1 + 48.0, -4975.0, -4963.0, z0 + z_rod, z0 + z_upper, MATS["Gold_Brass"], col_2f)
            add_box_mm(f"2F_WIC_S_Bay{b_i}_RodDropR", bx2 - 48.0, bx2 - 36.0, -4975.0, -4963.0, z0 + z_rod, z0 + z_upper, MATS["Gold_Brass"], col_2f)
            add_box_mm(f"2F_WIC_S_Bay{b_i}_Rail", bx1 + 36.0, bx2 - 36.0, -4978.0, -4960.0, z0 + z_rod - 0.008, z0 + z_rod + 0.012, MATS["Gold_Brass"], col_2f)

            # Mid shelf above drawers / trays
            z_mid = 0.825 if has_drawers else 0.802
            add_box_mm(f"2F_WIC_S_Bay{b_i}_MidShelf", bx1, bx2, yb_s + 20.0, yf_s - 48.0, z0 + z_mid, z0 + z_mid + 0.022, MATS["White_Shadow_Wood_Base"], col_2f)
            add_box_mm(f"2F_WIC_S_Bay{b_i}_MidLED", bx1 + 10.0, bx2 - 10.0, yb_s + 24.0, yb_s + 42.0, z0 + z_mid - 0.008, z0 + z_mid, MATS["Warm_LED_Glow"], col_2f)

            if has_drawers:
                # 2 Stacked Pull-Out Drawers (CAD red drawer boxes) + lower divider shelf
                for d_j, (dz_a, dz_b) in enumerate([(0.635, 0.815), (0.425, 0.615)], 1):
                    add_box_mm(f"2F_WIC_S_Bay{b_i}_Drawer_{d_j}", bx1 + 4.0, bx2 - 4.0, yb_s + 26.0, yf_s - 48.0, z0 + dz_a, z0 + dz_b, MATS["White_Shadow_Wood_Base"], col_2f)
                    add_box_mm(f"2F_WIC_S_Bay{b_i}_DrawerGrip_{d_j}", bx1 + 24.0, bx2 - 24.0, yf_s - 50.0, yf_s - 44.0, z0 + dz_b - 0.018, z0 + dz_b - 0.004, MATS["Dark_Bronze_Recess"], col_2f)
                add_box_mm(f"2F_WIC_S_Bay{b_i}_LowShelf", bx1, bx2, yb_s + 20.0, yf_s - 48.0, z0 + 0.402, z0 + 0.422, MATS["White_Shadow_Wood_Base"], col_2f)
            else:
                # Right Bay: 2 Stacked Open Pull-Out Trays (抽盒 / 抽盒)
                for t_j, tz_0 in enumerate([0.425, 0.105], 1):
                    add_box_mm(f"2F_WIC_S_Bay{b_i}_TrayBase_{t_j}", bx1 + 4.0, bx2 - 4.0, yb_s + 24.0, yf_s - 52.0, z0 + tz_0, z0 + tz_0 + 0.018, MATS["White_Shadow_Wood_Base"], col_2f)
                    add_box_mm(f"2F_WIC_S_Bay{b_i}_TrayFront_{t_j}", bx1 + 4.0, bx2 - 4.0, yf_s - 68.0, yf_s - 52.0, z0 + tz_0 + 0.018, z0 + tz_0 + 0.068, MATS["White_Shadow_Wood_Base"], col_2f)
                    add_box_mm(f"2F_WIC_S_Bay{b_i}_TrayTrim_{t_j}", bx1 + 12.0, bx2 - 12.0, yf_s - 54.0, yf_s - 50.0, z0 + tz_0 + 0.062, z0 + tz_0 + 0.068, MATS["Gold_Brass"], col_2f)

        # 3 Full-height slim dark-bronze-framed Tucson semi-transparent mirror-glass doors (严格三个柜门! facing +Y)
        door_spans = [
            (-448.5, 106.0, True),   # Door 1: pull on right stile
            (109.0,  662.0, False),  # Door 2: pull on left stile
            (665.0,  1218.5, False), # Door 3: pull on left stile
        ]
        for d_i, (dx1, dx2, pull_right) in enumerate(door_spans, 1):
            dz0, dz1 = z0 + 0.012, z0 + 2.492
            add_box_mm(f"2F_WIC_S_Door_{d_i}_FrameL", dx1, dx1 + 14.0, yf_s - 22.0, yf_s, dz0, dz1, MATS["Stair_Bronze_Iron"], col_2f)
            add_box_mm(f"2F_WIC_S_Door_{d_i}_FrameR", dx2 - 14.0, dx2, yf_s - 22.0, yf_s, dz0, dz1, MATS["Stair_Bronze_Iron"], col_2f)
            add_box_mm(f"2F_WIC_S_Door_{d_i}_FrameB", dx1 + 14.0, dx2 - 14.0, yf_s - 22.0, yf_s, dz0, dz0 + 0.014, MATS["Stair_Bronze_Iron"], col_2f)
            add_box_mm(f"2F_WIC_S_Door_{d_i}_FrameT", dx1 + 14.0, dx2 - 14.0, yf_s - 22.0, yf_s, dz1 - 0.014, dz1, MATS["Stair_Bronze_Iron"], col_2f)
            add_box_mm(f"2F_WIC_S_Door_{d_i}_MirrorGlass", dx1 + 14.0, dx2 - 14.0, yf_s - 16.0, yf_s - 6.0, dz0 + 0.014, dz1 - 0.014, MATS["Tucson_Mirror_Glass"], col_2f)
            hx1 = (dx2 - 14.0) if pull_right else dx1
            hx2 = dx2 if pull_right else (dx1 + 14.0)
            add_box_mm(f"2F_WIC_S_Door_{d_i}_Pull", hx1, hx2, yf_s, yf_s + 10.0, z0 + 1.050, z0 + 1.150, MATS["Stair_Bronze_Iron"], col_2f)

    build_2f_wic_s_mirror_wardrobe()
    add_box_mm("2F_WIC_DispS_Bulkhead", 1220.0, 1500.0, -5260.0, -4660.0, z_2f + 2.5000, z_2f + h_2f, MATS["Wall_New"], col_2f)
    add_box_mm("2F_WIC_DispS_Back", 1220.0, 1240.0, -5260.0, -4682.0, z_2f + 0.0000, z_2f + 2.5000, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_WIC_DispS_SideWall", 1240.0, 1500.0, -5260.0, -5240.0, z_2f + 0.0000, z_2f + 2.5000, MATS["OLO_Cab_White"], col_2f)
    # 见光板: Exposed end panel matching South 3-door mirror wardrobe (2500 mm, facing +Y)
    add_box_mm("2F_WIC_DispS_PassPanel", 1220.0, 1500.0, -4682.0, -4660.0, z_2f + 0.5840, z_2f + 2.5000, MATS["Wardrobe_WaveGrain"], col_2f)
    add_box_mm("2F_WIC_DispS_PassMirror", 1220.0, 1500.0, -4682.0, -4660.0, z_2f + 0.0000, z_2f + 0.5800, MATS["Mirror_Bronze"], col_2f)
    add_box_mm("2F_WIC_DispS_PassMirrorTop", 1220.0, 1500.0, -4682.0, -4660.0, z_2f + 0.5720, z_2f + 0.5800, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispS_PassMullion", 1486.0, 1500.0, -4682.0, -4660.0, z_2f + 0.0000, z_2f + 0.5800, MATS["RoseGold_Metal"], col_2f)
    for g_idx, gz in enumerate([0.7196, 0.8602, 1.0009, 1.1415, 1.2821, 1.4228, 1.5634, 1.7040, 1.8446, 1.9853, 2.1259, 2.2665, 2.4071], 1):
        add_box_mm(f"2F_WIC_DispS_PassGrain_{g_idx}", 1224.0, 1496.0, -4660.0, -4659.0, z_2f + gz, z_2f + gz + 0.0020, MATS["Wall_Panel_Cream"], col_2f)
    add_box_mm("2F_WIC_DispS_Top", 1240.0, 1500.0, -5240.0, -4682.0, z_2f + 2.4500, z_2f + 2.5000, MATS["Counter_Marble"], col_2f)
    add_box_mm("2F_WIC_DispS_Glow", 1240.0, 1255.0, -5240.0, -4682.0, z_2f + 0.9000, z_2f + 2.4500, MATS["B2_Backlit_Cream"], col_2f)
    add_box_mm("2F_WIC_DispS_Base", 1255.0, 1498.0, -5240.0, -4682.0, z_2f + 0.0000, z_2f + 0.8600, MATS["Wall_Panel_Cream"], col_2f)
    add_box_mm("2F_WIC_DispS_Marble", 1255.0, 1510.0, -5240.0, -4682.0, z_2f + 0.8600, z_2f + 0.9000, MATS["Counter_Marble"], col_2f)
    add_box_mm("2F_WIC_DispS_Shelf_0", 1255.0, 1470.0, -5240.0, -4682.0, z_2f + 1.4500, z_2f + 1.4650, MATS["Window_Glass"], col_2f)
    add_box_mm("2F_WIC_DispS_ShelfRail_0", 1450.0, 1470.0, -5240.0, -4682.0, z_2f + 1.4380, z_2f + 1.4650, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispS_LED_0", 1435.0, 1448.0, -5230.0, -4692.0, z_2f + 1.4420, z_2f + 1.4500, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_WIC_DispS_Shelf_1", 1255.0, 1470.0, -5240.0, -4682.0, z_2f + 2.0500, z_2f + 2.0650, MATS["Window_Glass"], col_2f)
    add_box_mm("2F_WIC_DispS_ShelfRail_1", 1450.0, 1470.0, -5240.0, -4682.0, z_2f + 2.0380, z_2f + 2.0650, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispS_LED_1", 1435.0, 1448.0, -5230.0, -4692.0, z_2f + 2.0420, z_2f + 2.0500, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_WIC_DispS_RailA", 1478.0, 1492.0, -5234.0, -5220.0, z_2f + 0.9000, z_2f + 2.4500, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispS_RailA_Knuckle_0", 1474.0, 1496.0, -5238.0, -5216.0, z_2f + 1.4200, z_2f + 1.4950, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispS_RailA_Knuckle_1", 1474.0, 1496.0, -5238.0, -5216.0, z_2f + 2.0200, z_2f + 2.0950, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispS_RailB", 1478.0, 1492.0, -4702.0, -4688.0, z_2f + 0.9000, z_2f + 2.4500, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispS_RailB_Knuckle_0", 1474.0, 1496.0, -4706.0, -4684.0, z_2f + 1.4200, z_2f + 1.4950, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispS_RailB_Knuckle_1", 1474.0, 1496.0, -4706.0, -4684.0, z_2f + 2.0200, z_2f + 2.0950, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispS_Books", 1280.0, 1420.0, -5160.0, -5010.0, z_2f + 0.9000, z_2f + 1.1800, MATS["Book_Cream"], col_2f)
    add_box_mm("2F_WIC_DispS_Vase", 1290.0, 1420.0, -4912.0, -4782.0, z_2f + 1.4650, z_2f + 1.6800, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_WIC_DispN_Bulkhead", 1220.0, 1500.0, -3450.0, -2850.0, z_2f + 2.5000, z_2f + h_2f, MATS["Wall_New"], col_2f)
    add_box_mm("2F_WIC_DispN_Back", 1220.0, 1240.0, -3428.0, -2850.0, z_2f + 0.0000, z_2f + 2.5000, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_WIC_DispN_SideWall", 1240.0, 1500.0, -2870.0, -2850.0, z_2f + 0.0000, z_2f + 2.5000, MATS["OLO_Cab_White"], col_2f)
    # 见光板: Exposed end panel matching North 4-door wardrobe in Optical Wood Shadow (0.50x0.75m seamless tile, 280x2500mm)
    add_uv_front_box_mm("2F_WIC_DispN_PassPanel", 1220.0, 1500.0, -3450.0, -3428.0, z_2f + 0.0000, z_2f + 2.5000, 0.12, 0.12 + 0.280 / 0.50, 0.0, 2.500 / 0.75, MATS["Optical_Wood_Shadow_WIC"], col_2f)
    add_box_mm("2F_WIC_DispN_Top", 1240.0, 1500.0, -3428.0, -2870.0, z_2f + 2.4500, z_2f + 2.5000, MATS["Counter_Marble"], col_2f)
    add_box_mm("2F_WIC_DispN_Glow", 1240.0, 1255.0, -3428.0, -2870.0, z_2f + 0.9000, z_2f + 2.4500, MATS["B2_Backlit_Cream"], col_2f)
    add_box_mm("2F_WIC_DispN_Base", 1255.0, 1498.0, -3428.0, -2870.0, z_2f + 0.0000, z_2f + 0.8600, MATS["Wall_Panel_Cream"], col_2f)
    add_box_mm("2F_WIC_DispN_Marble", 1255.0, 1510.0, -3428.0, -2870.0, z_2f + 0.8600, z_2f + 0.9000, MATS["Counter_Marble"], col_2f)
    add_box_mm("2F_WIC_DispN_Shelf_0", 1255.0, 1470.0, -3428.0, -2870.0, z_2f + 1.4500, z_2f + 1.4650, MATS["Window_Glass"], col_2f)
    add_box_mm("2F_WIC_DispN_ShelfRail_0", 1450.0, 1470.0, -3428.0, -2870.0, z_2f + 1.4380, z_2f + 1.4650, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispN_LED_0", 1435.0, 1448.0, -3418.0, -2880.0, z_2f + 1.4420, z_2f + 1.4500, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_WIC_DispN_Shelf_1", 1255.0, 1470.0, -3428.0, -2870.0, z_2f + 2.0500, z_2f + 2.0650, MATS["Window_Glass"], col_2f)
    add_box_mm("2F_WIC_DispN_ShelfRail_1", 1450.0, 1470.0, -3428.0, -2870.0, z_2f + 2.0380, z_2f + 2.0650, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispN_LED_1", 1435.0, 1448.0, -3418.0, -2880.0, z_2f + 2.0420, z_2f + 2.0500, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_WIC_DispN_RailA", 1478.0, 1492.0, -3422.0, -3408.0, z_2f + 0.9000, z_2f + 2.4500, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispN_RailA_Knuckle_0", 1474.0, 1496.0, -3426.0, -3404.0, z_2f + 1.4200, z_2f + 1.4950, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispN_RailA_Knuckle_1", 1474.0, 1496.0, -3426.0, -3404.0, z_2f + 2.0200, z_2f + 2.0950, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispN_RailB", 1478.0, 1492.0, -2890.0, -2876.0, z_2f + 0.9000, z_2f + 2.4500, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispN_RailB_Knuckle_0", 1474.0, 1496.0, -2894.0, -2872.0, z_2f + 1.4200, z_2f + 1.4950, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispN_RailB_Knuckle_1", 1474.0, 1496.0, -2894.0, -2872.0, z_2f + 2.0200, z_2f + 2.0950, MATS["RoseGold_Metal"], col_2f)
    add_box_mm("2F_WIC_DispN_Books", 1280.0, 1420.0, -3348.0, -3198.0, z_2f + 0.9000, z_2f + 1.1800, MATS["Book_Cream"], col_2f)
    add_box_mm("2F_WIC_DispN_Vase", 1290.0, 1420.0, -3100.0, -2970.0, z_2f + 1.4650, z_2f + 1.6800, MATS["OLO_Cab_White"], col_2f)
    # Calibrate 2F WIC (+213 mm East divider -> 1573..1713) cleanly in vertex space:
    # - Display alcoves, partitions, and N Bulkhead_Pass translate +213mm East (1220..1500 -> 1433..1713)
    # - North & South wardrobe runs expand smoothly from -450..1220 to -450..1433 (zero gap to display back)
    _wic_scale_x = (1433.0 - (-450.0)) / (1220.0 - (-450.0))
    for _ob in col_2f.objects:
        if not _ob.data or not hasattr(_ob.data, "vertices"):
            continue
        _nm = _ob.name
        if _nm.startswith(("2F_WIC_Partition_", "2F_WIC_DispS_", "2F_WIC_DispN_")) or _nm == "2F_WIC_N_Bulkhead_Pass":
            for _v in _ob.data.vertices:
                _v.co.x += 0.213
            _ob.data.update()
        elif _nm.startswith(("2F_WIC_N_", "2F_WIC_S_")):
            for _v in _ob.data.vertices:
                _v.co.x = -0.450 + (_v.co.x - (-0.450)) * _wic_scale_x
            _ob.data.update()
            if _ob.data.uv_layers and _ob.data.uv_layers.active:
                _uv_data = _ob.data.uv_layers.active.data
                if len(_uv_data) > 0:
                    _umin = min(lp.uv.x for lp in _uv_data)
                    for lp in _uv_data:
                        lp.uv.x = _umin + (lp.uv.x - _umin) * _wic_scale_x

    # Master Bedroom (calibrated width 4788 mm: X = 1714..6502 per WechatIMG7.jpg + 1F East wall alignment)
    add_box_mm("2F_MasterBed_Rug", 1820, 5140, -4064, -2561, z_2f + 0.003, z_2f + 0.015, MATS["Rug_Warm"], col_2f)
    # build_bed("2F_MasterBed_King", 2490, 4490, -5240, -3250, z_2f, "bottom", col_2f)  # replaced by f2_master_spec (rev. 2026-10-28)
    # add_box_mm("2F_MasterBed_NightstandL", 1510, 2460, -5240, -4680, zf_2f, z_2f + 0.52, MATS["Cabinet_Walnut"], col_2f, r_corner=20.0)  # replaced by f2_master_spec (rev. 2026-10-28)
    # add_box_mm("2F_MasterBed_NightstandR", 4520, 5190, -5240, -4680, zf_2f, z_2f + 0.52, MATS["Cabinet_Walnut"], col_2f, r_corner=20.0)  # replaced by f2_master_spec (rev. 2026-10-28)
    # add_box_mm("2F_MasterBed_Dresser", 5210, 6481, -5230, -4670, zf_2f, z_2f + 0.76, MATS["Cabinet_Cream"], col_2f, r_corner=25.0)  # replaced by f2_master_spec (rev. 2026-10-28)
    # add_cyl_mm("2F_MasterBed_Stool", 5836, -4399, 219, zf_2f, z_2f + 0.45, MATS["Accent_Leather"], col_2f)  # replaced by f2_master_spec (rev. 2026-10-28)
    # 2F master bedroom after reference rendering (rev. 2026-10-28, generated by f2_master_spec.py)
    def _add_raw_mesh_2f(rname, V, F, mat):
        me = bpy.data.meshes.new(rname)
        me.from_pydata([(x, y, z_2f + z) for (x, y, z) in V], [], [list(f) for f in F])
        me.update()
        ob = bpy.data.objects.new(rname, me)
        ob.data.materials.append(mat)
        link_obj(ob, col_2f)
        return ob
    add_box_mm("2F_MBR_HeadWall_Grey", 2490.0, 4490.0, -5280.0, -5260.0, z_2f + 0.0000, z_2f + 2.5000, MATS["Wallcover_Grey"], col_2f)
    add_box_mm("2F_MBR_HeadWall_BrassStrip_L", 2478.0, 2502.0, -5280.0, -5250.0, z_2f + 0.0000, z_2f + 2.5000, MATS["Gold_Brass"], col_2f)
    add_box_mm("2F_MBR_HeadWall_BrassStrip_R", 4478.0, 4502.0, -5280.0, -5250.0, z_2f + 0.0000, z_2f + 2.5000, MATS["Gold_Brass"], col_2f)
    add_box_mm("2F_MBR_HeadWall_Cream_W", 1714.0, 2478.0, -5280.0, -5255.0, z_2f + 0.0000, z_2f + 2.5000, MATS["Wall_Panel_Cream"], col_2f)
    add_box_mm("2F_MBR_HeadWall_Cream_W_Groove_1", 1864.0, 1870.0, -5255.0, -5252.0, z_2f + 0.0000, z_2f + 2.5000, MATS["OLO_Cab_Greige"], col_2f)
    add_box_mm("2F_MBR_HeadWall_Cream_W_Groove_2", 2017.0, 2023.0, -5255.0, -5252.0, z_2f + 0.0000, z_2f + 2.5000, MATS["OLO_Cab_Greige"], col_2f)
    add_box_mm("2F_MBR_HeadWall_Cream_W_Groove_3", 2170.0, 2176.0, -5255.0, -5252.0, z_2f + 0.0000, z_2f + 2.5000, MATS["OLO_Cab_Greige"], col_2f)
    add_box_mm("2F_MBR_HeadWall_Cream_W_Groove_4", 2323.0, 2329.0, -5255.0, -5252.0, z_2f + 0.0000, z_2f + 2.5000, MATS["OLO_Cab_Greige"], col_2f)
    add_box_mm("2F_MBR_Sconce_W_Plate", 2024.0, 2094.0, -5255.0, -5240.0, z_2f + 1.4200, z_2f + 1.9800, MATS["Stair_Bronze_Iron"], col_2f)
    _add_raw_mesh_2f("2F_MBR_Sconce_W_BladeA", [(2.0690, -5.2400, 1.9800), (2.0682, -5.2400, 1.9878), (2.0660, -5.2400, 1.9953), (2.0623, -5.2400, 2.0022), (2.0573, -5.2400, 2.0083), (2.0512, -5.2400, 2.0133), (2.0443, -5.2400, 2.0170), (2.0368, -5.2400, 2.0192), (2.0290, -5.2400, 2.0200), (2.0290, -5.2400, 2.0200), (2.0212, -5.2400, 2.0192), (2.0137, -5.2400, 2.0170), (2.0068, -5.2400, 2.0133), (2.0007, -5.2400, 2.0083), (1.9957, -5.2400, 2.0022), (1.9920, -5.2400, 1.9953), (1.9898, -5.2400, 1.9878), (1.9890, -5.2400, 1.9800), (1.9890, -5.2400, 1.4200), (1.9898, -5.2400, 1.4122), (1.9920, -5.2400, 1.4047), (1.9957, -5.2400, 1.3978), (2.0007, -5.2400, 1.3917), (2.0068, -5.2400, 1.3867), (2.0137, -5.2400, 1.3830), (2.0212, -5.2400, 1.3808), (2.0290, -5.2400, 1.3800), (2.0290, -5.2400, 1.3800), (2.0368, -5.2400, 1.3808), (2.0443, -5.2400, 1.3830), (2.0512, -5.2400, 1.3867), (2.0573, -5.2400, 1.3917), (2.0623, -5.2400, 1.3978), (2.0660, -5.2400, 1.4047), (2.0682, -5.2400, 1.4122), (2.0690, -5.2400, 1.4200), (2.0690, -5.1950, 1.9800), (2.0682, -5.1950, 1.9878), (2.0660, -5.1950, 1.9953), (2.0623, -5.1950, 2.0022), (2.0573, -5.1950, 2.0083), (2.0512, -5.1950, 2.0133), (2.0443, -5.1950, 2.0170), (2.0368, -5.1950, 2.0192), (2.0290, -5.1950, 2.0200), (2.0290, -5.1950, 2.0200), (2.0212, -5.1950, 2.0192), (2.0137, -5.1950, 2.0170), (2.0068, -5.1950, 2.0133), (2.0007, -5.1950, 2.0083), (1.9957, -5.1950, 2.0022), (1.9920, -5.1950, 1.9953), (1.9898, -5.1950, 1.9878), (1.9890, -5.1950, 1.9800), (1.9890, -5.1950, 1.4200), (1.9898, -5.1950, 1.4122), (1.9920, -5.1950, 1.4047), (1.9957, -5.1950, 1.3978), (2.0007, -5.1950, 1.3917), (2.0068, -5.1950, 1.3867), (2.0137, -5.1950, 1.3830), (2.0212, -5.1950, 1.3808), (2.0290, -5.1950, 1.3800), (2.0290, -5.1950, 1.3800), (2.0368, -5.1950, 1.3808), (2.0443, -5.1950, 1.3830), (2.0512, -5.1950, 1.3867), (2.0573, -5.1950, 1.3917), (2.0623, -5.1950, 1.3978), (2.0660, -5.1950, 1.4047), (2.0682, -5.1950, 1.4122), (2.0690, -5.1950, 1.4200)], [(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35), (71, 70, 69, 68, 67, 66, 65, 64, 63, 62, 61, 60, 59, 58, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38, 37, 36), (1, 0, 36, 37), (2, 1, 37, 38), (3, 2, 38, 39), (4, 3, 39, 40), (5, 4, 40, 41), (6, 5, 41, 42), (7, 6, 42, 43), (8, 7, 43, 44), (9, 8, 44, 45), (10, 9, 45, 46), (11, 10, 46, 47), (12, 11, 47, 48), (13, 12, 48, 49), (14, 13, 49, 50), (15, 14, 50, 51), (16, 15, 51, 52), (17, 16, 52, 53), (18, 17, 53, 54), (19, 18, 54, 55), (20, 19, 55, 56), (21, 20, 56, 57), (22, 21, 57, 58), (23, 22, 58, 59), (24, 23, 59, 60), (25, 24, 60, 61), (26, 25, 61, 62), (27, 26, 62, 63), (28, 27, 63, 64), (29, 28, 64, 65), (30, 29, 65, 66), (31, 30, 66, 67), (32, 31, 67, 68), (33, 32, 68, 69), (34, 33, 69, 70), (35, 34, 70, 71), (0, 35, 71, 36)], MATS["Sconce_Alabaster"])
    _add_raw_mesh_2f("2F_MBR_Sconce_W_BladeB", [(2.1240, -5.2200, 2.0600), (2.1232, -5.2200, 2.0678), (2.1210, -5.2200, 2.0753), (2.1173, -5.2200, 2.0822), (2.1123, -5.2200, 2.0883), (2.1062, -5.2200, 2.0933), (2.0993, -5.2200, 2.0970), (2.0918, -5.2200, 2.0992), (2.0840, -5.2200, 2.1000), (2.0840, -5.2200, 2.1000), (2.0762, -5.2200, 2.0992), (2.0687, -5.2200, 2.0970), (2.0618, -5.2200, 2.0933), (2.0557, -5.2200, 2.0883), (2.0507, -5.2200, 2.0822), (2.0470, -5.2200, 2.0753), (2.0448, -5.2200, 2.0678), (2.0440, -5.2200, 2.0600), (2.0440, -5.2200, 1.5000), (2.0448, -5.2200, 1.4922), (2.0470, -5.2200, 1.4847), (2.0507, -5.2200, 1.4778), (2.0557, -5.2200, 1.4717), (2.0618, -5.2200, 1.4667), (2.0687, -5.2200, 1.4630), (2.0762, -5.2200, 1.4608), (2.0840, -5.2200, 1.4600), (2.0840, -5.2200, 1.4600), (2.0918, -5.2200, 1.4608), (2.0993, -5.2200, 1.4630), (2.1062, -5.2200, 1.4667), (2.1123, -5.2200, 1.4717), (2.1173, -5.2200, 1.4778), (2.1210, -5.2200, 1.4847), (2.1232, -5.2200, 1.4922), (2.1240, -5.2200, 1.5000), (2.1240, -5.1750, 2.0600), (2.1232, -5.1750, 2.0678), (2.1210, -5.1750, 2.0753), (2.1173, -5.1750, 2.0822), (2.1123, -5.1750, 2.0883), (2.1062, -5.1750, 2.0933), (2.0993, -5.1750, 2.0970), (2.0918, -5.1750, 2.0992), (2.0840, -5.1750, 2.1000), (2.0840, -5.1750, 2.1000), (2.0762, -5.1750, 2.0992), (2.0687, -5.1750, 2.0970), (2.0618, -5.1750, 2.0933), (2.0557, -5.1750, 2.0883), (2.0507, -5.1750, 2.0822), (2.0470, -5.1750, 2.0753), (2.0448, -5.1750, 2.0678), (2.0440, -5.1750, 2.0600), (2.0440, -5.1750, 1.5000), (2.0448, -5.1750, 1.4922), (2.0470, -5.1750, 1.4847), (2.0507, -5.1750, 1.4778), (2.0557, -5.1750, 1.4717), (2.0618, -5.1750, 1.4667), (2.0687, -5.1750, 1.4630), (2.0762, -5.1750, 1.4608), (2.0840, -5.1750, 1.4600), (2.0840, -5.1750, 1.4600), (2.0918, -5.1750, 1.4608), (2.0993, -5.1750, 1.4630), (2.1062, -5.1750, 1.4667), (2.1123, -5.1750, 1.4717), (2.1173, -5.1750, 1.4778), (2.1210, -5.1750, 1.4847), (2.1232, -5.1750, 1.4922), (2.1240, -5.1750, 1.5000)], [(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35), (71, 70, 69, 68, 67, 66, 65, 64, 63, 62, 61, 60, 59, 58, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38, 37, 36), (1, 0, 36, 37), (2, 1, 37, 38), (3, 2, 38, 39), (4, 3, 39, 40), (5, 4, 40, 41), (6, 5, 41, 42), (7, 6, 42, 43), (8, 7, 43, 44), (9, 8, 44, 45), (10, 9, 45, 46), (11, 10, 46, 47), (12, 11, 47, 48), (13, 12, 48, 49), (14, 13, 49, 50), (15, 14, 50, 51), (16, 15, 51, 52), (17, 16, 52, 53), (18, 17, 53, 54), (19, 18, 54, 55), (20, 19, 55, 56), (21, 20, 56, 57), (22, 21, 57, 58), (23, 22, 58, 59), (24, 23, 59, 60), (25, 24, 60, 61), (26, 25, 61, 62), (27, 26, 62, 63), (28, 27, 63, 64), (29, 28, 64, 65), (30, 29, 65, 66), (31, 30, 66, 67), (32, 31, 67, 68), (33, 32, 68, 69), (34, 33, 69, 70), (35, 34, 70, 71), (0, 35, 71, 36)], MATS["Sconce_Alabaster"])
    add_box_mm("2F_MBR_HeadWall_Cream_E", 4502.0, 5200.0, -5250.0, -5225.0, z_2f + 0.0000, z_2f + 2.5000, MATS["Wall_Panel_Cream"], col_2f)
    add_box_mm("2F_MBR_HeadWall_Cream_E_Groove_1", 4640.0, 4646.0, -5225.0, -5222.0, z_2f + 0.0000, z_2f + 2.5000, MATS["OLO_Cab_Greige"], col_2f)
    add_box_mm("2F_MBR_HeadWall_Cream_E_Groove_2", 4780.0, 4786.0, -5225.0, -5222.0, z_2f + 0.0000, z_2f + 2.5000, MATS["OLO_Cab_Greige"], col_2f)
    add_box_mm("2F_MBR_HeadWall_Cream_E_Groove_3", 4920.0, 4926.0, -5225.0, -5222.0, z_2f + 0.0000, z_2f + 2.5000, MATS["OLO_Cab_Greige"], col_2f)
    add_box_mm("2F_MBR_HeadWall_Cream_E_Groove_4", 5060.0, 5066.0, -5225.0, -5222.0, z_2f + 0.0000, z_2f + 2.5000, MATS["OLO_Cab_Greige"], col_2f)
    add_box_mm("2F_MBR_HeadWall_Soffit", 1714.0, 5160.0, -5280.0, -5225.0, z_2f + 2.5000, z_2f + 2.8300, MATS["Wall_Panel_Cream"], col_2f)
    add_box_mm("2F_MBR_Sconce_E_Plate", 4886.0, 4956.0, -5225.0, -5210.0, z_2f + 1.4200, z_2f + 1.9800, MATS["Stair_Bronze_Iron"], col_2f)
    _add_raw_mesh_2f("2F_MBR_Sconce_E_BladeA", [(4.9310, -5.2100, 1.9800), (4.9302, -5.2100, 1.9878), (4.9280, -5.2100, 1.9953), (4.9243, -5.2100, 2.0022), (4.9193, -5.2100, 2.0083), (4.9132, -5.2100, 2.0133), (4.9063, -5.2100, 2.0170), (4.8988, -5.2100, 2.0192), (4.8910, -5.2100, 2.0200), (4.8910, -5.2100, 2.0200), (4.8832, -5.2100, 2.0192), (4.8757, -5.2100, 2.0170), (4.8688, -5.2100, 2.0133), (4.8627, -5.2100, 2.0083), (4.8577, -5.2100, 2.0022), (4.8540, -5.2100, 1.9953), (4.8518, -5.2100, 1.9878), (4.8510, -5.2100, 1.9800), (4.8510, -5.2100, 1.4200), (4.8518, -5.2100, 1.4122), (4.8540, -5.2100, 1.4047), (4.8577, -5.2100, 1.3978), (4.8627, -5.2100, 1.3917), (4.8688, -5.2100, 1.3867), (4.8757, -5.2100, 1.3830), (4.8832, -5.2100, 1.3808), (4.8910, -5.2100, 1.3800), (4.8910, -5.2100, 1.3800), (4.8988, -5.2100, 1.3808), (4.9063, -5.2100, 1.3830), (4.9132, -5.2100, 1.3867), (4.9193, -5.2100, 1.3917), (4.9243, -5.2100, 1.3978), (4.9280, -5.2100, 1.4047), (4.9302, -5.2100, 1.4122), (4.9310, -5.2100, 1.4200), (4.9310, -5.1650, 1.9800), (4.9302, -5.1650, 1.9878), (4.9280, -5.1650, 1.9953), (4.9243, -5.1650, 2.0022), (4.9193, -5.1650, 2.0083), (4.9132, -5.1650, 2.0133), (4.9063, -5.1650, 2.0170), (4.8988, -5.1650, 2.0192), (4.8910, -5.1650, 2.0200), (4.8910, -5.1650, 2.0200), (4.8832, -5.1650, 2.0192), (4.8757, -5.1650, 2.0170), (4.8688, -5.1650, 2.0133), (4.8627, -5.1650, 2.0083), (4.8577, -5.1650, 2.0022), (4.8540, -5.1650, 1.9953), (4.8518, -5.1650, 1.9878), (4.8510, -5.1650, 1.9800), (4.8510, -5.1650, 1.4200), (4.8518, -5.1650, 1.4122), (4.8540, -5.1650, 1.4047), (4.8577, -5.1650, 1.3978), (4.8627, -5.1650, 1.3917), (4.8688, -5.1650, 1.3867), (4.8757, -5.1650, 1.3830), (4.8832, -5.1650, 1.3808), (4.8910, -5.1650, 1.3800), (4.8910, -5.1650, 1.3800), (4.8988, -5.1650, 1.3808), (4.9063, -5.1650, 1.3830), (4.9132, -5.1650, 1.3867), (4.9193, -5.1650, 1.3917), (4.9243, -5.1650, 1.3978), (4.9280, -5.1650, 1.4047), (4.9302, -5.1650, 1.4122), (4.9310, -5.1650, 1.4200)], [(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35), (71, 70, 69, 68, 67, 66, 65, 64, 63, 62, 61, 60, 59, 58, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38, 37, 36), (1, 0, 36, 37), (2, 1, 37, 38), (3, 2, 38, 39), (4, 3, 39, 40), (5, 4, 40, 41), (6, 5, 41, 42), (7, 6, 42, 43), (8, 7, 43, 44), (9, 8, 44, 45), (10, 9, 45, 46), (11, 10, 46, 47), (12, 11, 47, 48), (13, 12, 48, 49), (14, 13, 49, 50), (15, 14, 50, 51), (16, 15, 51, 52), (17, 16, 52, 53), (18, 17, 53, 54), (19, 18, 54, 55), (20, 19, 55, 56), (21, 20, 56, 57), (22, 21, 57, 58), (23, 22, 58, 59), (24, 23, 59, 60), (25, 24, 60, 61), (26, 25, 61, 62), (27, 26, 62, 63), (28, 27, 63, 64), (29, 28, 64, 65), (30, 29, 65, 66), (31, 30, 66, 67), (32, 31, 67, 68), (33, 32, 68, 69), (34, 33, 69, 70), (35, 34, 70, 71), (0, 35, 71, 36)], MATS["Sconce_Alabaster"])
    _add_raw_mesh_2f("2F_MBR_Sconce_E_BladeB", [(4.9860, -5.1900, 2.0600), (4.9852, -5.1900, 2.0678), (4.9830, -5.1900, 2.0753), (4.9793, -5.1900, 2.0822), (4.9743, -5.1900, 2.0883), (4.9682, -5.1900, 2.0933), (4.9613, -5.1900, 2.0970), (4.9538, -5.1900, 2.0992), (4.9460, -5.1900, 2.1000), (4.9460, -5.1900, 2.1000), (4.9382, -5.1900, 2.0992), (4.9307, -5.1900, 2.0970), (4.9238, -5.1900, 2.0933), (4.9177, -5.1900, 2.0883), (4.9127, -5.1900, 2.0822), (4.9090, -5.1900, 2.0753), (4.9068, -5.1900, 2.0678), (4.9060, -5.1900, 2.0600), (4.9060, -5.1900, 1.5000), (4.9068, -5.1900, 1.4922), (4.9090, -5.1900, 1.4847), (4.9127, -5.1900, 1.4778), (4.9177, -5.1900, 1.4717), (4.9238, -5.1900, 1.4667), (4.9307, -5.1900, 1.4630), (4.9382, -5.1900, 1.4608), (4.9460, -5.1900, 1.4600), (4.9460, -5.1900, 1.4600), (4.9538, -5.1900, 1.4608), (4.9613, -5.1900, 1.4630), (4.9682, -5.1900, 1.4667), (4.9743, -5.1900, 1.4717), (4.9793, -5.1900, 1.4778), (4.9830, -5.1900, 1.4847), (4.9852, -5.1900, 1.4922), (4.9860, -5.1900, 1.5000), (4.9860, -5.1450, 2.0600), (4.9852, -5.1450, 2.0678), (4.9830, -5.1450, 2.0753), (4.9793, -5.1450, 2.0822), (4.9743, -5.1450, 2.0883), (4.9682, -5.1450, 2.0933), (4.9613, -5.1450, 2.0970), (4.9538, -5.1450, 2.0992), (4.9460, -5.1450, 2.1000), (4.9460, -5.1450, 2.1000), (4.9382, -5.1450, 2.0992), (4.9307, -5.1450, 2.0970), (4.9238, -5.1450, 2.0933), (4.9177, -5.1450, 2.0883), (4.9127, -5.1450, 2.0822), (4.9090, -5.1450, 2.0753), (4.9068, -5.1450, 2.0678), (4.9060, -5.1450, 2.0600), (4.9060, -5.1450, 1.5000), (4.9068, -5.1450, 1.4922), (4.9090, -5.1450, 1.4847), (4.9127, -5.1450, 1.4778), (4.9177, -5.1450, 1.4717), (4.9238, -5.1450, 1.4667), (4.9307, -5.1450, 1.4630), (4.9382, -5.1450, 1.4608), (4.9460, -5.1450, 1.4600), (4.9460, -5.1450, 1.4600), (4.9538, -5.1450, 1.4608), (4.9613, -5.1450, 1.4630), (4.9682, -5.1450, 1.4667), (4.9743, -5.1450, 1.4717), (4.9793, -5.1450, 1.4778), (4.9830, -5.1450, 1.4847), (4.9852, -5.1450, 1.4922), (4.9860, -5.1450, 1.5000)], [(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35), (71, 70, 69, 68, 67, 66, 65, 64, 63, 62, 61, 60, 59, 58, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38, 37, 36), (1, 0, 36, 37), (2, 1, 37, 38), (3, 2, 38, 39), (4, 3, 39, 40), (5, 4, 40, 41), (6, 5, 41, 42), (7, 6, 42, 43), (8, 7, 43, 44), (9, 8, 44, 45), (10, 9, 45, 46), (11, 10, 46, 47), (12, 11, 47, 48), (13, 12, 48, 49), (14, 13, 49, 50), (15, 14, 50, 51), (16, 15, 51, 52), (17, 16, 52, 53), (18, 17, 53, 54), (19, 18, 54, 55), (20, 19, 55, 56), (21, 20, 56, 57), (22, 21, 57, 58), (23, 22, 58, 59), (24, 23, 59, 60), (25, 24, 60, 61), (26, 25, 61, 62), (27, 26, 62, 63), (28, 27, 63, 64), (29, 28, 64, 65), (30, 29, 65, 66), (31, 30, 66, 67), (32, 31, 67, 68), (33, 32, 68, 69), (34, 33, 69, 70), (35, 34, 70, 71), (0, 35, 71, 36)], MATS["Sconce_Alabaster"])
    # Removed 2F_MBR_HeadWall_Cream_WEnd (1500..1640) — now inside calibrated WIC partition 1574..1714
    add_box_mm("2F_MBR_Bed_Plinth", 2570.0, 4410.0, -5070.0, -3140.0, z_2f + 0.0000, z_2f + 0.1200, MATS["OLO_Cab_Greige"], col_2f)
    _add_raw_mesh_2f("2F_MBR_Bed_Base", [(4.4900, -3.1000, 0.1200), (4.4892, -3.0922, 0.1200), (4.4870, -3.0847, 0.1200), (4.4833, -3.0778, 0.1200), (4.4783, -3.0717, 0.1200), (4.4722, -3.0667, 0.1200), (4.4653, -3.0630, 0.1200), (4.4578, -3.0608, 0.1200), (4.4500, -3.0600, 0.1200), (2.5300, -3.0600, 0.1200), (2.5222, -3.0608, 0.1200), (2.5147, -3.0630, 0.1200), (2.5078, -3.0667, 0.1200), (2.5017, -3.0717, 0.1200), (2.4967, -3.0778, 0.1200), (2.4930, -3.0847, 0.1200), (2.4908, -3.0922, 0.1200), (2.4900, -3.1000, 0.1200), (2.4900, -5.0900, 0.1200), (2.4908, -5.0978, 0.1200), (2.4930, -5.1053, 0.1200), (2.4967, -5.1122, 0.1200), (2.5017, -5.1183, 0.1200), (2.5078, -5.1233, 0.1200), (2.5147, -5.1270, 0.1200), (2.5222, -5.1292, 0.1200), (2.5300, -5.1300, 0.1200), (4.4500, -5.1300, 0.1200), (4.4578, -5.1292, 0.1200), (4.4653, -5.1270, 0.1200), (4.4722, -5.1233, 0.1200), (4.4783, -5.1183, 0.1200), (4.4833, -5.1122, 0.1200), (4.4870, -5.1053, 0.1200), (4.4892, -5.0978, 0.1200), (4.4900, -5.0900, 0.1200), (4.4900, -3.1000, 0.3000), (4.4892, -3.0922, 0.3000), (4.4870, -3.0847, 0.3000), (4.4833, -3.0778, 0.3000), (4.4783, -3.0717, 0.3000), (4.4722, -3.0667, 0.3000), (4.4653, -3.0630, 0.3000), (4.4578, -3.0608, 0.3000), (4.4500, -3.0600, 0.3000), (2.5300, -3.0600, 0.3000), (2.5222, -3.0608, 0.3000), (2.5147, -3.0630, 0.3000), (2.5078, -3.0667, 0.3000), (2.5017, -3.0717, 0.3000), (2.4967, -3.0778, 0.3000), (2.4930, -3.0847, 0.3000), (2.4908, -3.0922, 0.3000), (2.4900, -3.1000, 0.3000), (2.4900, -5.0900, 0.3000), (2.4908, -5.0978, 0.3000), (2.4930, -5.1053, 0.3000), (2.4967, -5.1122, 0.3000), (2.5017, -5.1183, 0.3000), (2.5078, -5.1233, 0.3000), (2.5147, -5.1270, 0.3000), (2.5222, -5.1292, 0.3000), (2.5300, -5.1300, 0.3000), (4.4500, -5.1300, 0.3000), (4.4578, -5.1292, 0.3000), (4.4653, -5.1270, 0.3000), (4.4722, -5.1233, 0.3000), (4.4783, -5.1183, 0.3000), (4.4833, -5.1122, 0.3000), (4.4870, -5.1053, 0.3000), (4.4892, -5.0978, 0.3000), (4.4900, -5.0900, 0.3000)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["OLO_Cab_Greige"])
    _add_raw_mesh_2f("2F_MBR_Bed_Mattress", [(4.4700, -3.1500, 0.3000), (4.4687, -3.1363, 0.3000), (4.4647, -3.1232, 0.3000), (4.4582, -3.1111, 0.3000), (4.4495, -3.1005, 0.3000), (4.4389, -3.0918, 0.3000), (4.4268, -3.0853, 0.3000), (4.4137, -3.0813, 0.3000), (4.4000, -3.0800, 0.3000), (2.5800, -3.0800, 0.3000), (2.5663, -3.0813, 0.3000), (2.5532, -3.0853, 0.3000), (2.5411, -3.0918, 0.3000), (2.5305, -3.1005, 0.3000), (2.5218, -3.1111, 0.3000), (2.5153, -3.1232, 0.3000), (2.5113, -3.1363, 0.3000), (2.5100, -3.1500, 0.3000), (2.5100, -5.0400, 0.3000), (2.5113, -5.0537, 0.3000), (2.5153, -5.0668, 0.3000), (2.5218, -5.0789, 0.3000), (2.5305, -5.0895, 0.3000), (2.5411, -5.0982, 0.3000), (2.5532, -5.1047, 0.3000), (2.5663, -5.1087, 0.3000), (2.5800, -5.1100, 0.3000), (4.4000, -5.1100, 0.3000), (4.4137, -5.1087, 0.3000), (4.4268, -5.1047, 0.3000), (4.4389, -5.0982, 0.3000), (4.4495, -5.0895, 0.3000), (4.4582, -5.0789, 0.3000), (4.4647, -5.0668, 0.3000), (4.4687, -5.0537, 0.3000), (4.4700, -5.0400, 0.3000), (4.4700, -3.1500, 0.5200), (4.4687, -3.1363, 0.5200), (4.4647, -3.1232, 0.5200), (4.4582, -3.1111, 0.5200), (4.4495, -3.1005, 0.5200), (4.4389, -3.0918, 0.5200), (4.4268, -3.0853, 0.5200), (4.4137, -3.0813, 0.5200), (4.4000, -3.0800, 0.5200), (2.5800, -3.0800, 0.5200), (2.5663, -3.0813, 0.5200), (2.5532, -3.0853, 0.5200), (2.5411, -3.0918, 0.5200), (2.5305, -3.1005, 0.5200), (2.5218, -3.1111, 0.5200), (2.5153, -3.1232, 0.5200), (2.5113, -3.1363, 0.5200), (2.5100, -3.1500, 0.5200), (2.5100, -5.0400, 0.5200), (2.5113, -5.0537, 0.5200), (2.5153, -5.0668, 0.5200), (2.5218, -5.0789, 0.5200), (2.5305, -5.0895, 0.5200), (2.5411, -5.0982, 0.5200), (2.5532, -5.1047, 0.5200), (2.5663, -5.1087, 0.5200), (2.5800, -5.1100, 0.5200), (4.4000, -5.1100, 0.5200), (4.4137, -5.1087, 0.5200), (4.4268, -5.1047, 0.5200), (4.4389, -5.0982, 0.5200), (4.4495, -5.0895, 0.5200), (4.4582, -5.0789, 0.5200), (4.4647, -5.0668, 0.5200), (4.4687, -5.0537, 0.5200), (4.4700, -5.0400, 0.5200)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["Bed_Linen"])
    _add_raw_mesh_2f("2F_MBR_Bed_Duvet", [(4.5300, -3.0800, 0.3600), (4.5288, -3.0683, 0.3600), (4.5254, -3.0570, 0.3600), (4.5199, -3.0467, 0.3600), (4.5124, -3.0376, 0.3600), (4.5033, -3.0301, 0.3600), (4.4930, -3.0246, 0.3600), (4.4817, -3.0212, 0.3600), (4.4700, -3.0200, 0.3600), (2.5100, -3.0200, 0.3600), (2.4983, -3.0212, 0.3600), (2.4870, -3.0246, 0.3600), (2.4767, -3.0301, 0.3600), (2.4676, -3.0376, 0.3600), (2.4601, -3.0467, 0.3600), (2.4546, -3.0570, 0.3600), (2.4512, -3.0683, 0.3600), (2.4500, -3.0800, 0.3600), (2.4500, -4.5500, 0.3600), (2.4512, -4.5617, 0.3600), (2.4546, -4.5730, 0.3600), (2.4601, -4.5833, 0.3600), (2.4676, -4.5924, 0.3600), (2.4767, -4.5999, 0.3600), (2.4870, -4.6054, 0.3600), (2.4983, -4.6088, 0.3600), (2.5100, -4.6100, 0.3600), (4.4700, -4.6100, 0.3600), (4.4817, -4.6088, 0.3600), (4.4930, -4.6054, 0.3600), (4.5033, -4.5999, 0.3600), (4.5124, -4.5924, 0.3600), (4.5199, -4.5833, 0.3600), (4.5254, -4.5730, 0.3600), (4.5288, -4.5617, 0.3600), (4.5300, -4.5500, 0.3600), (4.5300, -3.0800, 0.5600), (4.5288, -3.0683, 0.5600), (4.5254, -3.0570, 0.5600), (4.5199, -3.0467, 0.5600), (4.5124, -3.0376, 0.5600), (4.5033, -3.0301, 0.5600), (4.4930, -3.0246, 0.5600), (4.4817, -3.0212, 0.5600), (4.4700, -3.0200, 0.5600), (2.5100, -3.0200, 0.5600), (2.4983, -3.0212, 0.5600), (2.4870, -3.0246, 0.5600), (2.4767, -3.0301, 0.5600), (2.4676, -3.0376, 0.5600), (2.4601, -3.0467, 0.5600), (2.4546, -3.0570, 0.5600), (2.4512, -3.0683, 0.5600), (2.4500, -3.0800, 0.5600), (2.4500, -4.5500, 0.5600), (2.4512, -4.5617, 0.5600), (2.4546, -4.5730, 0.5600), (2.4601, -4.5833, 0.5600), (2.4676, -4.5924, 0.5600), (2.4767, -4.5999, 0.5600), (2.4870, -4.6054, 0.5600), (2.4983, -4.6088, 0.5600), (2.5100, -4.6100, 0.5600), (4.4700, -4.6100, 0.5600), (4.4817, -4.6088, 0.5600), (4.4930, -4.6054, 0.5600), (4.5033, -4.5999, 0.5600), (4.5124, -4.5924, 0.5600), (4.5199, -4.5833, 0.5600), (4.5254, -4.5730, 0.5600), (4.5288, -4.5617, 0.5600), (4.5300, -4.5500, 0.5600)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["Bed_Linen"])
    _add_raw_mesh_2f("2F_MBR_Bed_Throw", [(4.5400, -3.4400, 0.5600), (4.5396, -3.4361, 0.5600), (4.5385, -3.4323, 0.5600), (4.5366, -3.4289, 0.5600), (4.5341, -3.4259, 0.5600), (4.5311, -3.4234, 0.5600), (4.5277, -3.4215, 0.5600), (4.5239, -3.4204, 0.5600), (4.5200, -3.4200, 0.5600), (2.4600, -3.4200, 0.5600), (2.4561, -3.4204, 0.5600), (2.4523, -3.4215, 0.5600), (2.4489, -3.4234, 0.5600), (2.4459, -3.4259, 0.5600), (2.4434, -3.4289, 0.5600), (2.4415, -3.4323, 0.5600), (2.4404, -3.4361, 0.5600), (2.4400, -3.4400, 0.5600), (2.4400, -3.8800, 0.5600), (2.4404, -3.8839, 0.5600), (2.4415, -3.8877, 0.5600), (2.4434, -3.8911, 0.5600), (2.4459, -3.8941, 0.5600), (2.4489, -3.8966, 0.5600), (2.4523, -3.8985, 0.5600), (2.4561, -3.8996, 0.5600), (2.4600, -3.9000, 0.5600), (4.5200, -3.9000, 0.5600), (4.5239, -3.8996, 0.5600), (4.5277, -3.8985, 0.5600), (4.5311, -3.8966, 0.5600), (4.5341, -3.8941, 0.5600), (4.5366, -3.8911, 0.5600), (4.5385, -3.8877, 0.5600), (4.5396, -3.8839, 0.5600), (4.5400, -3.8800, 0.5600), (4.5400, -3.4400, 0.5800), (4.5396, -3.4361, 0.5800), (4.5385, -3.4323, 0.5800), (4.5366, -3.4289, 0.5800), (4.5341, -3.4259, 0.5800), (4.5311, -3.4234, 0.5800), (4.5277, -3.4215, 0.5800), (4.5239, -3.4204, 0.5800), (4.5200, -3.4200, 0.5800), (2.4600, -3.4200, 0.5800), (2.4561, -3.4204, 0.5800), (2.4523, -3.4215, 0.5800), (2.4489, -3.4234, 0.5800), (2.4459, -3.4259, 0.5800), (2.4434, -3.4289, 0.5800), (2.4415, -3.4323, 0.5800), (2.4404, -3.4361, 0.5800), (2.4400, -3.4400, 0.5800), (2.4400, -3.8800, 0.5800), (2.4404, -3.8839, 0.5800), (2.4415, -3.8877, 0.5800), (2.4434, -3.8911, 0.5800), (2.4459, -3.8941, 0.5800), (2.4489, -3.8966, 0.5800), (2.4523, -3.8985, 0.5800), (2.4561, -3.8996, 0.5800), (2.4600, -3.9000, 0.5800), (4.5200, -3.9000, 0.5800), (4.5239, -3.8996, 0.5800), (4.5277, -3.8985, 0.5800), (4.5311, -3.8966, 0.5800), (4.5341, -3.8941, 0.5800), (4.5366, -3.8911, 0.5800), (4.5385, -3.8877, 0.5800), (4.5396, -3.8839, 0.5800), (4.5400, -3.8800, 0.5800)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["Bed_Throw"])
    add_box_mm("2F_MBR_Bed_Throw_DrapeW", 2438.0, 2450.0, -3900.0, -3420.0, z_2f + 0.2500, z_2f + 0.5800, MATS["Bed_Throw"], col_2f)
    add_box_mm("2F_MBR_Bed_Throw_DrapeE", 4530.0, 4542.0, -3900.0, -3420.0, z_2f + 0.2500, z_2f + 0.5800, MATS["Bed_Throw"], col_2f)
    _add_raw_mesh_2f("2F_MBR_Bed_Pillow_L", [(3.4600, -4.9500, 0.5200), (3.4583, -4.9324, 0.5200), (3.4531, -4.9156, 0.5200), (3.4448, -4.9000, 0.5200), (3.4336, -4.8864, 0.5200), (3.4200, -4.8752, 0.5200), (3.4044, -4.8669, 0.5200), (3.3876, -4.8617, 0.5200), (3.3700, -4.8600, 0.5200), (2.7000, -4.8600, 0.5200), (2.6824, -4.8617, 0.5200), (2.6656, -4.8669, 0.5200), (2.6500, -4.8752, 0.5200), (2.6364, -4.8864, 0.5200), (2.6252, -4.9000, 0.5200), (2.6169, -4.9156, 0.5200), (2.6117, -4.9324, 0.5200), (2.6100, -4.9500, 0.5200), (2.6100, -4.9700, 0.5200), (2.6117, -4.9876, 0.5200), (2.6169, -5.0044, 0.5200), (2.6252, -5.0200, 0.5200), (2.6364, -5.0336, 0.5200), (2.6500, -5.0448, 0.5200), (2.6656, -5.0531, 0.5200), (2.6824, -5.0583, 0.5200), (2.7000, -5.0600, 0.5200), (3.3700, -5.0600, 0.5200), (3.3876, -5.0583, 0.5200), (3.4044, -5.0531, 0.5200), (3.4200, -5.0448, 0.5200), (3.4336, -5.0336, 0.5200), (3.4448, -5.0200, 0.5200), (3.4531, -5.0044, 0.5200), (3.4583, -4.9876, 0.5200), (3.4600, -4.9700, 0.5200), (3.4600, -4.9500, 0.8000), (3.4583, -4.9324, 0.8000), (3.4531, -4.9156, 0.8000), (3.4448, -4.9000, 0.8000), (3.4336, -4.8864, 0.8000), (3.4200, -4.8752, 0.8000), (3.4044, -4.8669, 0.8000), (3.3876, -4.8617, 0.8000), (3.3700, -4.8600, 0.8000), (2.7000, -4.8600, 0.8000), (2.6824, -4.8617, 0.8000), (2.6656, -4.8669, 0.8000), (2.6500, -4.8752, 0.8000), (2.6364, -4.8864, 0.8000), (2.6252, -4.9000, 0.8000), (2.6169, -4.9156, 0.8000), (2.6117, -4.9324, 0.8000), (2.6100, -4.9500, 0.8000), (2.6100, -4.9700, 0.8000), (2.6117, -4.9876, 0.8000), (2.6169, -5.0044, 0.8000), (2.6252, -5.0200, 0.8000), (2.6364, -5.0336, 0.8000), (2.6500, -5.0448, 0.8000), (2.6656, -5.0531, 0.8000), (2.6824, -5.0583, 0.8000), (2.7000, -5.0600, 0.8000), (3.3700, -5.0600, 0.8000), (3.3876, -5.0583, 0.8000), (3.4044, -5.0531, 0.8000), (3.4200, -5.0448, 0.8000), (3.4336, -5.0336, 0.8000), (3.4448, -5.0200, 0.8000), (3.4531, -5.0044, 0.8000), (3.4583, -4.9876, 0.8000), (3.4600, -4.9700, 0.8000)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["Bed_Linen"])
    _add_raw_mesh_2f("2F_MBR_Bed_Pillow_R", [(4.3700, -4.9500, 0.5200), (4.3683, -4.9324, 0.5200), (4.3631, -4.9156, 0.5200), (4.3548, -4.9000, 0.5200), (4.3436, -4.8864, 0.5200), (4.3300, -4.8752, 0.5200), (4.3144, -4.8669, 0.5200), (4.2976, -4.8617, 0.5200), (4.2800, -4.8600, 0.5200), (3.6100, -4.8600, 0.5200), (3.5924, -4.8617, 0.5200), (3.5756, -4.8669, 0.5200), (3.5600, -4.8752, 0.5200), (3.5464, -4.8864, 0.5200), (3.5352, -4.9000, 0.5200), (3.5269, -4.9156, 0.5200), (3.5217, -4.9324, 0.5200), (3.5200, -4.9500, 0.5200), (3.5200, -4.9700, 0.5200), (3.5217, -4.9876, 0.5200), (3.5269, -5.0044, 0.5200), (3.5352, -5.0200, 0.5200), (3.5464, -5.0336, 0.5200), (3.5600, -5.0448, 0.5200), (3.5756, -5.0531, 0.5200), (3.5924, -5.0583, 0.5200), (3.6100, -5.0600, 0.5200), (4.2800, -5.0600, 0.5200), (4.2976, -5.0583, 0.5200), (4.3144, -5.0531, 0.5200), (4.3300, -5.0448, 0.5200), (4.3436, -5.0336, 0.5200), (4.3548, -5.0200, 0.5200), (4.3631, -5.0044, 0.5200), (4.3683, -4.9876, 0.5200), (4.3700, -4.9700, 0.5200), (4.3700, -4.9500, 0.8000), (4.3683, -4.9324, 0.8000), (4.3631, -4.9156, 0.8000), (4.3548, -4.9000, 0.8000), (4.3436, -4.8864, 0.8000), (4.3300, -4.8752, 0.8000), (4.3144, -4.8669, 0.8000), (4.2976, -4.8617, 0.8000), (4.2800, -4.8600, 0.8000), (3.6100, -4.8600, 0.8000), (3.5924, -4.8617, 0.8000), (3.5756, -4.8669, 0.8000), (3.5600, -4.8752, 0.8000), (3.5464, -4.8864, 0.8000), (3.5352, -4.9000, 0.8000), (3.5269, -4.9156, 0.8000), (3.5217, -4.9324, 0.8000), (3.5200, -4.9500, 0.8000), (3.5200, -4.9700, 0.8000), (3.5217, -4.9876, 0.8000), (3.5269, -5.0044, 0.8000), (3.5352, -5.0200, 0.8000), (3.5464, -5.0336, 0.8000), (3.5600, -5.0448, 0.8000), (3.5756, -5.0531, 0.8000), (3.5924, -5.0583, 0.8000), (3.6100, -5.0600, 0.8000), (4.2800, -5.0600, 0.8000), (4.2976, -5.0583, 0.8000), (4.3144, -5.0531, 0.8000), (4.3300, -5.0448, 0.8000), (4.3436, -5.0336, 0.8000), (4.3548, -5.0200, 0.8000), (4.3631, -5.0044, 0.8000), (4.3683, -4.9876, 0.8000), (4.3700, -4.9700, 0.8000)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["Bed_Linen"])
    _add_raw_mesh_2f("2F_MBR_Bed_Pillow_Accent", [(3.8100, -4.8000, 0.5200), (3.8088, -4.7883, 0.5200), (3.8054, -4.7770, 0.5200), (3.7999, -4.7667, 0.5200), (3.7924, -4.7576, 0.5200), (3.7833, -4.7501, 0.5200), (3.7730, -4.7446, 0.5200), (3.7617, -4.7412, 0.5200), (3.7500, -4.7400, 0.5200), (3.2300, -4.7400, 0.5200), (3.2183, -4.7412, 0.5200), (3.2070, -4.7446, 0.5200), (3.1967, -4.7501, 0.5200), (3.1876, -4.7576, 0.5200), (3.1801, -4.7667, 0.5200), (3.1746, -4.7770, 0.5200), (3.1712, -4.7883, 0.5200), (3.1700, -4.8000, 0.5200), (3.1700, -4.8200, 0.5200), (3.1712, -4.8317, 0.5200), (3.1746, -4.8430, 0.5200), (3.1801, -4.8533, 0.5200), (3.1876, -4.8624, 0.5200), (3.1967, -4.8699, 0.5200), (3.2070, -4.8754, 0.5200), (3.2183, -4.8788, 0.5200), (3.2300, -4.8800, 0.5200), (3.7500, -4.8800, 0.5200), (3.7617, -4.8788, 0.5200), (3.7730, -4.8754, 0.5200), (3.7833, -4.8699, 0.5200), (3.7924, -4.8624, 0.5200), (3.7999, -4.8533, 0.5200), (3.8054, -4.8430, 0.5200), (3.8088, -4.8317, 0.5200), (3.8100, -4.8200, 0.5200), (3.8100, -4.8000, 0.7600), (3.8088, -4.7883, 0.7600), (3.8054, -4.7770, 0.7600), (3.7999, -4.7667, 0.7600), (3.7924, -4.7576, 0.7600), (3.7833, -4.7501, 0.7600), (3.7730, -4.7446, 0.7600), (3.7617, -4.7412, 0.7600), (3.7500, -4.7400, 0.7600), (3.2300, -4.7400, 0.7600), (3.2183, -4.7412, 0.7600), (3.2070, -4.7446, 0.7600), (3.1967, -4.7501, 0.7600), (3.1876, -4.7576, 0.7600), (3.1801, -4.7667, 0.7600), (3.1746, -4.7770, 0.7600), (3.1712, -4.7883, 0.7600), (3.1700, -4.8000, 0.7600), (3.1700, -4.8200, 0.7600), (3.1712, -4.8317, 0.7600), (3.1746, -4.8430, 0.7600), (3.1801, -4.8533, 0.7600), (3.1876, -4.8624, 0.7600), (3.1967, -4.8699, 0.7600), (3.2070, -4.8754, 0.7600), (3.2183, -4.8788, 0.7600), (3.2300, -4.8800, 0.7600), (3.7500, -4.8800, 0.7600), (3.7617, -4.8788, 0.7600), (3.7730, -4.8754, 0.7600), (3.7833, -4.8699, 0.7600), (3.7924, -4.8624, 0.7600), (3.7999, -4.8533, 0.7600), (3.8054, -4.8430, 0.7600), (3.8088, -4.8317, 0.7600), (3.8100, -4.8200, 0.7600)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["Bed_Throw"])
    _add_raw_mesh_2f("2F_MBR_Bed_Headboard", [(2.4500, -5.2600, 0.1200), (2.4500, -5.2600, 0.8500), (2.5020, -5.2600, 1.1014), (2.5540, -5.2600, 1.1119), (2.6060, -5.2600, 1.1225), (2.6580, -5.2600, 1.1327), (2.7100, -5.2600, 1.1423), (2.7620, -5.2600, 1.1507), (2.8140, -5.2600, 1.1577), (2.8660, -5.2600, 1.1629), (2.9180, -5.2600, 1.1659), (2.9700, -5.2600, 1.1667), (3.0220, -5.2600, 1.1651), (3.0740, -5.2600, 1.1609), (3.1260, -5.2600, 1.1544), (3.1780, -5.2600, 1.1455), (3.2300, -5.2600, 1.1345), (3.2820, -5.2600, 1.1217), (3.3340, -5.2600, 1.1076), (3.3860, -5.2600, 1.0925), (3.4380, -5.2600, 1.0769), (3.4900, -5.2600, 1.0613), (3.5420, -5.2600, 1.0462), (3.5940, -5.2600, 1.0321), (3.6460, -5.2600, 1.0194), (3.6980, -5.2600, 1.0085), (3.7500, -5.2600, 0.9998), (3.8020, -5.2600, 0.9935), (3.8540, -5.2600, 0.9896), (3.9060, -5.2600, 0.9884), (3.9580, -5.2600, 0.9896), (4.0100, -5.2600, 0.9933), (4.0620, -5.2600, 0.9991), (4.1140, -5.2600, 1.0068), (4.1660, -5.2600, 1.0161), (4.2180, -5.2600, 1.0265), (4.2700, -5.2600, 1.0377), (4.3220, -5.2600, 1.0492), (4.3740, -5.2600, 1.0607), (4.4260, -5.2600, 1.0717), (4.4780, -5.2600, 1.0820), (4.5300, -5.2600, 0.8500), (4.5300, -5.2600, 0.1200), (2.4500, -5.1300, 0.1200), (2.4500, -5.1300, 0.8500), (2.5020, -5.1300, 1.1014), (2.5540, -5.1300, 1.1119), (2.6060, -5.1300, 1.1225), (2.6580, -5.1300, 1.1327), (2.7100, -5.1300, 1.1423), (2.7620, -5.1300, 1.1507), (2.8140, -5.1300, 1.1577), (2.8660, -5.1300, 1.1629), (2.9180, -5.1300, 1.1659), (2.9700, -5.1300, 1.1667), (3.0220, -5.1300, 1.1651), (3.0740, -5.1300, 1.1609), (3.1260, -5.1300, 1.1544), (3.1780, -5.1300, 1.1455), (3.2300, -5.1300, 1.1345), (3.2820, -5.1300, 1.1217), (3.3340, -5.1300, 1.1076), (3.3860, -5.1300, 1.0925), (3.4380, -5.1300, 1.0769), (3.4900, -5.1300, 1.0613), (3.5420, -5.1300, 1.0462), (3.5940, -5.1300, 1.0321), (3.6460, -5.1300, 1.0194), (3.6980, -5.1300, 1.0085), (3.7500, -5.1300, 0.9998), (3.8020, -5.1300, 0.9935), (3.8540, -5.1300, 0.9896), (3.9060, -5.1300, 0.9884), (3.9580, -5.1300, 0.9896), (4.0100, -5.1300, 0.9933), (4.0620, -5.1300, 0.9991), (4.1140, -5.1300, 1.0068), (4.1660, -5.1300, 1.0161), (4.2180, -5.1300, 1.0265), (4.2700, -5.1300, 1.0377), (4.3220, -5.1300, 1.0492), (4.3740, -5.1300, 1.0607), (4.4260, -5.1300, 1.0717), (4.4780, -5.1300, 1.0820), (4.5300, -5.1300, 0.8500), (4.5300, -5.1300, 0.1200)], [(42, 41, 40, 39, 38, 37, 36, 35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85), (41, 42, 85, 84), (40, 41, 84, 83), (39, 40, 83, 82), (38, 39, 82, 81), (37, 38, 81, 80), (36, 37, 80, 79), (35, 36, 79, 78), (34, 35, 78, 77), (33, 34, 77, 76), (32, 33, 76, 75), (31, 32, 75, 74), (30, 31, 74, 73), (29, 30, 73, 72), (28, 29, 72, 71), (27, 28, 71, 70), (26, 27, 70, 69), (25, 26, 69, 68), (24, 25, 68, 67), (23, 24, 67, 66), (22, 23, 66, 65), (21, 22, 65, 64), (20, 21, 64, 63), (19, 20, 63, 62), (18, 19, 62, 61), (17, 18, 61, 60), (16, 17, 60, 59), (15, 16, 59, 58), (14, 15, 58, 57), (13, 14, 57, 56), (12, 13, 56, 55), (11, 12, 55, 54), (10, 11, 54, 53), (9, 10, 53, 52), (8, 9, 52, 51), (7, 8, 51, 50), (6, 7, 50, 49), (5, 6, 49, 48), (4, 5, 48, 47), (3, 4, 47, 46), (2, 3, 46, 45), (1, 2, 45, 44), (0, 1, 44, 43), (42, 0, 43, 85)], MATS["Bed_Linen"])
    _add_raw_mesh_2f("2F_MBR_Night_W_Plinth", [(2.3150, -4.9900, 0.0000), (2.3121, -4.9607, 0.0000), (2.3036, -4.9326, 0.0000), (2.2897, -4.9067, 0.0000), (2.2711, -4.8839, 0.0000), (2.2483, -4.8653, 0.0000), (2.2224, -4.8514, 0.0000), (2.1943, -4.8429, 0.0000), (2.1650, -4.8400, 0.0000), (1.9850, -4.8400, 0.0000), (1.9557, -4.8429, 0.0000), (1.9276, -4.8514, 0.0000), (1.9017, -4.8653, 0.0000), (1.8789, -4.8839, 0.0000), (1.8603, -4.9067, 0.0000), (1.8464, -4.9326, 0.0000), (1.8379, -4.9607, 0.0000), (1.8350, -4.9900, 0.0000), (1.8350, -5.0700, 0.0000), (1.8379, -5.0993, 0.0000), (1.8464, -5.1274, 0.0000), (1.8603, -5.1533, 0.0000), (1.8789, -5.1761, 0.0000), (1.9017, -5.1947, 0.0000), (1.9276, -5.2086, 0.0000), (1.9557, -5.2171, 0.0000), (1.9850, -5.2200, 0.0000), (2.1650, -5.2200, 0.0000), (2.1943, -5.2171, 0.0000), (2.2224, -5.2086, 0.0000), (2.2483, -5.1947, 0.0000), (2.2711, -5.1761, 0.0000), (2.2897, -5.1533, 0.0000), (2.3036, -5.1274, 0.0000), (2.3121, -5.0993, 0.0000), (2.3150, -5.0700, 0.0000), (2.3150, -4.9900, 0.0800), (2.3121, -4.9607, 0.0800), (2.3036, -4.9326, 0.0800), (2.2897, -4.9067, 0.0800), (2.2711, -4.8839, 0.0800), (2.2483, -4.8653, 0.0800), (2.2224, -4.8514, 0.0800), (2.1943, -4.8429, 0.0800), (2.1650, -4.8400, 0.0800), (1.9850, -4.8400, 0.0800), (1.9557, -4.8429, 0.0800), (1.9276, -4.8514, 0.0800), (1.9017, -4.8653, 0.0800), (1.8789, -4.8839, 0.0800), (1.8603, -4.9067, 0.0800), (1.8464, -4.9326, 0.0800), (1.8379, -4.9607, 0.0800), (1.8350, -4.9900, 0.0800), (1.8350, -5.0700, 0.0800), (1.8379, -5.0993, 0.0800), (1.8464, -5.1274, 0.0800), (1.8603, -5.1533, 0.0800), (1.8789, -5.1761, 0.0800), (1.9017, -5.1947, 0.0800), (1.9276, -5.2086, 0.0800), (1.9557, -5.2171, 0.0800), (1.9850, -5.2200, 0.0800), (2.1650, -5.2200, 0.0800), (2.1943, -5.2171, 0.0800), (2.2224, -5.2086, 0.0800), (2.2483, -5.1947, 0.0800), (2.2711, -5.1761, 0.0800), (2.2897, -5.1533, 0.0800), (2.3036, -5.1274, 0.0800), (2.3121, -5.0993, 0.0800), (2.3150, -5.0700, 0.0800)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["OLO_Cab_Greige"])
    _add_raw_mesh_2f("2F_MBR_Night_W_Drawer1", [(2.3550, -4.9900, 0.0800), (2.3513, -4.9529, 0.0800), (2.3405, -4.9173, 0.0800), (2.3230, -4.8844, 0.0800), (2.2994, -4.8556, 0.0800), (2.2706, -4.8320, 0.0800), (2.2377, -4.8145, 0.0800), (2.2021, -4.8037, 0.0800), (2.1650, -4.8000, 0.0800), (1.9850, -4.8000, 0.0800), (1.9479, -4.8037, 0.0800), (1.9123, -4.8145, 0.0800), (1.8794, -4.8320, 0.0800), (1.8506, -4.8556, 0.0800), (1.8270, -4.8844, 0.0800), (1.8095, -4.9173, 0.0800), (1.7987, -4.9529, 0.0800), (1.7950, -4.9900, 0.0800), (1.7950, -5.0600, 0.0800), (1.7987, -5.0971, 0.0800), (1.8095, -5.1327, 0.0800), (1.8270, -5.1656, 0.0800), (1.8506, -5.1944, 0.0800), (1.8794, -5.2180, 0.0800), (1.9123, -5.2355, 0.0800), (1.9479, -5.2463, 0.0800), (1.9850, -5.2500, 0.0800), (2.1650, -5.2500, 0.0800), (2.2021, -5.2463, 0.0800), (2.2377, -5.2355, 0.0800), (2.2706, -5.2180, 0.0800), (2.2994, -5.1944, 0.0800), (2.3230, -5.1656, 0.0800), (2.3405, -5.1327, 0.0800), (2.3513, -5.0971, 0.0800), (2.3550, -5.0600, 0.0800), (2.3550, -4.9900, 0.2800), (2.3513, -4.9529, 0.2800), (2.3405, -4.9173, 0.2800), (2.3230, -4.8844, 0.2800), (2.2994, -4.8556, 0.2800), (2.2706, -4.8320, 0.2800), (2.2377, -4.8145, 0.2800), (2.2021, -4.8037, 0.2800), (2.1650, -4.8000, 0.2800), (1.9850, -4.8000, 0.2800), (1.9479, -4.8037, 0.2800), (1.9123, -4.8145, 0.2800), (1.8794, -4.8320, 0.2800), (1.8506, -4.8556, 0.2800), (1.8270, -4.8844, 0.2800), (1.8095, -4.9173, 0.2800), (1.7987, -4.9529, 0.2800), (1.7950, -4.9900, 0.2800), (1.7950, -5.0600, 0.2800), (1.7987, -5.0971, 0.2800), (1.8095, -5.1327, 0.2800), (1.8270, -5.1656, 0.2800), (1.8506, -5.1944, 0.2800), (1.8794, -5.2180, 0.2800), (1.9123, -5.2355, 0.2800), (1.9479, -5.2463, 0.2800), (1.9850, -5.2500, 0.2800), (2.1650, -5.2500, 0.2800), (2.2021, -5.2463, 0.2800), (2.2377, -5.2355, 0.2800), (2.2706, -5.2180, 0.2800), (2.2994, -5.1944, 0.2800), (2.3230, -5.1656, 0.2800), (2.3405, -5.1327, 0.2800), (2.3513, -5.0971, 0.2800), (2.3550, -5.0600, 0.2800)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["OLO_Cab_White"])
    _add_raw_mesh_2f("2F_MBR_Night_W_Gap", [(2.3470, -4.9900, 0.2800), (2.3435, -4.9545, 0.2800), (2.3331, -4.9204, 0.2800), (2.3163, -4.8889, 0.2800), (2.2937, -4.8613, 0.2800), (2.2661, -4.8387, 0.2800), (2.2346, -4.8219, 0.2800), (2.2005, -4.8115, 0.2800), (2.1650, -4.8080, 0.2800), (1.9850, -4.8080, 0.2800), (1.9495, -4.8115, 0.2800), (1.9154, -4.8219, 0.2800), (1.8839, -4.8387, 0.2800), (1.8563, -4.8613, 0.2800), (1.8337, -4.8889, 0.2800), (1.8169, -4.9204, 0.2800), (1.8065, -4.9545, 0.2800), (1.8030, -4.9900, 0.2800), (1.8030, -5.0600, 0.2800), (1.8065, -5.0955, 0.2800), (1.8169, -5.1296, 0.2800), (1.8337, -5.1611, 0.2800), (1.8563, -5.1887, 0.2800), (1.8839, -5.2113, 0.2800), (1.9154, -5.2281, 0.2800), (1.9495, -5.2385, 0.2800), (1.9850, -5.2420, 0.2800), (2.1650, -5.2420, 0.2800), (2.2005, -5.2385, 0.2800), (2.2346, -5.2281, 0.2800), (2.2661, -5.2113, 0.2800), (2.2937, -5.1887, 0.2800), (2.3163, -5.1611, 0.2800), (2.3331, -5.1296, 0.2800), (2.3435, -5.0955, 0.2800), (2.3470, -5.0600, 0.2800), (2.3470, -4.9900, 0.2950), (2.3435, -4.9545, 0.2950), (2.3331, -4.9204, 0.2950), (2.3163, -4.8889, 0.2950), (2.2937, -4.8613, 0.2950), (2.2661, -4.8387, 0.2950), (2.2346, -4.8219, 0.2950), (2.2005, -4.8115, 0.2950), (2.1650, -4.8080, 0.2950), (1.9850, -4.8080, 0.2950), (1.9495, -4.8115, 0.2950), (1.9154, -4.8219, 0.2950), (1.8839, -4.8387, 0.2950), (1.8563, -4.8613, 0.2950), (1.8337, -4.8889, 0.2950), (1.8169, -4.9204, 0.2950), (1.8065, -4.9545, 0.2950), (1.8030, -4.9900, 0.2950), (1.8030, -5.0600, 0.2950), (1.8065, -5.0955, 0.2950), (1.8169, -5.1296, 0.2950), (1.8337, -5.1611, 0.2950), (1.8563, -5.1887, 0.2950), (1.8839, -5.2113, 0.2950), (1.9154, -5.2281, 0.2950), (1.9495, -5.2385, 0.2950), (1.9850, -5.2420, 0.2950), (2.1650, -5.2420, 0.2950), (2.2005, -5.2385, 0.2950), (2.2346, -5.2281, 0.2950), (2.2661, -5.2113, 0.2950), (2.2937, -5.1887, 0.2950), (2.3163, -5.1611, 0.2950), (2.3331, -5.1296, 0.2950), (2.3435, -5.0955, 0.2950), (2.3470, -5.0600, 0.2950)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["OLO_Cab_Greige"])
    _add_raw_mesh_2f("2F_MBR_Night_W_Drawer2", [(2.3550, -4.9900, 0.2950), (2.3513, -4.9529, 0.2950), (2.3405, -4.9173, 0.2950), (2.3230, -4.8844, 0.2950), (2.2994, -4.8556, 0.2950), (2.2706, -4.8320, 0.2950), (2.2377, -4.8145, 0.2950), (2.2021, -4.8037, 0.2950), (2.1650, -4.8000, 0.2950), (1.9850, -4.8000, 0.2950), (1.9479, -4.8037, 0.2950), (1.9123, -4.8145, 0.2950), (1.8794, -4.8320, 0.2950), (1.8506, -4.8556, 0.2950), (1.8270, -4.8844, 0.2950), (1.8095, -4.9173, 0.2950), (1.7987, -4.9529, 0.2950), (1.7950, -4.9900, 0.2950), (1.7950, -5.0600, 0.2950), (1.7987, -5.0971, 0.2950), (1.8095, -5.1327, 0.2950), (1.8270, -5.1656, 0.2950), (1.8506, -5.1944, 0.2950), (1.8794, -5.2180, 0.2950), (1.9123, -5.2355, 0.2950), (1.9479, -5.2463, 0.2950), (1.9850, -5.2500, 0.2950), (2.1650, -5.2500, 0.2950), (2.2021, -5.2463, 0.2950), (2.2377, -5.2355, 0.2950), (2.2706, -5.2180, 0.2950), (2.2994, -5.1944, 0.2950), (2.3230, -5.1656, 0.2950), (2.3405, -5.1327, 0.2950), (2.3513, -5.0971, 0.2950), (2.3550, -5.0600, 0.2950), (2.3550, -4.9900, 0.5000), (2.3513, -4.9529, 0.5000), (2.3405, -4.9173, 0.5000), (2.3230, -4.8844, 0.5000), (2.2994, -4.8556, 0.5000), (2.2706, -4.8320, 0.5000), (2.2377, -4.8145, 0.5000), (2.2021, -4.8037, 0.5000), (2.1650, -4.8000, 0.5000), (1.9850, -4.8000, 0.5000), (1.9479, -4.8037, 0.5000), (1.9123, -4.8145, 0.5000), (1.8794, -4.8320, 0.5000), (1.8506, -4.8556, 0.5000), (1.8270, -4.8844, 0.5000), (1.8095, -4.9173, 0.5000), (1.7987, -4.9529, 0.5000), (1.7950, -4.9900, 0.5000), (1.7950, -5.0600, 0.5000), (1.7987, -5.0971, 0.5000), (1.8095, -5.1327, 0.5000), (1.8270, -5.1656, 0.5000), (1.8506, -5.1944, 0.5000), (1.8794, -5.2180, 0.5000), (1.9123, -5.2355, 0.5000), (1.9479, -5.2463, 0.5000), (1.9850, -5.2500, 0.5000), (2.1650, -5.2500, 0.5000), (2.2021, -5.2463, 0.5000), (2.2377, -5.2355, 0.5000), (2.2706, -5.2180, 0.5000), (2.2994, -5.1944, 0.5000), (2.3230, -5.1656, 0.5000), (2.3405, -5.1327, 0.5000), (2.3513, -5.0971, 0.5000), (2.3550, -5.0600, 0.5000)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["OLO_Cab_White"])
    _add_raw_mesh_2f("2F_MBR_Night_W_Top", [(2.3600, -4.9900, 0.5000), (2.3563, -4.9520, 0.5000), (2.3452, -4.9154, 0.5000), (2.3271, -4.8817, 0.5000), (2.3029, -4.8521, 0.5000), (2.2733, -4.8279, 0.5000), (2.2396, -4.8098, 0.5000), (2.2030, -4.7987, 0.5000), (2.1650, -4.7950, 0.5000), (1.9850, -4.7950, 0.5000), (1.9470, -4.7987, 0.5000), (1.9104, -4.8098, 0.5000), (1.8767, -4.8279, 0.5000), (1.8471, -4.8521, 0.5000), (1.8229, -4.8817, 0.5000), (1.8048, -4.9154, 0.5000), (1.7937, -4.9520, 0.5000), (1.7900, -4.9900, 0.5000), (1.7900, -5.0600, 0.5000), (1.7937, -5.0980, 0.5000), (1.8048, -5.1346, 0.5000), (1.8229, -5.1683, 0.5000), (1.8471, -5.1979, 0.5000), (1.8767, -5.2221, 0.5000), (1.9104, -5.2402, 0.5000), (1.9470, -5.2513, 0.5000), (1.9850, -5.2550, 0.5000), (2.1650, -5.2550, 0.5000), (2.2030, -5.2513, 0.5000), (2.2396, -5.2402, 0.5000), (2.2733, -5.2221, 0.5000), (2.3029, -5.1979, 0.5000), (2.3271, -5.1683, 0.5000), (2.3452, -5.1346, 0.5000), (2.3563, -5.0980, 0.5000), (2.3600, -5.0600, 0.5000), (2.3600, -4.9900, 0.5200), (2.3563, -4.9520, 0.5200), (2.3452, -4.9154, 0.5200), (2.3271, -4.8817, 0.5200), (2.3029, -4.8521, 0.5200), (2.2733, -4.8279, 0.5200), (2.2396, -4.8098, 0.5200), (2.2030, -4.7987, 0.5200), (2.1650, -4.7950, 0.5200), (1.9850, -4.7950, 0.5200), (1.9470, -4.7987, 0.5200), (1.9104, -4.8098, 0.5200), (1.8767, -4.8279, 0.5200), (1.8471, -4.8521, 0.5200), (1.8229, -4.8817, 0.5200), (1.8048, -4.9154, 0.5200), (1.7937, -4.9520, 0.5200), (1.7900, -4.9900, 0.5200), (1.7900, -5.0600, 0.5200), (1.7937, -5.0980, 0.5200), (1.8048, -5.1346, 0.5200), (1.8229, -5.1683, 0.5200), (1.8471, -5.1979, 0.5200), (1.8767, -5.2221, 0.5200), (1.9104, -5.2402, 0.5200), (1.9470, -5.2513, 0.5200), (1.9850, -5.2550, 0.5200), (2.1650, -5.2550, 0.5200), (2.2030, -5.2513, 0.5200), (2.2396, -5.2402, 0.5200), (2.2733, -5.2221, 0.5200), (2.3029, -5.1979, 0.5200), (2.3271, -5.1683, 0.5200), (2.3452, -5.1346, 0.5200), (2.3563, -5.0980, 0.5200), (2.3600, -5.0600, 0.5200)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["OLO_Cab_White"])
    _add_raw_mesh_2f("2F_MBR_Night_E_Plinth", [(5.1550, -4.9600, 0.0000), (5.1521, -4.9307, 0.0000), (5.1436, -4.9026, 0.0000), (5.1297, -4.8767, 0.0000), (5.1111, -4.8539, 0.0000), (5.0883, -4.8353, 0.0000), (5.0624, -4.8214, 0.0000), (5.0343, -4.8129, 0.0000), (5.0050, -4.8100, 0.0000), (4.8250, -4.8100, 0.0000), (4.7957, -4.8129, 0.0000), (4.7676, -4.8214, 0.0000), (4.7417, -4.8353, 0.0000), (4.7189, -4.8539, 0.0000), (4.7003, -4.8767, 0.0000), (4.6864, -4.9026, 0.0000), (4.6779, -4.9307, 0.0000), (4.6750, -4.9600, 0.0000), (4.6750, -5.0400, 0.0000), (4.6779, -5.0693, 0.0000), (4.6864, -5.0974, 0.0000), (4.7003, -5.1233, 0.0000), (4.7189, -5.1461, 0.0000), (4.7417, -5.1647, 0.0000), (4.7676, -5.1786, 0.0000), (4.7957, -5.1871, 0.0000), (4.8250, -5.1900, 0.0000), (5.0050, -5.1900, 0.0000), (5.0343, -5.1871, 0.0000), (5.0624, -5.1786, 0.0000), (5.0883, -5.1647, 0.0000), (5.1111, -5.1461, 0.0000), (5.1297, -5.1233, 0.0000), (5.1436, -5.0974, 0.0000), (5.1521, -5.0693, 0.0000), (5.1550, -5.0400, 0.0000), (5.1550, -4.9600, 0.0800), (5.1521, -4.9307, 0.0800), (5.1436, -4.9026, 0.0800), (5.1297, -4.8767, 0.0800), (5.1111, -4.8539, 0.0800), (5.0883, -4.8353, 0.0800), (5.0624, -4.8214, 0.0800), (5.0343, -4.8129, 0.0800), (5.0050, -4.8100, 0.0800), (4.8250, -4.8100, 0.0800), (4.7957, -4.8129, 0.0800), (4.7676, -4.8214, 0.0800), (4.7417, -4.8353, 0.0800), (4.7189, -4.8539, 0.0800), (4.7003, -4.8767, 0.0800), (4.6864, -4.9026, 0.0800), (4.6779, -4.9307, 0.0800), (4.6750, -4.9600, 0.0800), (4.6750, -5.0400, 0.0800), (4.6779, -5.0693, 0.0800), (4.6864, -5.0974, 0.0800), (4.7003, -5.1233, 0.0800), (4.7189, -5.1461, 0.0800), (4.7417, -5.1647, 0.0800), (4.7676, -5.1786, 0.0800), (4.7957, -5.1871, 0.0800), (4.8250, -5.1900, 0.0800), (5.0050, -5.1900, 0.0800), (5.0343, -5.1871, 0.0800), (5.0624, -5.1786, 0.0800), (5.0883, -5.1647, 0.0800), (5.1111, -5.1461, 0.0800), (5.1297, -5.1233, 0.0800), (5.1436, -5.0974, 0.0800), (5.1521, -5.0693, 0.0800), (5.1550, -5.0400, 0.0800)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["OLO_Cab_Greige"])
    _add_raw_mesh_2f("2F_MBR_Night_E_Drawer1", [(5.1950, -4.9600, 0.0800), (5.1913, -4.9229, 0.0800), (5.1805, -4.8873, 0.0800), (5.1630, -4.8544, 0.0800), (5.1394, -4.8256, 0.0800), (5.1106, -4.8020, 0.0800), (5.0777, -4.7845, 0.0800), (5.0421, -4.7737, 0.0800), (5.0050, -4.7700, 0.0800), (4.8250, -4.7700, 0.0800), (4.7879, -4.7737, 0.0800), (4.7523, -4.7845, 0.0800), (4.7194, -4.8020, 0.0800), (4.6906, -4.8256, 0.0800), (4.6670, -4.8544, 0.0800), (4.6495, -4.8873, 0.0800), (4.6387, -4.9229, 0.0800), (4.6350, -4.9600, 0.0800), (4.6350, -5.0300, 0.0800), (4.6387, -5.0671, 0.0800), (4.6495, -5.1027, 0.0800), (4.6670, -5.1356, 0.0800), (4.6906, -5.1644, 0.0800), (4.7194, -5.1880, 0.0800), (4.7523, -5.2055, 0.0800), (4.7879, -5.2163, 0.0800), (4.8250, -5.2200, 0.0800), (5.0050, -5.2200, 0.0800), (5.0421, -5.2163, 0.0800), (5.0777, -5.2055, 0.0800), (5.1106, -5.1880, 0.0800), (5.1394, -5.1644, 0.0800), (5.1630, -5.1356, 0.0800), (5.1805, -5.1027, 0.0800), (5.1913, -5.0671, 0.0800), (5.1950, -5.0300, 0.0800), (5.1950, -4.9600, 0.2800), (5.1913, -4.9229, 0.2800), (5.1805, -4.8873, 0.2800), (5.1630, -4.8544, 0.2800), (5.1394, -4.8256, 0.2800), (5.1106, -4.8020, 0.2800), (5.0777, -4.7845, 0.2800), (5.0421, -4.7737, 0.2800), (5.0050, -4.7700, 0.2800), (4.8250, -4.7700, 0.2800), (4.7879, -4.7737, 0.2800), (4.7523, -4.7845, 0.2800), (4.7194, -4.8020, 0.2800), (4.6906, -4.8256, 0.2800), (4.6670, -4.8544, 0.2800), (4.6495, -4.8873, 0.2800), (4.6387, -4.9229, 0.2800), (4.6350, -4.9600, 0.2800), (4.6350, -5.0300, 0.2800), (4.6387, -5.0671, 0.2800), (4.6495, -5.1027, 0.2800), (4.6670, -5.1356, 0.2800), (4.6906, -5.1644, 0.2800), (4.7194, -5.1880, 0.2800), (4.7523, -5.2055, 0.2800), (4.7879, -5.2163, 0.2800), (4.8250, -5.2200, 0.2800), (5.0050, -5.2200, 0.2800), (5.0421, -5.2163, 0.2800), (5.0777, -5.2055, 0.2800), (5.1106, -5.1880, 0.2800), (5.1394, -5.1644, 0.2800), (5.1630, -5.1356, 0.2800), (5.1805, -5.1027, 0.2800), (5.1913, -5.0671, 0.2800), (5.1950, -5.0300, 0.2800)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["OLO_Cab_White"])
    _add_raw_mesh_2f("2F_MBR_Night_E_Gap", [(5.1870, -4.9600, 0.2800), (5.1835, -4.9245, 0.2800), (5.1731, -4.8904, 0.2800), (5.1563, -4.8589, 0.2800), (5.1337, -4.8313, 0.2800), (5.1061, -4.8087, 0.2800), (5.0746, -4.7919, 0.2800), (5.0405, -4.7815, 0.2800), (5.0050, -4.7780, 0.2800), (4.8250, -4.7780, 0.2800), (4.7895, -4.7815, 0.2800), (4.7554, -4.7919, 0.2800), (4.7239, -4.8087, 0.2800), (4.6963, -4.8313, 0.2800), (4.6737, -4.8589, 0.2800), (4.6569, -4.8904, 0.2800), (4.6465, -4.9245, 0.2800), (4.6430, -4.9600, 0.2800), (4.6430, -5.0300, 0.2800), (4.6465, -5.0655, 0.2800), (4.6569, -5.0996, 0.2800), (4.6737, -5.1311, 0.2800), (4.6963, -5.1587, 0.2800), (4.7239, -5.1813, 0.2800), (4.7554, -5.1981, 0.2800), (4.7895, -5.2085, 0.2800), (4.8250, -5.2120, 0.2800), (5.0050, -5.2120, 0.2800), (5.0405, -5.2085, 0.2800), (5.0746, -5.1981, 0.2800), (5.1061, -5.1813, 0.2800), (5.1337, -5.1587, 0.2800), (5.1563, -5.1311, 0.2800), (5.1731, -5.0996, 0.2800), (5.1835, -5.0655, 0.2800), (5.1870, -5.0300, 0.2800), (5.1870, -4.9600, 0.2950), (5.1835, -4.9245, 0.2950), (5.1731, -4.8904, 0.2950), (5.1563, -4.8589, 0.2950), (5.1337, -4.8313, 0.2950), (5.1061, -4.8087, 0.2950), (5.0746, -4.7919, 0.2950), (5.0405, -4.7815, 0.2950), (5.0050, -4.7780, 0.2950), (4.8250, -4.7780, 0.2950), (4.7895, -4.7815, 0.2950), (4.7554, -4.7919, 0.2950), (4.7239, -4.8087, 0.2950), (4.6963, -4.8313, 0.2950), (4.6737, -4.8589, 0.2950), (4.6569, -4.8904, 0.2950), (4.6465, -4.9245, 0.2950), (4.6430, -4.9600, 0.2950), (4.6430, -5.0300, 0.2950), (4.6465, -5.0655, 0.2950), (4.6569, -5.0996, 0.2950), (4.6737, -5.1311, 0.2950), (4.6963, -5.1587, 0.2950), (4.7239, -5.1813, 0.2950), (4.7554, -5.1981, 0.2950), (4.7895, -5.2085, 0.2950), (4.8250, -5.2120, 0.2950), (5.0050, -5.2120, 0.2950), (5.0405, -5.2085, 0.2950), (5.0746, -5.1981, 0.2950), (5.1061, -5.1813, 0.2950), (5.1337, -5.1587, 0.2950), (5.1563, -5.1311, 0.2950), (5.1731, -5.0996, 0.2950), (5.1835, -5.0655, 0.2950), (5.1870, -5.0300, 0.2950)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["OLO_Cab_Greige"])
    _add_raw_mesh_2f("2F_MBR_Night_E_Drawer2", [(5.1950, -4.9600, 0.2950), (5.1913, -4.9229, 0.2950), (5.1805, -4.8873, 0.2950), (5.1630, -4.8544, 0.2950), (5.1394, -4.8256, 0.2950), (5.1106, -4.8020, 0.2950), (5.0777, -4.7845, 0.2950), (5.0421, -4.7737, 0.2950), (5.0050, -4.7700, 0.2950), (4.8250, -4.7700, 0.2950), (4.7879, -4.7737, 0.2950), (4.7523, -4.7845, 0.2950), (4.7194, -4.8020, 0.2950), (4.6906, -4.8256, 0.2950), (4.6670, -4.8544, 0.2950), (4.6495, -4.8873, 0.2950), (4.6387, -4.9229, 0.2950), (4.6350, -4.9600, 0.2950), (4.6350, -5.0300, 0.2950), (4.6387, -5.0671, 0.2950), (4.6495, -5.1027, 0.2950), (4.6670, -5.1356, 0.2950), (4.6906, -5.1644, 0.2950), (4.7194, -5.1880, 0.2950), (4.7523, -5.2055, 0.2950), (4.7879, -5.2163, 0.2950), (4.8250, -5.2200, 0.2950), (5.0050, -5.2200, 0.2950), (5.0421, -5.2163, 0.2950), (5.0777, -5.2055, 0.2950), (5.1106, -5.1880, 0.2950), (5.1394, -5.1644, 0.2950), (5.1630, -5.1356, 0.2950), (5.1805, -5.1027, 0.2950), (5.1913, -5.0671, 0.2950), (5.1950, -5.0300, 0.2950), (5.1950, -4.9600, 0.5000), (5.1913, -4.9229, 0.5000), (5.1805, -4.8873, 0.5000), (5.1630, -4.8544, 0.5000), (5.1394, -4.8256, 0.5000), (5.1106, -4.8020, 0.5000), (5.0777, -4.7845, 0.5000), (5.0421, -4.7737, 0.5000), (5.0050, -4.7700, 0.5000), (4.8250, -4.7700, 0.5000), (4.7879, -4.7737, 0.5000), (4.7523, -4.7845, 0.5000), (4.7194, -4.8020, 0.5000), (4.6906, -4.8256, 0.5000), (4.6670, -4.8544, 0.5000), (4.6495, -4.8873, 0.5000), (4.6387, -4.9229, 0.5000), (4.6350, -4.9600, 0.5000), (4.6350, -5.0300, 0.5000), (4.6387, -5.0671, 0.5000), (4.6495, -5.1027, 0.5000), (4.6670, -5.1356, 0.5000), (4.6906, -5.1644, 0.5000), (4.7194, -5.1880, 0.5000), (4.7523, -5.2055, 0.5000), (4.7879, -5.2163, 0.5000), (4.8250, -5.2200, 0.5000), (5.0050, -5.2200, 0.5000), (5.0421, -5.2163, 0.5000), (5.0777, -5.2055, 0.5000), (5.1106, -5.1880, 0.5000), (5.1394, -5.1644, 0.5000), (5.1630, -5.1356, 0.5000), (5.1805, -5.1027, 0.5000), (5.1913, -5.0671, 0.5000), (5.1950, -5.0300, 0.5000)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["OLO_Cab_White"])
    _add_raw_mesh_2f("2F_MBR_Night_E_Top", [(5.2000, -4.9600, 0.5000), (5.1963, -4.9220, 0.5000), (5.1852, -4.8854, 0.5000), (5.1671, -4.8517, 0.5000), (5.1429, -4.8221, 0.5000), (5.1133, -4.7979, 0.5000), (5.0796, -4.7798, 0.5000), (5.0430, -4.7687, 0.5000), (5.0050, -4.7650, 0.5000), (4.8250, -4.7650, 0.5000), (4.7870, -4.7687, 0.5000), (4.7504, -4.7798, 0.5000), (4.7167, -4.7979, 0.5000), (4.6871, -4.8221, 0.5000), (4.6629, -4.8517, 0.5000), (4.6448, -4.8854, 0.5000), (4.6337, -4.9220, 0.5000), (4.6300, -4.9600, 0.5000), (4.6300, -5.0300, 0.5000), (4.6337, -5.0680, 0.5000), (4.6448, -5.1046, 0.5000), (4.6629, -5.1383, 0.5000), (4.6871, -5.1679, 0.5000), (4.7167, -5.1921, 0.5000), (4.7504, -5.2102, 0.5000), (4.7870, -5.2213, 0.5000), (4.8250, -5.2250, 0.5000), (5.0050, -5.2250, 0.5000), (5.0430, -5.2213, 0.5000), (5.0796, -5.2102, 0.5000), (5.1133, -5.1921, 0.5000), (5.1429, -5.1679, 0.5000), (5.1671, -5.1383, 0.5000), (5.1852, -5.1046, 0.5000), (5.1963, -5.0680, 0.5000), (5.2000, -5.0300, 0.5000), (5.2000, -4.9600, 0.5200), (5.1963, -4.9220, 0.5200), (5.1852, -4.8854, 0.5200), (5.1671, -4.8517, 0.5200), (5.1429, -4.8221, 0.5200), (5.1133, -4.7979, 0.5200), (5.0796, -4.7798, 0.5200), (5.0430, -4.7687, 0.5200), (5.0050, -4.7650, 0.5200), (4.8250, -4.7650, 0.5200), (4.7870, -4.7687, 0.5200), (4.7504, -4.7798, 0.5200), (4.7167, -4.7979, 0.5200), (4.6871, -4.8221, 0.5200), (4.6629, -4.8517, 0.5200), (4.6448, -4.8854, 0.5200), (4.6337, -4.9220, 0.5200), (4.6300, -4.9600, 0.5200), (4.6300, -5.0300, 0.5200), (4.6337, -5.0680, 0.5200), (4.6448, -5.1046, 0.5200), (4.6629, -5.1383, 0.5200), (4.6871, -5.1679, 0.5200), (4.7167, -5.1921, 0.5200), (4.7504, -5.2102, 0.5200), (4.7870, -5.2213, 0.5200), (4.8250, -5.2250, 0.5200), (5.0050, -5.2250, 0.5200), (5.0430, -5.2213, 0.5200), (5.0796, -5.2102, 0.5200), (5.1133, -5.1921, 0.5200), (5.1429, -5.1679, 0.5200), (5.1671, -5.1383, 0.5200), (5.1852, -5.1046, 0.5200), (5.1963, -5.0680, 0.5200), (5.2000, -5.0300, 0.5200)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["OLO_Cab_White"])
    add_box_mm("2F_MBR_Vanity_Back", 5360.0, 6620.0, -5280.0, -5250.0, z_2f + 0.0000, z_2f + 2.5000, MATS["Wall_Panel_Cream"], col_2f)
    add_box_mm("2F_MBR_Vanity_Head", 5360.0, 6620.0, -5250.0, -4998.0, z_2f + 2.4000, z_2f + 2.5000, MATS["Optical_Wood_Shadow_Base"], col_2f)
    add_uv_front_box_mm("2F_MBR_Vanity_Head_Door1", 5360.0, 5778.0, -4998.0, -4980.0, z_2f + 2.4020, z_2f + 2.4980, 0.00, 0.00 + 0.418 / 0.55, 0.0, 0.096 / 0.55, MATS["Optical_Wood_Shadow"], col_2f)
    add_uv_front_box_mm("2F_MBR_Vanity_Head_Door2", 5781.0, 6199.0, -4998.0, -4980.0, z_2f + 2.4020, z_2f + 2.4980, 0.32, 0.32 + 0.418 / 0.55, 0.0, 0.096 / 0.55, MATS["Optical_Wood_Shadow"], col_2f)
    add_uv_front_box_mm("2F_MBR_Vanity_Head_Door3", 6202.0, 6620.0, -4998.0, -4980.0, z_2f + 2.4020, z_2f + 2.4980, 0.64, 0.64 + 0.418 / 0.55, 0.0, 0.096 / 0.55, MATS["Optical_Wood_Shadow"], col_2f)
    add_box_mm("2F_MBR_Vanity_Soffit", 5360.0, 6620.0, -5280.0, -4980.0, z_2f + 2.5000, z_2f + 2.8300, MATS["Wall_Panel_Cream"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheL_SideA", 5360.0, 5385.0, -5250.0, -4980.0, z_2f + 0.8000, z_2f + 2.4000, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheL_SideB", 5655.0, 5680.0, -5250.0, -4980.0, z_2f + 0.8000, z_2f + 2.4000, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheL_Glow", 5385.0, 5655.0, -5250.0, -5235.0, z_2f + 0.8000, z_2f + 2.4000, MATS["B2_Backlit_Cream"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheL_Shelf_0", 5385.0, 5655.0, -5235.0, -4990.0, z_2f + 1.1200, z_2f + 1.1400, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheL_LED_0", 5390.0, 5650.0, -5010.0, -4995.0, z_2f + 1.1120, z_2f + 1.1200, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheL_Shelf_1", 5385.0, 5655.0, -5235.0, -4990.0, z_2f + 1.4400, z_2f + 1.4600, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheL_LED_1", 5390.0, 5650.0, -5010.0, -4995.0, z_2f + 1.4320, z_2f + 1.4400, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheL_Shelf_2", 5385.0, 5655.0, -5235.0, -4990.0, z_2f + 1.7600, z_2f + 1.7800, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheL_LED_2", 5390.0, 5650.0, -5010.0, -4995.0, z_2f + 1.7520, z_2f + 1.7600, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheL_Shelf_3", 5385.0, 5655.0, -5235.0, -4990.0, z_2f + 2.0800, z_2f + 2.1000, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheL_LED_3", 5390.0, 5650.0, -5010.0, -4995.0, z_2f + 2.0720, z_2f + 2.0800, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheR_SideA", 6300.0, 6325.0, -5250.0, -4980.0, z_2f + 0.8000, z_2f + 2.4000, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheR_SideB", 6595.0, 6620.0, -5250.0, -4980.0, z_2f + 0.8000, z_2f + 2.4000, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheR_Glow", 6325.0, 6595.0, -5250.0, -5235.0, z_2f + 0.8000, z_2f + 2.4000, MATS["B2_Backlit_Cream"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheR_Shelf_0", 6325.0, 6595.0, -5235.0, -4990.0, z_2f + 1.1200, z_2f + 1.1400, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheR_LED_0", 6330.0, 6590.0, -5010.0, -4995.0, z_2f + 1.1120, z_2f + 1.1200, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheR_Shelf_1", 6325.0, 6595.0, -5235.0, -4990.0, z_2f + 1.4400, z_2f + 1.4600, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheR_LED_1", 6330.0, 6590.0, -5010.0, -4995.0, z_2f + 1.4320, z_2f + 1.4400, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheR_Shelf_2", 6325.0, 6595.0, -5235.0, -4990.0, z_2f + 1.7600, z_2f + 1.7800, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheR_LED_2", 6330.0, 6590.0, -5010.0, -4995.0, z_2f + 1.7520, z_2f + 1.7600, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheR_Shelf_3", 6325.0, 6595.0, -5235.0, -4990.0, z_2f + 2.0800, z_2f + 2.1000, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_NicheR_LED_3", 6330.0, 6590.0, -5010.0, -4995.0, z_2f + 2.0720, z_2f + 2.0800, MATS["Warm_LED_Glow"], col_2f)
    add_box_mm("2F_MBR_Vanity_MirrorPanel", 5680.0, 6300.0, -5250.0, -5220.0, z_2f + 0.8000, z_2f + 2.4000, MATS["OLO_Cab_White"], col_2f)
    _add_raw_mesh_2f("2F_MBR_Vanity_Mirror_LED", [(5.7400, -5.2200, 1.2000), (5.7448, -5.2200, 1.1512), (5.7590, -5.2200, 1.1043), (5.7821, -5.2200, 1.0611), (5.8132, -5.2200, 1.0232), (5.8511, -5.2200, 0.9921), (5.8943, -5.2200, 0.9690), (5.9412, -5.2200, 0.9548), (5.9900, -5.2200, 0.9500), (6.0388, -5.2200, 0.9548), (6.0857, -5.2200, 0.9690), (6.1289, -5.2200, 0.9921), (6.1668, -5.2200, 1.0232), (6.1979, -5.2200, 1.0611), (6.2210, -5.2200, 1.1043), (6.2352, -5.2200, 1.1512), (6.2400, -5.2200, 1.2000), (6.2400, -5.2200, 2.2600), (6.2380, -5.2200, 2.2755), (6.2320, -5.2200, 2.2900), (6.2224, -5.2200, 2.3024), (6.2100, -5.2200, 2.3120), (6.1955, -5.2200, 2.3180), (6.1800, -5.2200, 2.3200), (5.8000, -5.2200, 2.3200), (5.7845, -5.2200, 2.3180), (5.7700, -5.2200, 2.3120), (5.7576, -5.2200, 2.3024), (5.7480, -5.2200, 2.2900), (5.7420, -5.2200, 2.2755), (5.7400, -5.2200, 2.2600), (5.7400, -5.2100, 1.2000), (5.7448, -5.2100, 1.1512), (5.7590, -5.2100, 1.1043), (5.7821, -5.2100, 1.0611), (5.8132, -5.2100, 1.0232), (5.8511, -5.2100, 0.9921), (5.8943, -5.2100, 0.9690), (5.9412, -5.2100, 0.9548), (5.9900, -5.2100, 0.9500), (6.0388, -5.2100, 0.9548), (6.0857, -5.2100, 0.9690), (6.1289, -5.2100, 0.9921), (6.1668, -5.2100, 1.0232), (6.1979, -5.2100, 1.0611), (6.2210, -5.2100, 1.1043), (6.2352, -5.2100, 1.1512), (6.2400, -5.2100, 1.2000), (6.2400, -5.2100, 2.2600), (6.2380, -5.2100, 2.2755), (6.2320, -5.2100, 2.2900), (6.2224, -5.2100, 2.3024), (6.2100, -5.2100, 2.3120), (6.1955, -5.2100, 2.3180), (6.1800, -5.2100, 2.3200), (5.8000, -5.2100, 2.3200), (5.7845, -5.2100, 2.3180), (5.7700, -5.2100, 2.3120), (5.7576, -5.2100, 2.3024), (5.7480, -5.2100, 2.2900), (5.7420, -5.2100, 2.2755), (5.7400, -5.2100, 2.2600)], [(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30), (61, 60, 59, 58, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38, 37, 36, 35, 34, 33, 32, 31), (1, 0, 31, 32), (2, 1, 32, 33), (3, 2, 33, 34), (4, 3, 34, 35), (5, 4, 35, 36), (6, 5, 36, 37), (7, 6, 37, 38), (8, 7, 38, 39), (9, 8, 39, 40), (10, 9, 40, 41), (11, 10, 41, 42), (12, 11, 42, 43), (13, 12, 43, 44), (14, 13, 44, 45), (15, 14, 45, 46), (16, 15, 46, 47), (17, 16, 47, 48), (18, 17, 48, 49), (19, 18, 49, 50), (20, 19, 50, 51), (21, 20, 51, 52), (22, 21, 52, 53), (23, 22, 53, 54), (24, 23, 54, 55), (25, 24, 55, 56), (26, 25, 56, 57), (27, 26, 57, 58), (28, 27, 58, 59), (29, 28, 59, 60), (30, 29, 60, 61), (0, 30, 61, 31)], MATS["Warm_LED_Glow"])
    _add_raw_mesh_2f("2F_MBR_Vanity_Mirror", [(5.7550, -5.2100, 1.2000), (5.7595, -5.2100, 1.1542), (5.7729, -5.2100, 1.1101), (5.7946, -5.2100, 1.0694), (5.8238, -5.2100, 1.0338), (5.8594, -5.2100, 1.0046), (5.9001, -5.2100, 0.9829), (5.9442, -5.2100, 0.9695), (5.9900, -5.2100, 0.9650), (6.0358, -5.2100, 0.9695), (6.0799, -5.2100, 0.9829), (6.1206, -5.2100, 1.0046), (6.1562, -5.2100, 1.0338), (6.1854, -5.2100, 1.0694), (6.2071, -5.2100, 1.1101), (6.2205, -5.2100, 1.1542), (6.2250, -5.2100, 1.2000), (6.2250, -5.2100, 2.2450), (6.2230, -5.2100, 2.2605), (6.2170, -5.2100, 2.2750), (6.2074, -5.2100, 2.2874), (6.1950, -5.2100, 2.2970), (6.1805, -5.2100, 2.3030), (6.1650, -5.2100, 2.3050), (5.8150, -5.2100, 2.3050), (5.7995, -5.2100, 2.3030), (5.7850, -5.2100, 2.2970), (5.7726, -5.2100, 2.2874), (5.7630, -5.2100, 2.2750), (5.7570, -5.2100, 2.2605), (5.7550, -5.2100, 2.2450), (5.7550, -5.2020, 1.2000), (5.7595, -5.2020, 1.1542), (5.7729, -5.2020, 1.1101), (5.7946, -5.2020, 1.0694), (5.8238, -5.2020, 1.0338), (5.8594, -5.2020, 1.0046), (5.9001, -5.2020, 0.9829), (5.9442, -5.2020, 0.9695), (5.9900, -5.2020, 0.9650), (6.0358, -5.2020, 0.9695), (6.0799, -5.2020, 0.9829), (6.1206, -5.2020, 1.0046), (6.1562, -5.2020, 1.0338), (6.1854, -5.2020, 1.0694), (6.2071, -5.2020, 1.1101), (6.2205, -5.2020, 1.1542), (6.2250, -5.2020, 1.2000), (6.2250, -5.2020, 2.2450), (6.2230, -5.2020, 2.2605), (6.2170, -5.2020, 2.2750), (6.2074, -5.2020, 2.2874), (6.1950, -5.2020, 2.2970), (6.1805, -5.2020, 2.3030), (6.1650, -5.2020, 2.3050), (5.8150, -5.2020, 2.3050), (5.7995, -5.2020, 2.3030), (5.7850, -5.2020, 2.2970), (5.7726, -5.2020, 2.2874), (5.7630, -5.2020, 2.2750), (5.7570, -5.2020, 2.2605), (5.7550, -5.2020, 2.2450)], [(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30), (61, 60, 59, 58, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38, 37, 36, 35, 34, 33, 32, 31), (1, 0, 31, 32), (2, 1, 32, 33), (3, 2, 33, 34), (4, 3, 34, 35), (5, 4, 35, 36), (6, 5, 36, 37), (7, 6, 37, 38), (8, 7, 38, 39), (9, 8, 39, 40), (10, 9, 40, 41), (11, 10, 41, 42), (12, 11, 42, 43), (13, 12, 43, 44), (14, 13, 44, 45), (15, 14, 45, 46), (16, 15, 46, 47), (17, 16, 47, 48), (18, 17, 48, 49), (19, 18, 49, 50), (20, 19, 50, 51), (21, 20, 51, 52), (22, 21, 52, 53), (23, 22, 53, 54), (24, 23, 54, 55), (25, 24, 55, 56), (26, 25, 56, 57), (27, 26, 57, 58), (28, 27, 58, 59), (29, 28, 59, 60), (30, 29, 60, 61), (0, 30, 61, 31)], MATS["Mirror_Silver"])
    add_box_mm("2F_MBR_Vanity_DeskTop", 5360.0, 6620.0, -5250.0, -4720.0, z_2f + 0.7400, z_2f + 0.7800, MATS["OLO_Cab_White"], col_2f)
    add_box_mm("2F_MBR_Vanity_DeskReveal", 5370.0, 6610.0, -5250.0, -4732.0, z_2f + 0.7280, z_2f + 0.7400, MATS["OLO_ToeKick_Black"], col_2f)
    add_box_mm("2F_MBR_Vanity_PedL", 5370.0, 5760.0, -5250.0, -4758.0, z_2f + 0.0000, z_2f + 0.7280, MATS["Optical_Wood_Shadow_Base"], col_2f)
    add_box_mm("2F_MBR_Vanity_PedR", 6220.0, 6610.0, -5250.0, -4758.0, z_2f + 0.0000, z_2f + 0.7280, MATS["Optical_Wood_Shadow_Base"], col_2f)
    add_box_mm("2F_MBR_Vanity_PedL_Seam", 5370.0, 5760.0, -4758.0, -4743.0, z_2f + 0.3580, z_2f + 0.3700, MATS["OLO_ToeKick_Black"], col_2f)
    add_box_mm("2F_MBR_Vanity_PedR_Seam", 6220.0, 6610.0, -4758.0, -4743.0, z_2f + 0.3580, z_2f + 0.3700, MATS["OLO_ToeKick_Black"], col_2f)
    add_box_mm("2F_MBR_Vanity_CenterDrawer", 5760.0, 6220.0, -5250.0, -4758.0, z_2f + 0.6000, z_2f + 0.7280, MATS["Optical_Wood_Shadow_Base"], col_2f)
    add_uv_front_box_mm("2F_MBR_Vanity_PedL_DoorBot", 5370.0, 5760.0, -4758.0, -4740.0, z_2f + 0.0050, z_2f + 0.3580, 0.00, 0.00 + 0.390 / 0.55, 0.00, 0.00 + 0.353 / 0.55, MATS["Optical_Wood_Shadow"], col_2f)
    add_uv_front_box_mm("2F_MBR_Vanity_PedL_DoorTop", 5370.0, 5760.0, -4758.0, -4740.0, z_2f + 0.3700, z_2f + 0.7260, 0.00, 0.00 + 0.390 / 0.55, 0.65, 0.65 + 0.356 / 0.55, MATS["Optical_Wood_Shadow"], col_2f)
    add_uv_front_box_mm("2F_MBR_Vanity_PedR_DoorBot", 6220.0, 6610.0, -4758.0, -4740.0, z_2f + 0.0050, z_2f + 0.3580, 0.42, 0.42 + 0.390 / 0.55, 0.00, 0.00 + 0.353 / 0.55, MATS["Optical_Wood_Shadow"], col_2f)
    add_uv_front_box_mm("2F_MBR_Vanity_PedR_DoorTop", 6220.0, 6610.0, -4758.0, -4740.0, z_2f + 0.3700, z_2f + 0.7260, 0.42, 0.42 + 0.390 / 0.55, 0.65, 0.65 + 0.356 / 0.55, MATS["Optical_Wood_Shadow"], col_2f)
    add_uv_front_box_mm("2F_MBR_Vanity_CenterDrawer_Front", 5762.0, 6218.0, -4758.0, -4740.0, z_2f + 0.6020, z_2f + 0.7260, 0.00, 0.00 + 0.456 / 0.55, 0.35, 0.35 + 0.124 / 0.55, MATS["Optical_Wood_Shadow"], col_2f)
    _add_raw_mesh_2f("2F_MBR_Vanity_Stool", [(6.0090, -4.5600, 0.0000), (6.0041, -4.5466, 0.0000), (6.0028, -4.5333, 0.0000), (6.0050, -4.5192, 0.0000), (5.9975, -4.5071, 0.0000), (5.9936, -4.4943, 0.0000), (5.9931, -4.4800, 0.0000), (5.9834, -4.4696, 0.0000), (5.9771, -4.4577, 0.0000), (5.9738, -4.4439, 0.0000), (5.9622, -4.4355, 0.0000), (5.9538, -4.4252, 0.0000), (5.9478, -4.4122, 0.0000), (5.9348, -4.4062, 0.0000), (5.9245, -4.3978, 0.0000), (5.9161, -4.3862, 0.0000), (5.9023, -4.3829, 0.0000), (5.8904, -4.3766, 0.0000), (5.8800, -4.3669, 0.0000), (5.8657, -4.3664, 0.0000), (5.8529, -4.3625, 0.0000), (5.8408, -4.3550, 0.0000), (5.8267, -4.3572, 0.0000), (5.8134, -4.3559, 0.0000), (5.8000, -4.3510, 0.0000), (5.7866, -4.3559, 0.0000), (5.7733, -4.3572, 0.0000), (5.7592, -4.3550, 0.0000), (5.7471, -4.3625, 0.0000), (5.7343, -4.3664, 0.0000), (5.7200, -4.3669, 0.0000), (5.7096, -4.3766, 0.0000), (5.6978, -4.3829, 0.0000), (5.6839, -4.3862, 0.0000), (5.6755, -4.3978, 0.0000), (5.6652, -4.4062, 0.0000), (5.6522, -4.4122, 0.0000), (5.6462, -4.4252, 0.0000), (5.6378, -4.4355, 0.0000), (5.6262, -4.4439, 0.0000), (5.6229, -4.4577, 0.0000), (5.6166, -4.4696, 0.0000), (5.6069, -4.4800, 0.0000), (5.6064, -4.4943, 0.0000), (5.6025, -4.5071, 0.0000), (5.5950, -4.5192, 0.0000), (5.5972, -4.5333, 0.0000), (5.5959, -4.5466, 0.0000), (5.5910, -4.5600, 0.0000), (5.5959, -4.5734, 0.0000), (5.5972, -4.5867, 0.0000), (5.5950, -4.6008, 0.0000), (5.6025, -4.6129, 0.0000), (5.6064, -4.6257, 0.0000), (5.6069, -4.6400, 0.0000), (5.6166, -4.6504, 0.0000), (5.6229, -4.6623, 0.0000), (5.6262, -4.6761, 0.0000), (5.6378, -4.6845, 0.0000), (5.6462, -4.6948, 0.0000), (5.6522, -4.7078, 0.0000), (5.6652, -4.7138, 0.0000), (5.6755, -4.7222, 0.0000), (5.6839, -4.7338, 0.0000), (5.6978, -4.7371, 0.0000), (5.7096, -4.7434, 0.0000), (5.7200, -4.7531, 0.0000), (5.7343, -4.7536, 0.0000), (5.7471, -4.7575, 0.0000), (5.7592, -4.7650, 0.0000), (5.7733, -4.7628, 0.0000), (5.7866, -4.7641, 0.0000), (5.8000, -4.7690, 0.0000), (5.8134, -4.7641, 0.0000), (5.8267, -4.7628, 0.0000), (5.8408, -4.7650, 0.0000), (5.8529, -4.7575, 0.0000), (5.8657, -4.7536, 0.0000), (5.8800, -4.7531, 0.0000), (5.8904, -4.7434, 0.0000), (5.9023, -4.7371, 0.0000), (5.9161, -4.7338, 0.0000), (5.9245, -4.7222, 0.0000), (5.9348, -4.7138, 0.0000), (5.9478, -4.7078, 0.0000), (5.9538, -4.6948, 0.0000), (5.9622, -4.6845, 0.0000), (5.9738, -4.6761, 0.0000), (5.9771, -4.6623, 0.0000), (5.9834, -4.6504, 0.0000), (5.9931, -4.6400, 0.0000), (5.9936, -4.6257, 0.0000), (5.9975, -4.6129, 0.0000), (6.0050, -4.6008, 0.0000), (6.0028, -4.5867, 0.0000), (6.0041, -4.5734, 0.0000), (6.0090, -4.5600, 0.4400), (6.0041, -4.5466, 0.4400), (6.0028, -4.5333, 0.4400), (6.0050, -4.5192, 0.4400), (5.9975, -4.5071, 0.4400), (5.9936, -4.4943, 0.4400), (5.9931, -4.4800, 0.4400), (5.9834, -4.4696, 0.4400), (5.9771, -4.4577, 0.4400), (5.9738, -4.4439, 0.4400), (5.9622, -4.4355, 0.4400), (5.9538, -4.4252, 0.4400), (5.9478, -4.4122, 0.4400), (5.9348, -4.4062, 0.4400), (5.9245, -4.3978, 0.4400), (5.9161, -4.3862, 0.4400), (5.9023, -4.3829, 0.4400), (5.8904, -4.3766, 0.4400), (5.8800, -4.3669, 0.4400), (5.8657, -4.3664, 0.4400), (5.8529, -4.3625, 0.4400), (5.8408, -4.3550, 0.4400), (5.8267, -4.3572, 0.4400), (5.8134, -4.3559, 0.4400), (5.8000, -4.3510, 0.4400), (5.7866, -4.3559, 0.4400), (5.7733, -4.3572, 0.4400), (5.7592, -4.3550, 0.4400), (5.7471, -4.3625, 0.4400), (5.7343, -4.3664, 0.4400), (5.7200, -4.3669, 0.4400), (5.7096, -4.3766, 0.4400), (5.6978, -4.3829, 0.4400), (5.6839, -4.3862, 0.4400), (5.6755, -4.3978, 0.4400), (5.6652, -4.4062, 0.4400), (5.6522, -4.4122, 0.4400), (5.6462, -4.4252, 0.4400), (5.6378, -4.4355, 0.4400), (5.6262, -4.4439, 0.4400), (5.6229, -4.4577, 0.4400), (5.6166, -4.4696, 0.4400), (5.6069, -4.4800, 0.4400), (5.6064, -4.4943, 0.4400), (5.6025, -4.5071, 0.4400), (5.5950, -4.5192, 0.4400), (5.5972, -4.5333, 0.4400), (5.5959, -4.5466, 0.4400), (5.5910, -4.5600, 0.4400), (5.5959, -4.5734, 0.4400), (5.5972, -4.5867, 0.4400), (5.5950, -4.6008, 0.4400), (5.6025, -4.6129, 0.4400), (5.6064, -4.6257, 0.4400), (5.6069, -4.6400, 0.4400), (5.6166, -4.6504, 0.4400), (5.6229, -4.6623, 0.4400), (5.6262, -4.6761, 0.4400), (5.6378, -4.6845, 0.4400), (5.6462, -4.6948, 0.4400), (5.6522, -4.7078, 0.4400), (5.6652, -4.7138, 0.4400), (5.6755, -4.7222, 0.4400), (5.6839, -4.7338, 0.4400), (5.6978, -4.7371, 0.4400), (5.7096, -4.7434, 0.4400), (5.7200, -4.7531, 0.4400), (5.7343, -4.7536, 0.4400), (5.7471, -4.7575, 0.4400), (5.7592, -4.7650, 0.4400), (5.7733, -4.7628, 0.4400), (5.7866, -4.7641, 0.4400), (5.8000, -4.7690, 0.4400), (5.8134, -4.7641, 0.4400), (5.8267, -4.7628, 0.4400), (5.8408, -4.7650, 0.4400), (5.8529, -4.7575, 0.4400), (5.8657, -4.7536, 0.4400), (5.8800, -4.7531, 0.4400), (5.8904, -4.7434, 0.4400), (5.9023, -4.7371, 0.4400), (5.9161, -4.7338, 0.4400), (5.9245, -4.7222, 0.4400), (5.9348, -4.7138, 0.4400), (5.9478, -4.7078, 0.4400), (5.9538, -4.6948, 0.4400), (5.9622, -4.6845, 0.4400), (5.9738, -4.6761, 0.4400), (5.9771, -4.6623, 0.4400), (5.9834, -4.6504, 0.4400), (5.9931, -4.6400, 0.4400), (5.9936, -4.6257, 0.4400), (5.9975, -4.6129, 0.4400), (6.0050, -4.6008, 0.4400), (6.0028, -4.5867, 0.4400), (6.0041, -4.5734, 0.4400)], [(95, 94, 93, 92, 91, 90, 89, 88, 87, 86, 85, 84, 83, 82, 81, 80, 79, 78, 77, 76, 75, 74, 73, 72, 71, 70, 69, 68, 67, 66, 65, 64, 63, 62, 61, 60, 59, 58, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38, 37, 36, 35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175, 176, 177, 178, 179, 180, 181, 182, 183, 184, 185, 186, 187, 188, 189, 190, 191), (0, 1, 97, 96), (1, 2, 98, 97), (2, 3, 99, 98), (3, 4, 100, 99), (4, 5, 101, 100), (5, 6, 102, 101), (6, 7, 103, 102), (7, 8, 104, 103), (8, 9, 105, 104), (9, 10, 106, 105), (10, 11, 107, 106), (11, 12, 108, 107), (12, 13, 109, 108), (13, 14, 110, 109), (14, 15, 111, 110), (15, 16, 112, 111), (16, 17, 113, 112), (17, 18, 114, 113), (18, 19, 115, 114), (19, 20, 116, 115), (20, 21, 117, 116), (21, 22, 118, 117), (22, 23, 119, 118), (23, 24, 120, 119), (24, 25, 121, 120), (25, 26, 122, 121), (26, 27, 123, 122), (27, 28, 124, 123), (28, 29, 125, 124), (29, 30, 126, 125), (30, 31, 127, 126), (31, 32, 128, 127), (32, 33, 129, 128), (33, 34, 130, 129), (34, 35, 131, 130), (35, 36, 132, 131), (36, 37, 133, 132), (37, 38, 134, 133), (38, 39, 135, 134), (39, 40, 136, 135), (40, 41, 137, 136), (41, 42, 138, 137), (42, 43, 139, 138), (43, 44, 140, 139), (44, 45, 141, 140), (45, 46, 142, 141), (46, 47, 143, 142), (47, 48, 144, 143), (48, 49, 145, 144), (49, 50, 146, 145), (50, 51, 147, 146), (51, 52, 148, 147), (52, 53, 149, 148), (53, 54, 150, 149), (54, 55, 151, 150), (55, 56, 152, 151), (56, 57, 153, 152), (57, 58, 154, 153), (58, 59, 155, 154), (59, 60, 156, 155), (60, 61, 157, 156), (61, 62, 158, 157), (62, 63, 159, 158), (63, 64, 160, 159), (64, 65, 161, 160), (65, 66, 162, 161), (66, 67, 163, 162), (67, 68, 164, 163), (68, 69, 165, 164), (69, 70, 166, 165), (70, 71, 167, 166), (71, 72, 168, 167), (72, 73, 169, 168), (73, 74, 170, 169), (74, 75, 171, 170), (75, 76, 172, 171), (76, 77, 173, 172), (77, 78, 174, 173), (78, 79, 175, 174), (79, 80, 176, 175), (80, 81, 177, 176), (81, 82, 178, 177), (82, 83, 179, 178), (83, 84, 180, 179), (84, 85, 181, 180), (85, 86, 182, 181), (86, 87, 183, 182), (87, 88, 184, 183), (88, 89, 185, 184), (89, 90, 186, 185), (90, 91, 187, 186), (91, 92, 188, 187), (92, 93, 189, 188), (93, 94, 190, 189), (94, 95, 191, 190), (95, 0, 96, 191)], MATS["Bed_Linen"])
    _add_raw_mesh_2f("2F_MBR_Vanity_Stool_Base", [(6.0000, -4.5590, 0.0000), (5.9962, -4.5202, 0.0000), (5.9849, -4.4828, 0.0000), (5.9665, -4.4484, 0.0000), (5.9417, -4.4183, 0.0000), (5.9116, -4.3935, 0.0000), (5.8772, -4.3751, 0.0000), (5.8398, -4.3638, 0.0000), (5.8010, -4.3600, 0.0000), (5.7990, -4.3600, 0.0000), (5.7602, -4.3638, 0.0000), (5.7228, -4.3751, 0.0000), (5.6884, -4.3935, 0.0000), (5.6583, -4.4183, 0.0000), (5.6335, -4.4484, 0.0000), (5.6151, -4.4828, 0.0000), (5.6038, -4.5202, 0.0000), (5.6000, -4.5590, 0.0000), (5.6000, -4.5610, 0.0000), (5.6038, -4.5998, 0.0000), (5.6151, -4.6372, 0.0000), (5.6335, -4.6716, 0.0000), (5.6583, -4.7017, 0.0000), (5.6884, -4.7265, 0.0000), (5.7228, -4.7449, 0.0000), (5.7602, -4.7562, 0.0000), (5.7990, -4.7600, 0.0000), (5.8010, -4.7600, 0.0000), (5.8398, -4.7562, 0.0000), (5.8772, -4.7449, 0.0000), (5.9116, -4.7265, 0.0000), (5.9417, -4.7017, 0.0000), (5.9665, -4.6716, 0.0000), (5.9849, -4.6372, 0.0000), (5.9962, -4.5998, 0.0000), (6.0000, -4.5610, 0.0000), (6.0000, -4.5590, 0.0200), (5.9962, -4.5202, 0.0200), (5.9849, -4.4828, 0.0200), (5.9665, -4.4484, 0.0200), (5.9417, -4.4183, 0.0200), (5.9116, -4.3935, 0.0200), (5.8772, -4.3751, 0.0200), (5.8398, -4.3638, 0.0200), (5.8010, -4.3600, 0.0200), (5.7990, -4.3600, 0.0200), (5.7602, -4.3638, 0.0200), (5.7228, -4.3751, 0.0200), (5.6884, -4.3935, 0.0200), (5.6583, -4.4183, 0.0200), (5.6335, -4.4484, 0.0200), (5.6151, -4.4828, 0.0200), (5.6038, -4.5202, 0.0200), (5.6000, -4.5590, 0.0200), (5.6000, -4.5610, 0.0200), (5.6038, -4.5998, 0.0200), (5.6151, -4.6372, 0.0200), (5.6335, -4.6716, 0.0200), (5.6583, -4.7017, 0.0200), (5.6884, -4.7265, 0.0200), (5.7228, -4.7449, 0.0200), (5.7602, -4.7562, 0.0200), (5.7990, -4.7600, 0.0200), (5.8010, -4.7600, 0.0200), (5.8398, -4.7562, 0.0200), (5.8772, -4.7449, 0.0200), (5.9116, -4.7265, 0.0200), (5.9417, -4.7017, 0.0200), (5.9665, -4.6716, 0.0200), (5.9849, -4.6372, 0.0200), (5.9962, -4.5998, 0.0200), (6.0000, -4.5610, 0.0200)], [(35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0), (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71), (0, 1, 37, 36), (1, 2, 38, 37), (2, 3, 39, 38), (3, 4, 40, 39), (4, 5, 41, 40), (5, 6, 42, 41), (6, 7, 43, 42), (7, 8, 44, 43), (8, 9, 45, 44), (9, 10, 46, 45), (10, 11, 47, 46), (11, 12, 48, 47), (12, 13, 49, 48), (13, 14, 50, 49), (14, 15, 51, 50), (15, 16, 52, 51), (16, 17, 53, 52), (17, 18, 54, 53), (18, 19, 55, 54), (19, 20, 56, 55), (20, 21, 57, 56), (21, 22, 58, 57), (22, 23, 59, 58), (23, 24, 60, 59), (24, 25, 61, 60), (25, 26, 62, 61), (26, 27, 63, 62), (27, 28, 64, 63), (28, 29, 65, 64), (29, 30, 66, 65), (30, 31, 67, 66), (31, 32, 68, 67), (32, 33, 69, 68), (33, 34, 70, 69), (34, 35, 71, 70), (35, 0, 36, 71)], MATS["Gold_Brass"])
    # Calibrate 2F Master Bedroom South-wall furniture into X = 1714..6502 (4788 mm) in vertex space:
    # - Vanity + mirror + stool: -200 mm -> 5160..6420 (82 mm clear of East wall 6502)
    # - Bed + headwall grey + brass strips + Cream_E: -40 mm -> bed 2450..4450, Cream_E 4462..5160 (flush to Vanity!)
    # - Night_E + Sconce_E: -100 mm -> Night_E 4530..5100 (80mm from bed, 60mm from Vanity)
    # - Night_W + Sconce_W: -20 mm -> Night_W 1770..2340 (56mm from WIC 1714, 110mm from bed)
    # - HeadWall_Cream_W: right edge 2478 -> 2438 (flush to BrassStrip_L at 2438)
    for _ob in col_2f.objects:
        if not _ob.data or not hasattr(_ob.data, "vertices"):
            continue
        _nm = _ob.name
        _dx = 0.0
        if _nm.startswith("2F_MBR_Vanity_"):
            _dx = -0.200
        elif _nm.startswith(("2F_MBR_Night_E_", "2F_MBR_Sconce_E_")):
            _dx = -0.100
        elif _nm.startswith(("2F_MBR_Night_W_", "2F_MBR_Sconce_W_")):
            _dx = -0.020
        elif _nm.startswith(("2F_MBR_Bed_", "2F_MBR_HeadWall_Grey", "2F_MBR_HeadWall_BrassStrip_", "2F_MBR_HeadWall_Cream_E")):
            _dx = -0.040
        if _dx != 0.0:
            for _v in _ob.data.vertices:
                _v.co.x += _dx
            _ob.data.update()
        elif _nm == "2F_MBR_HeadWall_Cream_W":
            for _v in _ob.data.vertices:
                if _v.co.x > 2.45:
                    _v.co.x = 2.438
            _ob.data.update()

    def build_2f_mbr_opp_wardrobe():
        # 2F Master Bedroom Foot-of-Bed Cabinet (unified 3790x2500mm, flush to calibrated East window wall x=6500, concave curved bays + Golden Silk Nanmu center alcove)
        x0, x1 = 2710.0, 6500.0
        yb, yf = -1830.0, -2360.0
        scoop_d = 58.0
        z0 = z_2f
        h_tot = 2.500
        h_body = 2.460

        def y_concave(px, bay_xa, bay_xb):
            s = max(-1.0, min(1.0, 2.0 * (px - bay_xa) / max(1e-3, bay_xb - bay_xa) - 1.0))
            return yf - scoop_d * (abs(s) ** 2.2)

        def add_concave_bay_panel_mm(pname, bay_xa, bay_xb, px1, px2, y_off, depth_mm, z_lo, z_hi, mat, n_seg=24, u0=0.0, u1=0.72, v0=0.0, v1=1.0):
            pts_f = []
            for si in range(n_seg + 1):
                px = px1 + (px2 - px1) * (si / float(n_seg))
                pts_f.append((px, y_concave(px, bay_xa, bay_xb) + y_off))

            arc_s = [0.0]
            for i in range(1, len(pts_f)):
                arc_s.append(arc_s[-1] + math.hypot(pts_f[i][0] - pts_f[i - 1][0], pts_f[i][1] - pts_f[i - 1][1]))
            tot_arc = max(arc_s[-1], 1e-4)

            mesh = bpy.data.meshes.new(pname)
            bm = bmesh.new()
            uv_layer = bm.loops.layers.uv.new("UVMap")
            n_p = len(pts_f)
            fb, ft, bb, bt = [], [], [], []
            for px, py in pts_f:
                fb.append(bm.verts.new((px * MM, py * MM, z_lo)))
                ft.append(bm.verts.new((px * MM, py * MM, z_hi)))
                bb.append(bm.verts.new((px * MM, (py + depth_mm) * MM, z_lo)))
                bt.append(bm.verts.new((px * MM, (py + depth_mm) * MM, z_hi)))

            for i in range(n_p - 1):
                u_a = u0 + (u1 - u0) * (arc_s[i] / tot_arc)
                u_b = u0 + (u1 - u0) * (arc_s[i + 1] / tot_arc)
                ff = bm.faces.new([fb[i], fb[i + 1], ft[i + 1], ft[i]])
                ff.smooth = True
                for lp, uv in zip(ff.loops, [(u_a, v0), (u_b, v0), (u_b, v1), (u_a, v1)]):
                    lp[uv_layer].uv = uv

                fbk = bm.faces.new([bb[i + 1], bb[i], bt[i], bt[i + 1]])
                fbk.smooth = False
                for lp in fbk.loops:
                    lp[uv_layer].uv = (u0, v0)

                fbot = bm.faces.new([bb[i], bb[i + 1], fb[i + 1], fb[i]])
                fbot.smooth = False
                for lp in fbot.loops:
                    lp[uv_layer].uv = (u_a, v0)

                ftop = bm.faces.new([ft[i], ft[i + 1], bt[i + 1], bt[i]])
                ftop.smooth = False
                for lp in ftop.loops:
                    lp[uv_layer].uv = (u_a, v1)

            fl = bm.faces.new([bb[0], fb[0], ft[0], bt[0]])
            fl.smooth = False
            for lp in fl.loops:
                lp[uv_layer].uv = (u0, v0)
            fr = bm.faces.new([fb[-1], bb[-1], bt[-1], ft[-1]])
            fr.smooth = False
            for lp in fr.loops:
                lp[uv_layer].uv = (u1, v0)

            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
            sharp = [
                e for e in bm.edges
                if len(e.link_faces) == 2 and (
                    e.link_faces[0].smooth != e.link_faces[1].smooth
                    or e.link_faces[0].normal.dot(e.link_faces[1].normal) < 0.72
                )
            ]
            if sharp:
                bmesh.ops.split_edges(bm, edges=sharp)
            bm.to_mesh(mesh)
            bm.free()
            obj = bpy.data.objects.new(pname, mesh)
            obj.data.materials.append(mat)
            link_obj(obj, col_2f)
            return obj

        # Recessed Upper Gypsum Bulkhead (z: 2.500..2.830) following 200mm stepped North wall (Y=-1830 West, Y=-1630 East of x0+2564=5274)
        add_box_mm("2F_MBR_OppCab_Soffit", x0, x0 + 2564.0, yf + 25.0, yb, z0 + h_tot, z0 + h_2f, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm("2F_MBR_OppCab_Soffit_R", x0 + 2564.0, x1, yf + 25.0, yb + 200.0, z0 + h_tot, z0 + h_2f, MATS["Wall_Panel_Cream"], col_2f)

        # Left (48..932 -> 45cm depth: yb_L=-1910) & Right (2564..3500 -> 60cm depth: yb_R=-1760, recessed North wall) Concave White_Shadow_Wood 2-Door Wardrobes
        def build_concave_wardrobe_bay(tag, xa, d1_b, d2_a, xb, c1_x, c2_x, gr_la, gr_lb, gr_ra, gr_rb, bay_yb):
            b_xa, b_xb = x0 + xa, x0 + xb
            add_box_mm(f"2F_MBR_OppCab_{tag}_Carcass", b_xa, b_xb, yf + 24.0, bay_yb, z0 + 0.060, z0 + h_body, MATS["White_Shadow_Wood_Base"], col_2f)
            add_box_mm(f"2F_MBR_OppCab_{tag}_Seam", x0 + d1_b - 6.0, x0 + d2_a + 6.0, yf + 16.0, yf + 24.0, z0 + 0.060, z0 + h_body, MATS["Dark_Bronze_Recess"], col_2f)
            w1_m = abs((x0 + d1_b) - b_xa) * MM
            w2_m = abs(b_xb - (x0 + d2_a)) * MM
            add_concave_bay_panel_mm(f"2F_MBR_OppCab_{tag}_Door1", b_xa, b_xb, b_xa, x0 + d1_b, 0.0, 22.0, z0 + 0.060, z0 + h_body, MATS["White_Shadow_Wood"], n_seg=24, u0=0.0, u1=0.0 + w1_m / 0.62, v0=0.0, v1=(h_body - 0.060) / 0.62)
            add_concave_bay_panel_mm(f"2F_MBR_OppCab_{tag}_Door2", b_xa, b_xb, x0 + d2_a, b_xb, 0.0, 22.0, z0 + 0.060, z0 + h_body, MATS["White_Shadow_Wood"], n_seg=24, u0=0.18, u1=0.18 + w2_m / 0.62, v0=0.0, v1=(h_body - 0.060) / 0.62)
            # CAD 40mm Top Crown (2.460..2.500) & 60mm Bottom Plinth (0.000..0.060) Concave Antique Brass Ribbons + Solid Fill
            add_concave_bay_panel_mm(f"2F_MBR_OppCab_{tag}_TopBrass", b_xa, b_xb, b_xa, b_xb, -2.0, 62.0, z0 + h_body, z0 + h_tot, MATS["Antique_Champagne_Brass"], n_seg=32)
            add_concave_bay_panel_mm(f"2F_MBR_OppCab_{tag}_BotBrass", b_xa, b_xb, b_xa, b_xb, -2.0, 62.0, z0 + 0.000, z0 + 0.060, MATS["Antique_Champagne_Brass"], n_seg=32)
            add_box_mm(f"2F_MBR_OppCab_{tag}_TopFill", b_xa, b_xb, yf + 26.0, bay_yb, z0 + h_body, z0 + h_tot, MATS["White_Shadow_Wood_Base"], col_2f)
            add_box_mm(f"2F_MBR_OppCab_{tag}_BotFill", b_xa, b_xb, yf + 26.0, bay_yb, z0 + 0.000, z0 + 0.060, MATS["Dark_Bronze_Recess"], col_2f)
            # CAD Waist-Height Hairline Concave Bronze Grooves (z = 0.883 & z = 1.291) + Centered Vertical Dark-Bronze Pull Slots
            for s_idx, (ga, gb, cx) in enumerate([(gr_la, gr_lb, c1_x), (gr_ra, gr_rb, c2_x)], 1):
                add_concave_bay_panel_mm(f"2F_MBR_OppCab_{tag}_GrB_{s_idx}", b_xa, b_xb, x0 + ga, x0 + gb, -2.0, 4.0, z0 + 0.882, z0 + 0.885, MATS["Dark_Bronze_Recess"], n_seg=16)
                add_concave_bay_panel_mm(f"2F_MBR_OppCab_{tag}_GrT_{s_idx}", b_xa, b_xb, x0 + ga, x0 + gb, -2.0, 4.0, z0 + 1.288, z0 + 1.291, MATS["Dark_Bronze_Recess"], n_seg=16)
                y_sl = y_concave(x0 + cx, b_xa, b_xb)
                add_box_mm(f"2F_MBR_OppCab_{tag}_Slot_{s_idx}", x0 + cx - 16.0, x0 + cx + 16.0, y_sl - 4.0, y_sl + 6.0, z0 + 0.885, z0 + 1.288, MATS["Dark_Bronze_Recess"], col_2f)
                add_box_mm(f"2F_MBR_OppCab_{tag}_SlotTrim_{s_idx}", x0 + cx + 8.0, x0 + cx + 14.0, y_sl - 5.5, y_sl - 2.0, z0 + 0.890, z0 + 1.284, MATS["Antique_Champagne_Brass"], col_2f)
            # 2 Illuminated 3-Segment Amber Curved-Rim Light Handles at the Proud Concave Outer Rims (yf - scoop_d)
            y_rim = yf - scoop_d
            for r_idx, rx1 in enumerate([xa, xb - 21.0], 1):
                rx2 = rx1 + 21.0
                add_box_mm(f"2F_MBR_OppCab_{tag}_RimF_L{r_idx}", x0 + rx1, x0 + rx1 + 3.0, y_rim - 4.0, y_rim + 12.0, z0 + 0.883, z0 + 1.291, MATS["Antique_Champagne_Brass"], col_2f)
                add_box_mm(f"2F_MBR_OppCab_{tag}_RimF_R{r_idx}", x0 + rx2 - 3.0, x0 + rx2, y_rim - 4.0, y_rim + 12.0, z0 + 0.883, z0 + 1.291, MATS["Antique_Champagne_Brass"], col_2f)
                add_box_mm(f"2F_MBR_OppCab_{tag}_RimF_B{r_idx}", x0 + rx1, x0 + rx2, y_rim - 4.0, y_rim + 12.0, z0 + 0.883, z0 + 0.889, MATS["Antique_Champagne_Brass"], col_2f)
                add_box_mm(f"2F_MBR_OppCab_{tag}_RimF_T{r_idx}", x0 + rx1, x0 + rx2, y_rim - 4.0, y_rim + 12.0, z0 + 1.285, z0 + 1.291, MATS["Antique_Champagne_Brass"], col_2f)
                add_box_mm(f"2F_MBR_OppCab_{tag}_RimBar1_{r_idx}", x0 + rx1, x0 + rx2, y_rim - 4.0, y_rim + 12.0, z0 + 1.018, z0 + 1.024, MATS["Antique_Champagne_Brass"], col_2f)
                add_box_mm(f"2F_MBR_OppCab_{tag}_RimBar2_{r_idx}", x0 + rx1, x0 + rx2, y_rim - 4.0, y_rim + 12.0, z0 + 1.150, z0 + 1.156, MATS["Antique_Champagne_Brass"], col_2f)
                for l_i, (lz0, lz1) in enumerate([(0.889, 1.018), (1.024, 1.150), (1.156, 1.285)], 1):
                    add_box_mm(f"2F_MBR_OppCab_{tag}_RimGlow_{r_idx}_{l_i}", x0 + rx1 + 3.0, x0 + rx2 - 3.0, y_rim - 5.0, y_rim + 9.0, z0 + lz0, z0 + lz1, MATS["Handle_Amber_Glow"], col_2f)

        build_concave_wardrobe_bay("L", 48.0, 488.0, 492.0, 932.0, 290.0, 690.0, 95.0, 488.0, 492.0, 885.0, yf + 450.0)
        build_concave_wardrobe_bay("R", 2564.0, 3030.0, 3034.0, 3500.0, 2795.0, 3265.0, 2610.0, 3030.0, 3034.0, 3450.0, yb + 200.0)

        # CAD Left End Cheek (0..48mm) & Shadow Reveals Flanking Center Alcove
        add_box_mm("2F_MBR_OppCab_LeftGap", x0, x0 + 14.0, yf - scoop_d + 8.0, yb, z0, z0 + h_tot, MATS["Dark_Bronze_Recess"], col_2f)
        add_box_mm("2F_MBR_OppCab_LeftCheek", x0 + 14.0, x0 + 48.0, yf - scoop_d + 4.0, yb, z0, z0 + h_tot, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_MBR_OppCab_SeamAlcL", x0 + 932.0, x0 + 942.0, yf - scoop_d + 4.0, yb, z0, z0 + h_tot, MATS["Dark_Bronze_Recess"], col_2f)
        add_box_mm("2F_MBR_OppCab_SeamAlcR", x0 + 2554.0, x0 + 2564.0, yf - scoop_d + 4.0, yb, z0, z0 + h_tot, MATS["Dark_Bronze_Recess"], col_2f)

        # Curved-Corner Center Golden Silk Nanmu Alcove (x_local: 942..2554, Left+Center CAD 2554mm)
        def build_alcove_u_profile():
            pts = []
            # Left front flared lip (x_l: 942..974, tangent (-Y) at 942 matching concave rim turning (+Y) at 974)
            for si in range(9):
                th = 0.5 * math.pi * (si / 8.0)
                pts.append((x0 + 942.0 + 32.0 * math.sin(th), (yf - scoop_d) + 74.0 * (1.0 - math.cos(th))))
            # Left concave R=160 quarter-circle fillet into back wall (y: yb-180 -> yb-20)
            for si in range(17):
                phi = 0.5 * math.pi * (si / 16.0)
                pts.append((x0 + 974.0 + 160.0 * (1.0 - math.cos(phi)), (yb - 180.0) + 160.0 * math.sin(phi)))
            # Flat center back wall -> Right concave R=160 fillet
            for si in range(17):
                phi = 0.5 * math.pi + 0.5 * math.pi * (si / 16.0)
                pts.append((x0 + 2362.0 - 160.0 * math.cos(phi), (yb - 180.0) + 160.0 * math.sin(phi)))
            # Right front flared lip (x_l: 2522..2554)
            for si in range(1, 9):
                th = 0.5 * math.pi * (si / 8.0)
                pts.append((x0 + 2522.0 + 32.0 * (1.0 - math.cos(th)), (yf + 16.0) - 74.0 * math.sin(th)))
            return pts

        alc_pts = build_alcove_u_profile()
        alc_s = [0.0]
        for i in range(1, len(alc_pts)):
            alc_s.append(alc_s[-1] + math.hypot(alc_pts[i][0] - alc_pts[i - 1][0], alc_pts[i][1] - alc_pts[i - 1][1]))
        alc_tot = max(alc_s[-1], 1e-4)

        def create_alcove_solid(aname, pts_xy, z_lo, z_hi, mat_wall, wrap_uv=False):
            mesh_a = bpy.data.meshes.new(aname)
            bm_a = bmesh.new()
            uv_a = bm_a.loops.layers.uv.new("UVMap")
            p_ro = (x0 + 2554.0, yf - 22.0)
            p_rb = (x0 + 2554.0, yb)
            p_lb = (x0 + 942.0, yb)
            p_lo = (x0 + 942.0, yf - 22.0)
            ring_xy = pts_xy + [p_ro, p_rb, p_lb, p_lo]
            m_tot = len(ring_xy)
            n_curve = len(pts_xy) - 1
            vb_ring = [bm_a.verts.new((px * MM, py * MM, z_lo)) for px, py in ring_xy]
            vt_ring = [bm_a.verts.new((px * MM, py * MM, z_hi)) for px, py in ring_xy]
            for i in range(m_tot):
                j = (i + 1) % m_tot
                is_curve = (i < n_curve)
                f = bm_a.faces.new([vb_ring[i], vb_ring[j], vt_ring[j], vt_ring[i]])
                f.smooth = is_curve
                if wrap_uv and is_curve:
                    ua = (alc_s[i] * MM) / 0.90
                    ub = (alc_s[i + 1] * MM) / 0.90
                    v_hi = (z_hi - z_lo) / 0.60
                    for lp, uv in zip(f.loops, [(ua, 0.0), (ub, 0.0), (ub, v_hi), (ua, v_hi)]):
                        lp[uv_a].uv = uv
                else:
                    for lp in f.loops:
                        lp[uv_a].uv = (0.5, 0.5)
            bm_a.edges.ensure_lookup_table()
            bot_edges = [bm_a.edges.get((vb_ring[i], vb_ring[(i + 1) % m_tot])) for i in range(m_tot)]
            top_edges = [bm_a.edges.get((vt_ring[i], vt_ring[(i + 1) % m_tot])) for i in range(m_tot)]
            res_bot = bmesh.ops.triangle_fill(bm_a, use_beauty=True, edges=[e for e in bot_edges if e is not None])
            res_top = bmesh.ops.triangle_fill(bm_a, use_beauty=True, edges=[e for e in top_edges if e is not None])
            for g_f in res_bot.get("geom", []) + res_top.get("geom", []):
                if isinstance(g_f, bmesh.types.BMFace):
                    g_f.smooth = False
                    for lp in g_f.loops:
                        lp[uv_a].uv = (0.5, 0.5)
            bmesh.ops.recalc_face_normals(bm_a, faces=bm_a.faces[:])
            sharp_a = [
                e for e in bm_a.edges
                if len(e.link_faces) == 2 and (
                    e.link_faces[0].smooth != e.link_faces[1].smooth
                    or e.link_faces[0].normal.dot(e.link_faces[1].normal) < 0.72
                )
            ]
            if sharp_a:
                bmesh.ops.split_edges(bm_a, edges=sharp_a)
            bm_a.to_mesh(mesh_a)
            bm_a.free()
            obj_a = bpy.data.objects.new(aname, mesh_a)
            obj_a.data.materials.append(mat_wall)
            link_obj(obj_a, col_2f)
            return obj_a

        create_alcove_solid("2F_MBR_OppCab_Alcove_CurvedWall", alc_pts, z0 + 0.060, z0 + h_body, MATS["Golden_Silk_Nanmu"], wrap_uv=True)
        alc_trim_pts = [(px, py - 2.0) for px, py in alc_pts]
        create_alcove_solid("2F_MBR_OppCab_Alcove_TopBrass", alc_trim_pts, z0 + h_body, z0 + h_tot, MATS["Antique_Champagne_Brass"], wrap_uv=False)
        create_alcove_solid("2F_MBR_OppCab_Alcove_BotBrass", alc_trim_pts, z0 + 0.000, z0 + 0.060, MATS["Antique_Champagne_Brass"], wrap_uv=False)
        add_box_mm("2F_MBR_OppCab_Alcove_TopLED", x0 + 1140.0, x0 + 2360.0, yb - 55.0, yb - 30.0, z0 + h_body - 0.012, z0 + h_body, MATS["Warm_LED_Glow"], col_2f)

        # 3 Ultra-Slim Bronze Floating Shelves at Exact CAD Elevations (z = 1.208, 1.555, 1.872m) + Guardrails
        sx1, sx2 = x0 + 1188.0, x0 + 2355.0
        sy_front = yf + 240.0
        for si, sz in enumerate([1.208, 1.555, 1.872], 1):
            add_box_mm(f"2F_MBR_OppCab_Shelf_{si}", sx1, sx2, sy_front + 6.0, yb - 20.0, z0 + sz, z0 + sz + 0.026, MATS["White_Shadow_Wood_Base"], col_2f)
            add_box_mm(f"2F_MBR_OppCab_ShelfEdge_{si}", sx1, sx2, sy_front, sy_front + 6.0, z0 + sz, z0 + sz + 0.026, MATS["Antique_Champagne_Brass"], col_2f)
            add_box_mm(f"2F_MBR_OppCab_ShelfLED_{si}", sx1 + 10.0, sx2 - 10.0, yb - 52.0, yb - 30.0, z0 + sz - 0.010, z0 + sz, MATS["Warm_LED_Glow"], col_2f)
            add_box_mm(f"2F_MBR_OppCab_ShelfRail_{si}", sx1 + 18.0, sx2 - 18.0, sy_front + 7.0, sy_front + 13.0, z0 + sz + 0.060, z0 + sz + 0.066, MATS["Antique_Champagne_Brass"], col_2f)
            for p_i, px_st in enumerate([x0 + 1218.0, x0 + 1590.0, x0 + 1965.0, x0 + 2325.0], 1):
                add_cyl_mm(f"2F_MBR_OppCab_ShelfPin_{si}_{p_i}", px_st, sy_front + 10.0, 2.5, z0 + sz + 0.026, z0 + sz + 0.062, MATS["Antique_Champagne_Brass"], col_2f, segs=10)

        # Minimalist Gallery Shelf Decor
        add_cyl_mm("2F_MBR_OppCab_Decor_VesselTopL", sx1 + 170.0, sy_front + 95.0, 52.0, z0 + 1.898, z0 + 2.115, MATS["OLO_Cab_White"], col_2f, segs=24)
        add_cyl_mm("2F_MBR_OppCab_Decor_TumblerTopR", sx2 - 360.0, sy_front + 95.0, 38.0, z0 + 1.898, z0 + 2.010, MATS["Dark_Bronze_Recess"], col_2f, segs=12)
        add_box_mm("2F_MBR_OppCab_Decor_BooksMidL", sx1 + 260.0, sx1 + 400.0, sy_front + 45.0, yb - 75.0, z0 + 1.581, z0 + 1.795, MATS["Book_Cream"], col_2f)
        add_cyl_mm("2F_MBR_OppCab_Decor_VaseMidR", sx2 - 160.0, sy_front + 105.0, 56.0, z0 + 1.581, z0 + 1.740, MATS["OLO_Cab_White"], col_2f, segs=24)
        add_cyl_mm("2F_MBR_OppCab_Decor_RingBotL", sx1 + 310.0, sy_front + 95.0, 58.0, z0 + 1.234, z0 + 1.360, MATS["OLO_Cab_White"], col_2f, segs=24)
        add_box_mm("2F_MBR_OppCab_Decor_BookBotR", sx2 - 310.0, sx2 - 170.0, sy_front + 55.0, sy_front + 95.0, z0 + 1.234, z0 + 1.455, MATS["Dark_Bronze_Recess"], col_2f)

        # Suspended Floating Lower Console at Exact CAD Elevation (z: 0.219..0.891m, Marble Top 0.857..0.891m)
        cx_mid = 0.5 * (sx1 + sx2)
        cy_con = yf + 115.0
        add_box_mm("2F_MBR_OppCab_Console_Body", sx1, sx2, cy_con + 18.0, yb - 20.0, z0 + 0.219, z0 + 0.850, MATS["White_Shadow_Wood_Base"], col_2f, r_corner=42.0)
        add_box_mm("2F_MBR_OppCab_Console_Reveal", sx1 + 10.0, sx2 - 10.0, cy_con + 26.0, yb - 20.0, z0 + 0.850, z0 + 0.857, MATS["Dark_Bronze_Recess"], col_2f, r_corner=38.0)
        add_box_mm("2F_MBR_OppCab_Console_MarbleTop", sx1 - 4.0, sx2 + 4.0, cy_con - 2.0, yb - 20.0, z0 + 0.857, z0 + 0.891, MATS["Counter_Marble"], col_2f, r_corner=44.0)
        add_box_mm("2F_MBR_OppCab_Console_LED", sx1 + 25.0, sx2 - 25.0, cy_con + 55.0, yb - 45.0, z0 + 0.207, z0 + 0.219, MATS["Warm_LED_Glow"], col_2f)
        pan_xs = [sx1 + 44.0, sx1 + 44.0 + (sx2 - sx1 - 88.0) * 0.25, cx_mid, sx2 - 44.0 - (sx2 - sx1 - 88.0) * 0.25, sx2 - 44.0]
        for pi in range(4):
            pan_w_m = ((pan_xs[pi + 1] - 2.0) - (pan_xs[pi] + 2.0)) * MM
            pu0 = (pi * 0.23) % 1.0
            add_uv_front_box_mm(f"2F_MBR_OppCab_Console_Panel{pi+1}", pan_xs[pi] + 2.0, pan_xs[pi + 1] - 2.0, cy_con + 2.0, cy_con + 22.0, z0 + 0.223, z0 + 0.846, pu0, pu0 + pan_w_m / 0.62, 0.0, 0.623 / 0.62, MATS["White_Shadow_Wood"], col_2f)
            if pi > 0:
                add_box_mm(f"2F_MBR_OppCab_Console_Seam{pi}", pan_xs[pi] - 2.0, pan_xs[pi] + 2.0, cy_con + 10.0, cy_con + 24.0, z0 + 0.223, z0 + 0.846, MATS["Dark_Bronze_Recess"], col_2f)
        add_cyl_mm("2F_MBR_OppCab_Decor_SculptNeck", sx1 + 275.0, cy_con + 115.0, 32.0, z0 + 0.891, z0 + 1.010, MATS["OLO_ToeKick_Black"], col_2f, segs=20)
        add_cyl_mm("2F_MBR_OppCab_Decor_SculptHead", sx1 + 275.0, cy_con + 115.0, 62.0, z0 + 1.005, z0 + 1.135, MATS["OLO_ToeKick_Black"], col_2f, segs=24)
        add_box_mm("2F_MBR_OppCab_Decor_ArtFrame", sx2 - 390.0, sx2 - 110.0, cy_con + 125.0, cy_con + 148.0, z0 + 0.892, z0 + 1.130, MATS["Dark_Bronze_Recess"], col_2f)
        add_box_mm("2F_MBR_OppCab_Decor_ArtMat", sx2 - 378.0, sx2 - 122.0, cy_con + 123.0, cy_con + 135.0, z0 + 0.904, z0 + 1.118, MATS["OLO_Cab_White"], col_2f)
        add_uv_front_box_mm("2F_MBR_OppCab_Decor_ArtInner", sx2 - 340.0, sx2 - 160.0, cy_con + 121.0, cy_con + 126.0, z0 + 0.936, z0 + 1.086, 0.2, 0.8, 0.2, 0.8, MATS["Golden_Silk_Nanmu"], col_2f)

        # Far-Right CAD 290mm Open Shelf Display Column (x_local: 3500..3790, x: 6210..6500mm inside 200mm stepped wall recess yb+200=-1630)
        rx1, rx2 = x0 + 3500.0, x0 + 3790.0
        yb_col = yb + 200.0
        add_box_mm("2F_MBR_OppCab_Col_TopBrass", rx1, rx2, yf - scoop_d + 4.0, yb_col, z0 + h_body, z0 + h_tot, MATS["Antique_Champagne_Brass"], col_2f)
        add_box_mm("2F_MBR_OppCab_Col_BotBrass", rx1, rx2, yf - scoop_d + 4.0, yb_col, z0 + 0.000, z0 + 0.060, MATS["Antique_Champagne_Brass"], col_2f)
        add_box_mm("2F_MBR_OppCab_Col_CheekL", rx1, rx1 + 22.0, yf - scoop_d + 18.0, yb_col, z0 + 0.060, z0 + h_body, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_MBR_OppCab_Col_CheekR", rx2 - 22.0, rx2, yf - scoop_d + 18.0, yb_col, z0 + 0.060, z0 + h_body, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_MBR_OppCab_Col_Back", rx1 + 22.0, rx2 - 22.0, yb_col - 20.0, yb_col, z0 + 0.060, z0 + h_body, MATS["White_Shadow_Wood_Base"], col_2f)
        add_box_mm("2F_MBR_OppCab_Col_VertLED", rx1 + 35.0, rx2 - 35.0, yb_col - 36.0, yb_col - 20.0, z0 + 0.080, z0 + h_body - 0.020, MATS["Warm_LED_Glow"], col_2f)
        for ci, cz in enumerate([0.284, 0.508, 0.732, 0.956, 1.180, 1.404, 1.628, 1.852, 2.076, 2.300], 1):
            add_box_mm(f"2F_MBR_OppCab_Col_Shelf_{ci}", rx1 + 22.0, rx2 - 22.0, yf - scoop_d + 22.0, yb_col - 25.0, z0 + cz, z0 + cz + 0.014, MATS["Fluted_Changhong_Glass"], col_2f)
            add_box_mm(f"2F_MBR_OppCab_Col_Trim_{ci}", rx1 + 22.0, rx2 - 22.0, yf - scoop_d + 18.0, yf - scoop_d + 24.0, z0 + cz - 0.001, z0 + cz + 0.015, MATS["Antique_Champagne_Brass"], col_2f)

    build_2f_mbr_opp_wardrobe()
    # 2F North Bedroom South Wall Opposite-Bed Cabinet & Curved Art Alcove (x: 1800..6633, y: -1720..-1420, depth=300mm, unified H=2485/2500mm)
    def build_2f_northbed_opp_cabinet():
        yb = -1720.0
        yf = -1420.0
        z0 = z_2f
        h_cab = 2.485
        h_tot = 2.500

        # 1. Rightmost 22mm end filler + 1198mm 2-door flush wardrobe (x: 1800..3020)
        add_box_mm("2F_NorthBed_OppCab_R_Toe", 1800.0, 3020.0, yb, yf - 22.0, z0, z0 + 0.028, MATS["OLO_ToeKick_Black"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_R_BaseTrim", 1800.0, 3020.0, yf - 22.0, yf, z0, z0 + 0.028, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_R_BaseReveal", 1800.0, 3020.0, yb, yf - 8.0, z0 + 0.028, z0 + 0.034, MATS["OLO_ToeKick_Black"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_R_Carcass", 1800.0, 3020.0, yb, yf - 25.0, z0 + 0.034, z0 + h_cab, MATS["OLO_Cab_White"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_R_SeamBack", 1800.0, 3020.0, yf - 25.0, yf - 20.0, z0 + 0.034, z0 + h_cab, MATS["OLO_ToeKick_Black"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_R_Filler22", 1800.0, 1822.0, yf - 20.0, yf, z0 + 0.034, z0 + h_cab, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_R_Door1", 1824.0, 2419.0, yf - 20.0, yf, z0 + 0.034, z0 + h_cab, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_R_Door2", 2423.0, 3018.0, yf - 20.0, yf, z0 + 0.034, z0 + h_cab, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_R_TopGap", 1800.0, 3020.0, yb, yf - 10.0, z0 + h_cab, z0 + h_tot, MATS["OLO_ToeKick_Black"], col_2f)

        # 2. Fluted Frosted Changhong Glass Door Cabinet (602mm wide: x: 3020..3622)
        gx1, gx2 = 3020.0, 3622.0
        add_box_mm("2F_NorthBed_OppCab_G_Toe", gx1, gx2, yb, yf - 22.0, z0, z0 + 0.028, MATS["OLO_ToeKick_Black"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_BaseTrim", gx1, gx2, yf - 22.0, yf, z0, z0 + 0.028, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_BaseReveal", gx1, gx2, yb, yf - 8.0, z0 + 0.028, z0 + 0.034, MATS["OLO_ToeKick_Black"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_Back", gx1, gx2, yb, yb + 20.0, z0 + 0.034, z0 + h_cab, MATS["Oak_Veneer"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_CheekL", gx1, gx1 + 18.0, yb + 20.0, yf - 22.0, z0 + 0.034, z0 + h_cab, MATS["Oak_Veneer"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_CheekR", gx2 - 18.0, gx2, yb + 20.0, yf - 22.0, z0 + 0.034, z0 + h_cab, MATS["Oak_Veneer"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_Top", gx1, gx2, yb + 20.0, yf - 22.0, z0 + h_cab - 0.020, z0 + h_cab, MATS["Oak_Veneer"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_Bot", gx1, gx2, yb + 20.0, yf - 22.0, z0 + 0.034, z0 + 0.050, MATS["Oak_Veneer"], col_2f)
        for s_i, sz in enumerate([0.46, 0.93, 1.40, 1.87]):
            add_box_mm(f"2F_NorthBed_OppCab_G_Shelf_{s_i}", gx1 + 18.0, gx2 - 18.0, yb + 22.0, yf - 40.0, z0 + sz, z0 + sz + 0.020, MATS["Oak_Veneer"], col_2f)
            add_box_mm(f"2F_NorthBed_OppCab_G_LED_{s_i}", gx1 + 24.0, gx2 - 24.0, yb + 25.0, yb + 42.0, z0 + sz - 0.008, z0 + sz, MATS["Warm_LED_Glow"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_TopLED", gx1 + 24.0, gx2 - 24.0, yb + 25.0, yb + 45.0, z0 + h_cab - 0.028, z0 + h_cab - 0.020, MATS["Warm_LED_Glow"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_FrameL", gx1 + 2.0, gx1 + 20.0, yf - 22.0, yf, z0 + 0.034, z0 + h_cab, MATS["RoseGold_Metal"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_FrameR", gx2 - 20.0, gx2 - 2.0, yf - 22.0, yf, z0 + 0.034, z0 + h_cab, MATS["RoseGold_Metal"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_FrameB", gx1 + 20.0, gx2 - 20.0, yf - 22.0, yf, z0 + 0.034, z0 + 0.050, MATS["RoseGold_Metal"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_FrameT", gx1 + 20.0, gx2 - 20.0, yf - 22.0, yf, z0 + h_cab - 0.018, z0 + h_cab, MATS["RoseGold_Metal"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_Handle", gx1 + 4.0, gx1 + 14.0, yf, yf + 14.0, z0 + 0.86, z0 + 1.12, MATS["RoseGold_Metal"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_FrostPane", gx1 + 18.0, gx2 - 18.0, yf - 20.0, yf - 17.0, z0 + 0.050, z0 + h_cab - 0.018, MATS["Changhong_Frost_Diffuser"], col_2f)

        # Continuous smooth 3D sinusoidal vertical-ribbed Changhong glass pane
        n_ribs, rib_segs = 34, 6
        n_g_steps = n_ribs * rib_segs
        gx_in1, gx_in2 = gx1 + 18.0, gx2 - 18.0
        gz0_g, gz1_g = z0 + 0.050, z0 + h_cab - 0.018
        gy_b = (yf - 16.0) * MM
        mesh_cg = bpy.data.meshes.new("2F_NorthBed_OppCab_G_FlutedGlass")
        bm_cg = bmesh.new()
        cg_fb, cg_ft = [], []
        for gi in range(n_g_steps + 1):
            u = gi / float(n_g_steps)
            px = (gx_in1 + u * (gx_in2 - gx_in1)) * MM
            py = (yf - 12.0 + 4.0 * (1.0 - math.cos(2.0 * math.pi * n_ribs * u))) * MM
            cg_fb.append(bm_cg.verts.new((px, py, gz0_g)))
            cg_ft.append(bm_cg.verts.new((px, py, gz1_g)))
        c_vbl = bm_cg.verts.new((gx_in1 * MM, gy_b, gz0_g))
        c_vtl = bm_cg.verts.new((gx_in1 * MM, gy_b, gz1_g))
        c_vbr = bm_cg.verts.new((gx_in2 * MM, gy_b, gz0_g))
        c_vtr = bm_cg.verts.new((gx_in2 * MM, gy_b, gz1_g))
        for gi in range(n_g_steps):
            fg = bm_cg.faces.new([cg_fb[gi], cg_fb[gi + 1], cg_ft[gi + 1], cg_ft[gi]])
            fg.smooth = True
        for ff in [
            bm_cg.faces.new([c_vbr, c_vbl, c_vtl, c_vtr]),
            bm_cg.faces.new([c_vbl, cg_fb[0], cg_ft[0], c_vtl]),
            bm_cg.faces.new([cg_fb[-1], c_vbr, c_vtr, cg_ft[-1]]),
            bm_cg.faces.new([c_vbl, c_vbr] + list(reversed(cg_fb))),
            bm_cg.faces.new(cg_ft + [c_vtr, c_vtl]),
        ]:
            ff.smooth = False
        bmesh.ops.recalc_face_normals(bm_cg, faces=bm_cg.faces[:])
        cg_sharp = [
            e for e in bm_cg.edges
            if len(e.link_faces) == 2 and (
                e.link_faces[0].smooth != e.link_faces[1].smooth
                or e.link_faces[0].normal.dot(e.link_faces[1].normal) < 0.5
            )
        ]
        if cg_sharp:
            bmesh.ops.split_edges(bm_cg, edges=cg_sharp)
        bm_cg.to_mesh(mesh_cg)
        bm_cg.free()
        obj_cg = bpy.data.objects.new("2F_NorthBed_OppCab_G_FlutedGlass", mesh_cg)
        obj_cg.data.materials.append(MATS["Fluted_Changhong_Glass"])
        link_obj(obj_cg, col_2f)
        add_box_mm("2F_NorthBed_OppCab_G_TopGap", gx1, gx2, yb, yf - 10.0, z0 + h_cab, z0 + h_tot, MATS["OLO_ToeKick_Black"], col_2f)

        # 3. Open Shelving + 2 Drawers + 2-Door Lower Cabinet (1190mm wide per CAD: x: 3622..4812)
        mx1, mx2 = 3622.0, 4812.0
        add_box_mm("2F_NorthBed_OppCab_M_Toe", mx1, mx2, yb, yf - 22.0, z0, z0 + 0.028, MATS["OLO_ToeKick_Black"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_BaseTrim", mx1, mx2, yf - 22.0, yf, z0, z0 + 0.028, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_BaseReveal", mx1, mx2, yb, yf - 8.0, z0 + 0.028, z0 + 0.034, MATS["OLO_ToeKick_Black"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_BaseBody", mx1, mx2, yb, yf - 25.0, z0 + 0.034, z0 + 0.620, MATS["OLO_Cab_White"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_SeamBack", mx1, mx2, yf - 25.0, yf - 20.0, z0 + 0.034, z0 + 1.050, MATS["OLO_ToeKick_Black"], col_2f)
        m_mid = 0.5 * (mx1 + mx2)
        add_box_mm("2F_NorthBed_OppCab_M_BaseDoor1", mx1 + 2.0, m_mid - 2.0, yf - 20.0, yf, z0 + 0.034, z0 + 0.616, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_BaseDoor2", m_mid + 2.0, mx2 - 2.0, yf - 20.0, yf, z0 + 0.034, z0 + 0.616, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_DrwBody", mx1, mx2, yb, yf - 25.0, z0 + 0.620, z0 + 1.050, MATS["OLO_Cab_White"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_Drw1", mx1 + 2.0, mx2 - 2.0, yf - 20.0, yf, z0 + 0.622, z0 + 0.832, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_Drw2", mx1 + 2.0, mx2 - 2.0, yf - 20.0, yf, z0 + 0.838, z0 + 1.046, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_OpenBack", mx1, mx2, yb, yb + 20.0, z0 + 1.050, z0 + h_cab, MATS["Oak_Veneer"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_OpenCheekL", mx1, mx1 + 20.0, yb + 20.0, yf, z0 + 1.050, z0 + h_cab, MATS["Oak_Veneer"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_OpenCheekR", mx2 - 20.0, mx2, yb + 20.0, yf, z0 + 1.050, z0 + h_cab, MATS["Oak_Veneer"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_OpenBot", mx1 + 20.0, mx2 - 20.0, yb + 20.0, yf, z0 + 1.050, z0 + 1.072, MATS["Oak_Veneer"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_OpenTop", mx1 + 20.0, mx2 - 20.0, yb + 20.0, yf, z0 + h_cab - 0.022, z0 + h_cab, MATS["Oak_Veneer"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_M_TopLED", mx1 + 24.0, mx2 - 24.0, yb + 24.0, yb + 44.0, z0 + h_cab - 0.030, z0 + h_cab - 0.022, MATS["Warm_LED_Glow"], col_2f)
        for os_i, osz in enumerate([1.46, 1.88]):
            add_box_mm(f"2F_NorthBed_OppCab_M_Shelf_{os_i}", mx1 + 20.0, mx2 - 20.0, yb + 20.0, yf - 4.0, z0 + osz, z0 + osz + 0.022, MATS["Oak_Veneer"], col_2f)
            add_box_mm(f"2F_NorthBed_OppCab_M_ShelfLED_{os_i}", mx1 + 24.0, mx2 - 24.0, yb + 24.0, yb + 44.0, z0 + osz - 0.008, z0 + osz, MATS["Warm_LED_Glow"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_Decor_Books1", mx2 - 200.0, mx2 - 70.0, yb + 65.0, yb + 225.0, z0 + 1.902, z0 + 2.13, MATS["Book_Cream"], col_2f)
        add_cyl_mm("2F_NorthBed_OppCab_Decor_Vase", mx1 + 260.0, yb + 150.0, 65.0, z0 + 1.902, z0 + 2.11, MATS["Marble_Green_Pedestal"], col_2f, segs=24)
        add_box_mm("2F_NorthBed_OppCab_Decor_BookFlat", mx1 + 440.0, mx1 + 720.0, yb + 75.0, yb + 235.0, z0 + 1.482, z0 + 1.525, MATS["Book_Cream"], col_2f)
        add_cyl_mm("2F_NorthBed_OppCab_Decor_Bowl", mx1 + 580.0, yb + 155.0, 68.0, z0 + 1.525, z0 + 1.605, MATS["OLO_Cab_White"], col_2f, segs=24)
        add_box_mm("2F_NorthBed_OppCab_Decor_Books2", mx2 - 210.0, mx2 - 65.0, yb + 65.0, yb + 225.0, z0 + 1.072, z0 + 1.31, MATS["Book_Cream"], col_2f)
        add_cyl_mm("2F_NorthBed_OppCab_Decor_Jar", mx1 + 260.0, yb + 150.0, 58.0, z0 + 1.072, z0 + 1.23, MATS["OLO_Cab_White"], col_2f, segs=24)
        add_box_mm("2F_NorthBed_OppCab_M_TopGap", mx1, mx2, yb, yf - 10.0, z0 + h_cab, z0 + h_tot, MATS["OLO_ToeKick_Black"], col_2f)

        # 4. 5-Flute Scalloped Vertical Pilaster (224mm wide per CAD: x: 4812..5036)
        px1, px2 = 4812.0, 5036.0
        n_pw, p_segs = 5, 8
        n_p_steps = n_pw * p_segs
        mesh_pw = bpy.data.meshes.new("2F_NorthBed_OppCab_Pilaster_Wave")
        bm_pw = bmesh.new()
        py_b = yb * MM
        pw_fb, pw_ft = [], []
        for pi in range(n_p_steps + 1):
            u = pi / float(n_p_steps)
            px_m = (px1 + u * (px2 - px1)) * MM
            py_m = (yf - 12.0 + 6.0 * (1.0 - math.cos(2.0 * math.pi * n_pw * u))) * MM
            pw_fb.append(bm_pw.verts.new((px_m, py_m, z0)))
            pw_ft.append(bm_pw.verts.new((px_m, py_m, z0 + h_tot)))
        p_vbl = bm_pw.verts.new((px1 * MM, py_b, z0))
        p_vtl = bm_pw.verts.new((px1 * MM, py_b, z0 + h_tot))
        p_vbr = bm_pw.verts.new((px2 * MM, py_b, z0))
        p_vtr = bm_pw.verts.new((px2 * MM, py_b, z0 + h_tot))
        for pi in range(n_p_steps):
            fp = bm_pw.faces.new([pw_fb[pi], pw_fb[pi + 1], pw_ft[pi + 1], pw_ft[pi]])
            fp.smooth = True
        for ff in [
            bm_pw.faces.new([p_vbr, p_vbl, p_vtl, p_vtr]),
            bm_pw.faces.new([p_vbl, pw_fb[0], pw_ft[0], p_vtl]),
            bm_pw.faces.new([pw_fb[-1], p_vbr, p_vtr, pw_ft[-1]]),
            bm_pw.faces.new([p_vbl, p_vbr] + list(reversed(pw_fb))),
            bm_pw.faces.new(pw_ft + [p_vtr, p_vtl]),
        ]:
            ff.smooth = False
        bmesh.ops.recalc_face_normals(bm_pw, faces=bm_pw.faces[:])
        pw_sharp = [
            e for e in bm_pw.edges
            if len(e.link_faces) == 2 and (
                e.link_faces[0].smooth != e.link_faces[1].smooth
                or e.link_faces[0].normal.dot(e.link_faces[1].normal) < 0.5
            )
        ]
        if pw_sharp:
            bmesh.ops.split_edges(bm_pw, edges=pw_sharp)
        bm_pw.to_mesh(mesh_pw)
        bm_pw.free()
        obj_pw = bpy.data.objects.new("2F_NorthBed_OppCab_Pilaster_Wave", mesh_pw)
        obj_pw.data.materials.append(MATS["NorthBed_WaveGrille_Lacquer"])
        link_obj(obj_pw, col_2f)

        # 5. East Single-Curve Wall Panel (curves West into open cabinet only, runs flat along +200mm stepped wall to East window; world x: 5174..6495 after +0.138 shift)
        ax1, ax2 = 5036.0, 6357.0
        yb_a = -1530.0      # flush with stepped South wall face
        yf_flat = -1508.0   # 22mm flat wall panel all the way to the East window
        n_arc = 16
        mesh_alc = bpy.data.meshes.new("2F_NorthBed_OppCab_Alcove_CurveWall")
        bm_alc = bmesh.new()
        arc_pts = [
            (
                ax1 + 90.0 * (si / float(n_arc)),
                yf_flat + (yf - yf_flat) * (1.0 - math.sin(0.5 * math.pi * (si / float(n_arc)))),
            )
            for si in range(n_arc + 1)
        ]
        arc_pts.append((ax2, yf_flat))
        arc_rings = []
        for px_mm, py_front_mm in arc_pts:
            px_m = px_mm * MM
            py_front_m = py_front_mm * MM
            py_back_m = yb_a * MM
            v0 = bm_alc.verts.new((px_m, py_back_m, z0))
            v1 = bm_alc.verts.new((px_m, py_front_m, z0))
            v2 = bm_alc.verts.new((px_m, py_front_m, z0 + h_tot))
            v3 = bm_alc.verts.new((px_m, py_back_m, z0 + h_tot))
            arc_rings.append((v0, v1, v2, v3))
        for ai in range(len(arc_rings) - 1):
            r0, r1 = arc_rings[ai], arc_rings[ai + 1]
            for s in range(4):
                bm_alc.faces.new([r0[s], r0[(s + 1) % 4], r1[(s + 1) % 4], r1[s]])
        bm_alc.faces.new(list(arc_rings[0])[::-1])
        bm_alc.faces.new(list(arc_rings[-1]))
        bmesh.ops.recalc_face_normals(bm_alc, faces=bm_alc.faces[:])
        bm_alc.to_mesh(mesh_alc)
        bm_alc.free()
        for p in mesh_alc.polygons:
            p.use_smooth = (abs(p.normal.z) < 0.7)
        obj_alc = bpy.data.objects.new("2F_NorthBed_OppCab_Alcove_CurveWall", mesh_alc)
        obj_alc.data.materials.append(MATS["Wall_Panel_Cream"])
        link_obj(obj_alc, col_2f)

        a_flat_x1, a_flat_x2 = ax1 + 90.0, ax2
        add_box_mm("2F_NorthBed_OppCab_Alcove_LED", a_flat_x1 + 80.0, a_flat_x2 - 80.0, yf_flat, yf_flat + 35.0, z0 + h_tot - 0.030, z0 + h_tot - 0.015, MATS["Warm_LED_Glow"], col_2f)
        art_cx = 0.5 * (a_flat_x1 + a_flat_x2)
        art_w = 820.0
        add_box_mm("2F_NorthBed_OppCab_Art_Frame", art_cx - art_w * 0.5 - 12.0, art_cx + art_w * 0.5 + 12.0, yf_flat, yf_flat + 26.0, z0 + 0.56, z0 + 1.98, MATS["RoseGold_Metal"], col_2f)
        add_uv_front_box_mm("2F_NorthBed_OppCab_Art_Canvas", art_cx - art_w * 0.5, art_cx + art_w * 0.5, yf_flat + 20.0, yf_flat + 34.0, z0 + 0.572, z0 + 1.968, 0.0, 1.0, 0.0, 1.0, MATS["Child_Alcove_Art"], col_2f)
        bench_w = 1040.0
        add_box_mm("2F_NorthBed_OppCab_Bench_Base", art_cx - bench_w * 0.5 + 14.0, art_cx + bench_w * 0.5 - 14.0, yf_flat + 6.0, yf_flat + 290.0, z0 + 0.004, z0 + 0.052, MATS["Gold_Brass"], col_2f, r_corner=95.0)
        add_box_mm("2F_NorthBed_OppCab_Bench_Cushion", art_cx - bench_w * 0.5, art_cx + bench_w * 0.5, yf_flat - 2.0, yf_flat + 300.0, z0 + 0.052, z0 + 0.415, MATS["Bed_Linen"], col_2f, r_corner=110.0)

        # 6. Top Gypsum Bulkhead & Cove Ceiling Soffit stepped cleanly at ax1=5036 (world 5174)
        add_box_mm("2F_NorthBed_OppCab_Soffit", 1800.0, ax1, yb, yf, z0 + h_tot, z0 + h_2f, MATS["Pure_White_Ceiling"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_Soffit_East", ax1, ax2, yb_a, yf_flat, z0 + h_tot, z0 + h_2f, MATS["Pure_White_Ceiling"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_CeilingCove", 1800.0, ax2, yf_flat, yf_flat + 320.0, z0 + h_2f - 0.14, z0 + h_2f, MATS["Pure_White_Ceiling"], col_2f)
        add_box_mm("2F_NorthBed_OppCab_CeilingLED", 1840.0, ax2 - 40.0, yf_flat + 290.0, yf_flat + 320.0, z0 + h_2f - 0.135, z0 + h_2f - 0.120, MATS["Warm_LED_Glow"], col_2f)

    build_2f_northbed_opp_cabinet()
    # Shift 2F_NorthBed_OppCab +138mm East (1800..6297 -> 1938..6435) so 5-flute Pilaster lands flush at the 200mm wall step X=5174!
    for _ob in col_2f.objects:
        if _ob.name.startswith("2F_NorthBed_OppCab_") and _ob.data and hasattr(_ob.data, "vertices"):
            for _v in _ob.data.vertices:
                _v.co.x += 0.138
            _ob.data.update()

    # 2F North Bedroom (Secondary Bedroom): Headboard Wall with Vertical-Fluted Panels, Square Sea-Wave Painting,
    # Slim Linear Sconces, 2 Nightstands, Left 3-Door Wardrobe + Rounded Plaster Column, and Calibrated 1886mm En-Suite Bath
    add_box_mm("2F_NorthBath_Vanity", 1150, 1980, 600, 1150, zf_2f, z_2f + 0.84, MATS["Cabinet_Walnut"], col_2f)
    add_cyl_mm("2F_NorthBath_Basin", 1565, 875, 175.0, z_2f + 0.842, z_2f + 0.94, MATS["Sanitary_White"], col_2f)
    add_box_mm("2F_NorthBath_Toilet", 2060, 2530, 850, 1380, zf_2f, z_2f + 0.42, MATS["Sanitary_White"], col_2f, r_corner=50.0)
    add_box_mm("2F_NorthBath_ShowerGlass", 700, 1540, 150, 160, zf_2f, z_2f + 2.20, MATS["Window_Glass"], col_2f)

    # Left 3-Door High-Gloss Cream & Smoked-Mirror Kick-Panel Wardrobe flush to calibrated SecBath East wall X=2677 (x: 2677..3229, y: -214..1420, facing East +x)
    # Semicircular EndCorner (y: -490..-214) aligns flush with Door_1 at Y=-214, Wardrobe front X=3229, West wall X=2677, and SecBath corner Y=-490!
    add_box_mm("2F_NorthBed_Wardrobe_ToeKick", 2677.0, 3207.0, -214.0, 1420.0, zf_2f, z_2f + 0.014, MATS["OLO_ToeKick_Black"], col_2f)
    add_box_mm("2F_NorthBed_Wardrobe_Body", 2677.0, 3207.0, -214.0, 1420.0, z_2f + 0.014, z_2f + 2.500, MATS["NorthBed_Wardrobe_GlossCream"], col_2f)
    for wd_i in range(3):
        wy1 = -214.0 + wd_i * 545.0
        wy2 = wy1 + 541.0
        # Smoked-mirror lower kick panel (`z: 0.014..0.370`) + slim black reveal line (`0.370..0.382`) + high-gloss cream upper door (`0.382..2.496`)
        add_box_mm(f"2F_NorthBed_Wardrobe_MirrorBase_{wd_i+1}", 3207.0, 3229.0, wy1, wy2, z_2f + 0.014, z_2f + 0.370, MATS["NorthBed_Smoked_Mirror"], col_2f)
        add_box_mm(f"2F_NorthBed_Wardrobe_TrimLine_{wd_i+1}",   3207.0, 3227.0, wy1, wy2, z_2f + 0.370, z_2f + 0.382, MATS["OLO_ToeKick_Black"], col_2f)
        add_box_mm(f"2F_NorthBed_Wardrobe_Door_{wd_i+1}",       3207.0, 3229.0, wy1, wy2, z_2f + 0.382, z_2f + 2.496, MATS["NorthBed_Wardrobe_GlossCream"], col_2f)
        hx_y = wy2 - 32.0 if wd_i in (0, 2) else wy1 + 32.0
        add_box_mm(f"2F_NorthBed_Wardrobe_Handle_{wd_i+1}",     3229.0, 3243.0, hx_y - 11.0, hx_y + 11.0, z_2f + 0.56, z_2f + 0.72, MATS["NorthBed_JadeBlack_Pull"], col_2f)
    add_box_mm("2F_NorthBed_Wardrobe_Soffit", 2677.0, 3229.0, -214.0, 1420.0, z_2f + 2.500, z_2f + 2.830, MATS["Pure_White_Ceiling"], col_2f)
    # True smooth semicircular rounded end column at South end of wardrobe (x: 2677..3229, y: -490..-214, R=276mm)
    _w_cx, _w_cy, _w_r = 2953.0, -214.0, 276.0
    _pts_wcorner = [(_w_cx + _w_r * math.cos(math.radians(a)), _w_cy + _w_r * math.sin(math.radians(a))) for a in [180.0 + 180.0 * k / 32.0 for k in range(33)]]
    _obj_wcorner = add_prism("2F_NorthBed_Wardrobe_EndCorner", _pts_wcorner, zf_2f, z_2f + 2.500, MATS["Wall_Panel_Cream"], col_2f)
    if _obj_wcorner is not None:
        for _p in _obj_wcorner.data.polygons:
            _p.use_smooth = (abs(_p.normal.z) < 0.7)
    _obj_wcorner_sof = add_prism("2F_NorthBed_Wardrobe_Soffit_EndCorner", _pts_wcorner, z_2f + 2.500, z_2f + 2.830, MATS["Pure_White_Ceiling"], col_2f)
    if _obj_wcorner_sof is not None:
        for _p in _obj_wcorner_sof.data.polygons:
            _p.use_smooth = (abs(_p.normal.z) < 0.7)

    # Headboard Wall Paneling (calibrated clear span x: 3229..6495 = 3266 mm, center 4862 mm, facing South -y)
    add_box_mm("2F_NorthBed_HeadWall_Lower", 3229.0, 6495.0, 1385.0, 1420.0, zf_2f, z_2f + 1.08, MATS["Wall_Panel_Cream"], col_2f)
    bay_edges = [3229.0, 3785.0, 4340.0, 5390.0, 5945.0, 6495.0]
    add_box_mm("2F_NorthBed_HeadWall_UpperBack", 3229.0, 6495.0, 1392.0, 1420.0, z_2f + 1.08, z_2f + 2.500, MATS["OLO_Cab_Greige"], col_2f)

    def add_wave_grille_panel_mm(pname, x1, x2, y_back, y_valley, wave_depth, z0, z1, pitch_mm, mat, col):
        n_waves = max(12, int(round((x2 - x1) / pitch_mm)))
        segs_per_wave = 8
        n_steps = n_waves * segs_per_wave
        mesh_wg = bpy.data.meshes.new(pname)
        bm_wg = bmesh.new()
        yb_m = y_back * MM
        front_bot, front_top = [], []
        for i in range(n_steps + 1):
            u = i / float(n_steps)
            px = (x1 + u * (x2 - x1)) * MM
            py = (y_valley - 0.5 * wave_depth * (1.0 - math.cos(2.0 * math.pi * n_waves * u))) * MM
            front_bot.append(bm_wg.verts.new((px, py, z0)))
            front_top.append(bm_wg.verts.new((px, py, z1)))
        vb_l = bm_wg.verts.new((x1 * MM, yb_m, z0))
        vt_l = bm_wg.verts.new((x1 * MM, yb_m, z1))
        vb_r = bm_wg.verts.new((x2 * MM, yb_m, z0))
        vt_r = bm_wg.verts.new((x2 * MM, yb_m, z1))
        wave_faces = []
        for i in range(n_steps):
            fw = bm_wg.faces.new([front_bot[i], front_bot[i + 1], front_top[i + 1], front_top[i]])
            fw.smooth = True
            wave_faces.append(fw)
        flat_faces = [
            bm_wg.faces.new([vb_r, vb_l, vt_l, vt_r]),
            bm_wg.faces.new([vb_l, front_bot[0], front_top[0], vt_l]),
            bm_wg.faces.new([front_bot[-1], vb_r, vt_r, front_top[-1]]),
            bm_wg.faces.new([vb_l, vb_r] + list(reversed(front_bot))),
            bm_wg.faces.new(front_top + [vt_r, vt_l]),
        ]
        for ff in flat_faces:
            ff.smooth = False
        bmesh.ops.recalc_face_normals(bm_wg, faces=bm_wg.faces[:])
        sharp_edges = [
            e for e in bm_wg.edges
            if len(e.link_faces) == 2 and (
                e.link_faces[0].smooth != e.link_faces[1].smooth
                or e.link_faces[0].normal.dot(e.link_faces[1].normal) < 0.5
            )
        ]
        if sharp_edges:
            bmesh.ops.split_edges(bm_wg, edges=sharp_edges)
        bm_wg.to_mesh(mesh_wg)
        bm_wg.free()
        obj_wg = bpy.data.objects.new(pname, mesh_wg)
        obj_wg.data.materials.append(mat)
        link_obj(obj_wg, col)
        return obj_wg

    for b_i in range(len(bay_edges) - 1):
        bx1, bx2 = bay_edges[b_i] + 3.0, bay_edges[b_i + 1] - 3.0
        # 10cm (100mm) deep secondary-bedroom grille (y_back=1420 -> wave crest y=1320mm)
        add_wave_grille_panel_mm(
            f"2F_NorthBed_HeadWavePanel_{b_i+1}",
            bx1, bx2, 1420.0, 1390.0, 70.0,
            z_2f + 1.084, z_2f + 2.496, 34.0,
            MATS["NorthBed_WaveGrille_Lacquer"], col_2f
        )

    # Center Square Abstract Sea-Wave Painting (centered at x=4865: x: 4245..5485, z: 1.19..2.41m)
    add_box_mm("2F_NorthBed_HeadArt_Frame", 4235.0, 5495.0, 1354.0, 1370.5, z_2f + 1.18, z_2f + 2.42, MATS["RoseGold_Metal"], col_2f)
    add_uv_front_box_mm("2F_NorthBed_HeadArt_Canvas", 4245.0, 5485.0, 1348.0, 1360.0, z_2f + 1.19, z_2f + 2.41, 0.0, 1.0, 0.0, 1.0, MATS["NorthBed_Head_Art"], col_2f)

    # 2 Slim Vertical Linear Wall Sconces (x=3875 & x=5855, z: 1.18..1.98m)
    for sc_i, scx in enumerate([3875.0, 5855.0]):
        add_box_mm(f"2F_NorthBed_SconceBase_{sc_i+1}", scx - 14.0, scx + 14.0, 1345.0, 1373.0, z_2f + 1.26, z_2f + 1.40, MATS["Gold_Brass"], col_2f, r_corner=6.0)
        add_cyl_mm(f"2F_NorthBed_SconceTube_{sc_i+1}", scx, 1345.0, 8.0, z_2f + 1.18, z_2f + 1.98, MATS["Warm_LED_Glow"], col_2f, segs=12)

    # Bed, Upholstered Headboard, Pillows, Throw & Area Rug (centered at x=4865, width=1800mm: x: 3965..5765)
    add_box_mm("2F_NorthBed_Rug", 3465.0, 6265.0, -950.0, 1250.0, z_2f + 0.002, z_2f + 0.014, MATS["Rug_Warm"], col_2f, r_corner=20.0)
    add_box_mm("2F_NorthBed_Headboard_Trim", 3935.0, 5795.0, 1280.0, 1385.0, z_2f + 0.25, z_2f + 1.08, MATS["Oak_Veneer"], col_2f, r_corner=25.0)
    add_box_mm("2F_NorthBed_Headboard_Pad", 3960.0, 5770.0, 1265.0, 1360.0, z_2f + 0.28, z_2f + 1.055, MATS["Bed_Linen"], col_2f, r_corner=25.0)
    add_box_mm("2F_NorthBed_BedFrame", 3965.0, 5765.0, -620.0, 1340.0, zf_2f, z_2f + 0.36, MATS["OLO_Cab_White"], col_2f, r_corner=35.0)
    add_box_mm("2F_NorthBed_Mattress", 3995.0, 5735.0, -590.0, 1280.0, z_2f + 0.36, z_2f + 0.56, MATS["Bed_Linen"], col_2f, r_corner=45.0)
    add_box_mm("2F_NorthBed_Throw", 3980.0, 5750.0, -605.0, 420.0, z_2f + 0.56, z_2f + 0.59, MATS["Bed_Throw"], col_2f, r_corner=40.0)
    add_box_mm("2F_NorthBed_PillowW_L", 4105.0, 4825.0, 900.0, 1230.0, z_2f + 0.56, z_2f + 0.72, MATS["Bed_Linen"], col_2f, r_corner=50.0)
    add_box_mm("2F_NorthBed_PillowW_R", 4905.0, 5625.0, 900.0, 1230.0, z_2f + 0.56, z_2f + 0.72, MATS["Bed_Linen"], col_2f, r_corner=50.0)
    add_box_mm("2F_NorthBed_PillowG_L", 4285.0, 4765.0, 810.0, 1020.0, z_2f + 0.56, z_2f + 0.70, MATS["Wallcover_Grey"], col_2f, r_corner=40.0)
    add_box_mm("2F_NorthBed_PillowG_R", 4965.0, 5445.0, 810.0, 1020.0, z_2f + 0.56, z_2f + 0.70, MATS["Wallcover_Grey"], col_2f, r_corner=40.0)
    add_box_mm("2F_NorthBed_PillowAccent", 4675.0, 5055.0, 740.0, 910.0, z_2f + 0.56, z_2f + 0.67, MATS["Bed_Throw"], col_2f, r_corner=30.0)

    # Two Matching Nightstands (x: 3355..3855 & x: 5875..6375, y: 880..1385)
    for ns_i, (nx1, nx2) in enumerate([(3355.0, 3855.0), (5875.0, 6375.0)]):
        add_box_mm(f"2F_NorthBed_Night_Body_{ns_i+1}", nx1, nx2, 900.0, 1385.0, zf_2f, z_2f + 0.53, MATS["OLO_Cab_White"], col_2f)
        add_box_mm(f"2F_NorthBed_Night_Drw1_{ns_i+1}", nx1 + 4.0, nx2 - 4.0, 882.0, 900.0, z_2f + 0.03, z_2f + 0.275, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm(f"2F_NorthBed_Night_Drw2_{ns_i+1}", nx1 + 4.0, nx2 - 4.0, 882.0, 900.0, z_2f + 0.295, z_2f + 0.525, MATS["Wall_Panel_Cream"], col_2f)
        add_box_mm(f"2F_NorthBed_Night_Strip_{ns_i+1}", nx1 + 4.0, nx2 - 4.0, 886.0, 900.0, z_2f + 0.275, z_2f + 0.295, MATS["Oak_Veneer"], col_2f)
        add_box_mm(f"2F_NorthBed_Switch_{ns_i+1}", nx1 + 190.0, nx1 + 310.0, 1372.0, 1385.0, z_2f + 0.68, z_2f + 0.76, MATS["OLO_ToeKick_Black"], col_2f)
    add_cyl_mm("2F_NorthBed_Night_Vase", 3565.0, 1110.0, 65.0, z_2f + 0.53, z_2f + 0.66, MATS["Glass_Blue_Sphere"], col_2f, segs=24)
    add_box_mm("2F_NorthBed_Night_Book", 6055.0, 6225.0, 1040.0, 1220.0, z_2f + 0.53, z_2f + 0.56, MATS["Book_Cream"], col_2f)

    # Tray Cove Ceiling above Bed (unified 2.50m datum, hidden during bird's-eye render)
    add_box_mm("2F_NorthBed_HeadCove_Outer", 3229.0, 6495.0, -1100.0, 1420.0, z_2f + 2.500, z_2f + 2.830, MATS["Pure_White_Ceiling"], col_2f)
    add_box_mm("2F_NorthBed_HeadCove_LED", 3565.0, 6165.0, -820.0, 1140.0, z_2f + 2.485, z_2f + 2.500, MATS["Warm_LED_Glow"], col_2f)

    # 2F CAD linework removed to eliminate floating rods/lines across open 1F->2F stairwell
    # add_cad_linework_curve(msp, "2F", p_2f["xr"], p_2f["yr"], *p_2f["orig"], z_2f + 0.008, col_2f)

    # Apply floor offsets if requested
    for k, (dx, dy, dz) in floor_offsets_xy.items():
        if abs(dx) > 1e-4 or abs(dy) > 1e-4 or abs(dz) > 1e-4:
            for obj in cols[k].objects:
                obj.location.x += dx
                obj.location.y += dy
                obj.location.z += dz

    return cols


# ---------------------------------------------------------------------------
# Lighting & Camera Rendering Helpers
# ---------------------------------------------------------------------------
def setup_world_and_lights():
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = 'METAL'
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        scene.cycles.device = 'GPU'
    except Exception:
        pass
    scene.cycles.samples = 128
    scene.cycles.max_bounces = 12
    scene.cycles.diffuse_bounces = 6
    scene.cycles.glossy_bounces = 6
    scene.cycles.transmission_bounces = 12
    scene.cycles.transparent_max_bounces = 12
    scene.cycles.use_denoising = True

    # Color Management: Filmic Medium High Contrast, balanced architectural interior exposure (rev. 2026-11-06)
    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look = 'Medium High Contrast'
    scene.view_settings.exposure = 0.02

    world = bpy.data.worlds.new("ArchWorld")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.94, 0.95, 0.96, 1.0)
        bg.inputs[1].default_value = 0.72

    sun_data = bpy.data.lights.new(name="Sun_Key", type='SUN')
    sun_data.energy = 1.65
    sun_data.angle = math.radians(12.0)
    sun_data.color = (1.0, 0.96, 0.90)
    sun_obj = bpy.data.objects.new("Sun_Key", sun_data)
    sun_obj.rotation_euler = (math.radians(36.0), math.radians(-16.0), math.radians(28.0))
    scene.collection.objects.link(sun_obj)

    fill_data = bpy.data.lights.new(name="Area_Fill", type='AREA')
    fill_data.energy = 850.0
    fill_data.size = 26.0
    fill_data.color = (0.92, 0.96, 1.0)
    fill_obj = bpy.data.objects.new("Area_Fill", fill_data)
    fill_obj.location = (-6.0, -12.0, 24.0)
    fill_obj.rotation_euler = (math.radians(28.0), 0.0, math.radians(-20.0))
    scene.collection.objects.link(fill_obj)


def look_at(cam_obj, target):
    direction = Vector(target) - cam_obj.location
    rot_quat = direction.to_track_quat('-Z', 'Y')
    cam_obj.rotation_euler = rot_quat.to_euler()


def render_view(filepath, cam_loc, target, ortho_scale=None, lens=38.0, res=(2200, 1600), shift_y=0.0, level_horiz=False, clip_start=0.1):
    target_filter = os.environ.get("RENDER_FILTER", "")
    if target_filter:
        tokens = [t.strip() for t in target_filter.split(",") if t.strip()]
        bname = os.path.basename(filepath)
        if tokens and not any(t in bname for t in tokens):
            print(f"[SKIP RENDER] {bname} does not match filter {target_filter}")
            return
    scene = bpy.context.scene
    scene.render.resolution_x = res[0]
    scene.render.resolution_y = res[1]
    scene.render.filepath = filepath

    cam_data = bpy.data.cameras.new("RenderCam")
    if ortho_scale is not None:
        cam_data.type = 'ORTHO'
        cam_data.ortho_scale = ortho_scale
    else:
        cam_data.type = 'PERSP'
        cam_data.lens = lens
    cam_data.clip_start = clip_start
    cam_data.clip_end = 200.0
    if shift_y != 0.0:
        cam_data.shift_y = shift_y
    cam_obj = bpy.data.objects.new("RenderCam", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = Vector(cam_loc)
    if level_horiz:
        dx = target[0] - cam_loc[0]
        dy = target[1] - cam_loc[1]
        yaw = math.atan2(dx, dy)
        cam_obj.rotation_euler = (math.radians(90.0), 0.0, -yaw)
    else:
        look_at(cam_obj, target)
    scene.camera = cam_obj

    bpy.ops.render.render(write_still=True)
    scene.collection.objects.unlink(cam_obj)
    bpy.data.objects.remove(cam_obj)
    bpy.data.cameras.remove(cam_data)


def set_only_collections_visible(cols, active_keys):
    for k, c in cols.items():
        hide = (k not in active_keys)
        c.hide_render = hide
        c.hide_viewport = hide


def main():
    print("Loading DXF:", DXF_PATH)
    doc = ezdxf.readfile(DXF_PATH)
    msp = doc.modelspace()

    # Copy DXF to output dir for user convenience
    import shutil
    shutil.copyfile(DXF_PATH, os.path.join(OUT_DIR, "4层家装_11.2.dxf"))

    # --- Pass 1: True Stacked 4-Floor Model & Individual Floor Renders ---
    bpy.ops.wm.read_factory_settings(use_empty=True)
    init_materials()
    setup_world_and_lights()
    cols = build_house_floors(msp)

    blend_path = os.path.join(OUT_DIR, "4层家装_11.2.blend")
    glb_stacked = os.path.join(OUT_DIR, "4层家装_11.2.glb")
    obj_stacked = os.path.join(OUT_DIR, "4层家装_11.2.obj")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    bpy.ops.export_scene.gltf(filepath=glb_stacked, export_format='GLB')
    bpy.ops.wm.obj_export(filepath=obj_stacked)

    # Export full house and individual floor models to Pascal导入 directory for Pascal Editor
    pascal_dir = os.path.join(OUT_DIR, "Pascal导入")
    os.makedirs(pascal_dir, exist_ok=True)
    whole_house_path = os.path.join(pascal_dir, "全屋_whole_house.glb")
    shutil.copyfile(glb_stacked, whole_house_path)

    floor_exports = [
        ("B2.glb", "B2_Base"),
        ("B1.glb", "B1_Mezz"),
        ("1F.glb", "1F_Plan"),
        ("2F.glb", "2F_Plan")
    ]
    for glb_name, col_name in floor_exports:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in cols[col_name].objects:
            obj.select_set(True)
        out_fp = os.path.join(pascal_dir, glb_name)
        bpy.ops.export_scene.gltf(filepath=out_fp, export_format='GLB', use_selection=True)
    bpy.ops.object.select_all(action='DESELECT')
    print("ALL PASCAL GLB MODELS EXPORTED TO:", pascal_dir)

    # Hide 1F_Living_Ceiling_* and B1_Ceiling_* during bird's-eye renders so top-down views can see inside
    ceil_objs_1f = [o for o in cols["1F_Plan"].objects if o.name.startswith("1F_Living_Ceiling_")]
    for co in ceil_objs_1f:
        co.hide_render = True
    ceil_objs_b1 = [o for o in cols["B1_Mezz"].objects if o.name.startswith("B1_Ceiling_")]
    for co in ceil_objs_b1:
        co.hide_render = True

    # 1. Stacked 4-Floor Isometric View
    set_only_collections_visible(cols, ["B2_Base", "B1_Mezz", "1F_Plan", "2F_Plan"])
    render_view(
        os.path.join(OUT_DIR, "preview_stacked_cutaway.png"),
        cam_loc=(-11.5, -17.5, 16.5),
        target=(-0.4, -1.8, 0.6),
        lens=36.0,
        res=(2200, 1650)
    )

    # 2. 1F Ground Floor Bird's-Eye Render (steeper angle for full room visibility)
    set_only_collections_visible(cols, ["1F_Plan"])
    render_view(
        os.path.join(OUT_DIR, "preview_1F_一层.png"),
        cam_loc=(-0.1, -9.8, 16.8),
        target=(-0.1, -2.0, 0.6),
        lens=38.0,
        res=(2200, 1500)
    )

    # 2b. 1F Dining Room L-Shaped Neo-Chinese Sideboard & Banquette Render (matching media_1795367527550_6dc6804b.jpg)
    for co in ceil_objs_1f:
        co.hide_render = False
    hidden_for_dining_render = []
    for obj in cols["1F_Plan"].objects:
        if obj.name.startswith(("1F_Kitchen_", "1F_Foyer_", "1F_Spiral_", "1F_To_2F_Spiral", "1F_StairGuard_", "1F_Living_Ceiling_FlatW", "1F_Toilet_Clad_D", "1F_Toilet_Skirt_D", "1F_Toilet_Crown_D")) or "CAD_Overlay" in obj.name or "CAD_Lines" in obj.name:
            obj.hide_render = True
            hidden_for_dining_render.append(obj)
    _sun_dn = bpy.data.objects.get("Sun_Key")
    _orig_sun_dn = _sun_dn.data.energy if _sun_dn else 1.65
    _af_dn = bpy.data.objects.get("Area_Fill")
    _orig_af_dn = _af_dn.data.energy if _af_dn else 850.0
    _wbg_dn = bpy.context.scene.world.node_tree.nodes.get("Background") if (bpy.context.scene.world and bpy.context.scene.world.use_nodes) else None
    _orig_wbg_dn = _wbg_dn.inputs[1].default_value if _wbg_dn else 0.72
    if _sun_dn:
        _sun_dn.data.energy = 0.0
    if _af_dn:
        _af_dn.data.energy = 20.0
    if _wbg_dn:
        _wbg_dn.inputs[1].default_value = 0.14
    _z_1f_dn = PLANS["1F_Plan"]["z0"]
    dining_fill_data = bpy.data.lights.new(name="DiningRoomFill", type='AREA')
    dining_fill_data.energy = 58.0
    dining_fill_data.color = (1.0, 0.97, 0.93)
    dining_fill_data.size = 3.2
    dining_fill_obj = bpy.data.objects.new(name="DiningRoomFill", object_data=dining_fill_data)
    bpy.context.scene.collection.objects.link(dining_fill_obj)
    dining_fill_obj.location = (-2.80, -2.50, _z_1f_dn + 2.35)
    look_at(dining_fill_obj, (-3.90, -0.20, _z_1f_dn + 1.25))

    dn_wave_data = bpy.data.lights.new(name="DiningWaveAlcoveWash", type='AREA')
    dn_wave_data.shape = 'RECTANGLE'
    dn_wave_data.size = 1.25
    dn_wave_data.size_y = 0.12
    dn_wave_data.energy = 26.0
    dn_wave_data.color = (1.0, 0.86, 0.62)
    dn_wave_obj = bpy.data.objects.new(name="DiningWaveAlcoveWash", object_data=dn_wave_data)
    bpy.context.scene.collection.objects.link(dn_wave_obj)
    dn_wave_obj.location = (-3.396, -0.05, _z_1f_dn + 1.62)
    look_at(dn_wave_obj, (-3.396, 0.16, _z_1f_dn + 1.05))

    render_view(
        os.path.join(OUT_DIR, "preview_1F_餐厅_无限单脚桌.png"),
        cam_loc=(-2.62, -3.12, _z_1f_dn + 1.24),
        target=(-3.78, -0.15, _z_1f_dn + 1.22),
        lens=20.0,
        res=(1920, 1440),
        level_horiz=True
    )
    bpy.data.objects.remove(dn_wave_obj, do_unlink=True)
    bpy.data.lights.remove(dn_wave_data, do_unlink=True)
    bpy.data.objects.remove(dining_fill_obj, do_unlink=True)
    bpy.data.lights.remove(dining_fill_data, do_unlink=True)
    if _sun_dn:
        _sun_dn.data.energy = _orig_sun_dn
    if _af_dn:
        _af_dn.data.energy = _orig_af_dn
    if _wbg_dn:
        _wbg_dn.inputs[1].default_value = _orig_wbg_dn
    for obj in hidden_for_dining_render:
        obj.hide_render = False
    for co in ceil_objs_1f:
        co.hide_render = True

    # 2c. 1F Kitchen & Foyer Front Perspective Render (matching reference OLO kitchen front rendering)
    hidden_for_kitchen_render = []
    for obj in cols["1F_Plan"].objects:
        if obj.name.startswith("1F_Dining_"):
            obj.hide_render = True
            hidden_for_kitchen_render.append(obj)
    render_view(
        os.path.join(OUT_DIR, "preview_1F_厨房_正面效果图.png"),
        cam_loc=(-4.20, 0.15, 1.25),
        target=(-4.20, -3.80, 1.22),
        lens=24.0,
        res=(2000, 1000)
    )
    for obj in hidden_for_kitchen_render:
        obj.hide_render = False

    # 2d. 1F Kitchen Island Close-Up 3/4 Render (matching reference island cross-section & drawer/door layout)
    hidden_for_island_render = []
    hide_prefixes_island = (
        "1F_Kitchen_Counter_", "1F_Kitchen_S_", "1F_Kitchen_Stove",
        "1F_Kitchen_Burner", "1F_Kitchen_Black_Backsplash",
        "1F_Kitchen_RangeHood", "1F_Kitchen_Upper_", "1F_Kitchen_Steamer_"
    )
    for obj in cols["1F_Plan"].objects:
        if obj.name.startswith(hide_prefixes_island):
            obj.hide_render = True
            hidden_for_island_render.append(obj)
    render_view(
        os.path.join(OUT_DIR, "preview_1F_厨房_岛台特写.png"),
        cam_loc=(-4.65, -4.50, 1.48),
        target=(-3.30, -3.22, 0.46),
        lens=26.0,
        res=(1920, 1200)
    )
    for obj in hidden_for_island_render:
        obj.hide_render = False

    # 2e. 1F Living Room TV Cabinet (Open Interior Shelving) & Sculpted 3-Wave Ceiling Front Render
    for co in ceil_objs_1f:
        co.hide_render = False
    hidden_for_tv_render = []
    for obj in cols["1F_Plan"].objects:
        if obj.name.startswith(("1F_Living_CurvedSofa", "1F_Living_Sofa", "1F_Living_CoffeeTable", "1F_Living_Armchair", "1F_Living_Fireplace", "1F_Living_Rug", "1F_CAD_Linework", "1F_Kaspar_Frame", "1F_Kaspar_Wing", "1F_Kaspar_Relief", "1F_Kaspar_Stone", "1F_Kaspar_Center", "1F_VentShaft_")):
            obj.hide_render = True
            hidden_for_tv_render.append(obj)
    # Photorealistic interior design lighting for wave ceiling, flying birds, ocean mural & celadon floor
    # (rev. 2026-11-06: eliminated upper-left ceiling/header overexposure per user comment: 这里的光线有点过爆炸)
    _area_fill_obj = bpy.data.objects.get("Area_Fill")
    _orig_fill_energy = _area_fill_obj.data.energy if _area_fill_obj else 850.0
    if _area_fill_obj:
        _area_fill_obj.data.energy = 85.0
    _world_bg = bpy.context.scene.world.node_tree.nodes.get("Background") if (bpy.context.scene.world and bpy.context.scene.world.use_nodes) else None
    _orig_bg_strength = _world_bg.inputs[1].default_value if _world_bg else 0.72
    if _world_bg:
        _world_bg.inputs[1].default_value = 0.32

    # Grazing East window key light raking across the 3D wave ceiling vaults (authentic interior daylighting)
    ldata_tv = bpy.data.lights.new("TVRoomFill", type='AREA')
    ldata_tv.shape = 'RECTANGLE'
    ldata_tv.energy = 95.0
    ldata_tv.size = 2.10
    ldata_tv.size_y = 0.16
    ldata_tv.color = (1.0, 0.98, 0.95)
    lobj_tv = bpy.data.objects.new("TVRoomFill", ldata_tv)
    bpy.context.scene.collection.objects.link(lobj_tv)
    lobj_tv.location = (6.42, -0.15, 2.575)
    look_at(lobj_tv, (3.10, 0.25, 2.68))

    ldata_tv2 = bpy.data.lights.new("TVRoomBounce", type='AREA')
    ldata_tv2.energy = 34.0
    ldata_tv2.size = 3.8
    ldata_tv2.color = (0.99, 0.98, 0.96)
    lobj_tv2 = bpy.data.objects.new("TVRoomBounce", ldata_tv2)
    bpy.context.scene.collection.objects.link(lobj_tv2)
    lobj_tv2.location = (3.20, -2.40, 1.10)
    look_at(lobj_tv2, (3.60, 1.20, 0.95))

    # Warm natural sunlight streaming in through the East floor-to-ceiling window (1F_Win_Living_E, x=6.50..6.74m, y=-1.37..+1.19m)
    # per user comment: 这外面是窗，可以晒阳光进来
    ldata_w_sun = bpy.data.lights.new("TVWindowSunPortal", type='AREA')
    ldata_w_sun.energy = 95.0
    ldata_w_sun.size = 1.40
    ldata_w_sun.color = (1.0, 0.92, 0.76)
    lobj_w_sun = bpy.data.objects.new("TVWindowSunPortal", ldata_w_sun)
    bpy.context.scene.collection.objects.link(lobj_w_sun)
    lobj_w_sun.location = (6.46, -0.10, 1.35)
    look_at(lobj_w_sun, (4.40, 0.30, 0.05))

    ldata_w_beam = bpy.data.lights.new("TVWindowSunBeam", type='SPOT')
    ldata_w_beam.energy = 280.0
    ldata_w_beam.color = (1.0, 0.90, 0.70)
    ldata_w_beam.spot_size = math.radians(34.0)
    ldata_w_beam.spot_blend = 0.50
    ldata_w_beam.shadow_soft_size = 0.14
    lobj_w_beam = bpy.data.objects.new("TVWindowSunBeam", ldata_w_beam)
    bpy.context.scene.collection.objects.link(lobj_w_beam)
    lobj_w_beam.location = (6.72, -0.20, 1.75)
    look_at(lobj_w_beam, (4.80, 0.45, 0.02))

    # First render with exterior folding doors hidden to show open multi-grid bookcase
    hidden_fold_doors = []
    for obj in cols["1F_Plan"].objects:
        if obj.name.startswith(("1F_Living_TVCab_Fold", "1F_Living_TVCab_Outer", "1F_Living_TVCab_Shoe", "1F_Living_TVCab_TravertineHearth", "1F_Living_TVCab_GreenHearth", "1F_Living_TVCab_Niche")):
            obj.hide_render = True
            hidden_fold_doors.append(obj)
    render_view(
        os.path.join(OUT_DIR, "preview_1F_客厅_电视柜与天花板.png"),
        cam_loc=(3.65, -2.75, 1.32),
        target=(3.65, 1.13, 1.32),
        lens=21.6,
        res=(1920, 1070)
    )
    for obj in hidden_fold_doors:
        obj.hide_render = False

    # 2f. 1F Living Room TV Cabinet with 8 Jade-Green Luxury Stone Folding Doors Closed & Wave Travertine Hearth
    # Ensure all interior troughs and open shelves are completely hidden so nothing pokes out into the open plinth niche
    hidden_troughs = [o for o in cols["1F_Plan"].objects if "TVCab_Trough" in o.name or "TVCab_Sh_" in o.name]
    for o in hidden_troughs:
        o.hide_render = True
    render_view(
        os.path.join(OUT_DIR, "preview_1F_客厅_电视柜_折叠门闭合.png"),
        cam_loc=(3.65, -2.75, 1.32),
        target=(3.65, 1.13, 1.32),
        lens=21.6,
        res=(1920, 1070)
    )

    # 2f-up. Upward-looking view from below showing the entire 1F ceiling ("截图一张从下往上看整个一楼天花板的图片")
    hidden_for_up_ceil = []
    for obj in cols["1F_Plan"].objects:
        if obj.name.startswith(("1F_Slab_", "1F_StairGuard_", "1F_To_2F_Spiral")):
            obj.hide_render = True
            hidden_for_up_ceil.append(obj)
    ldata_w_beam.energy = 0.0
    ldata_w_sun.energy = 0.0
    ldata_up = bpy.data.lights.new("TVUpCeilFill", type='AREA')
    ldata_up.energy = 155.0
    ldata_up.size = 6.2
    ldata_up.color = (1.0, 0.98, 0.95)
    lobj_up = bpy.data.objects.new("TVUpCeilFill", ldata_up)
    bpy.context.scene.collection.objects.link(lobj_up)
    lobj_up.location = (3.10, -1.10, 0.20)
    look_at(lobj_up, (3.10, -0.50, 2.70))
    render_view(
        os.path.join(OUT_DIR, "preview_1F_天花板_仰视图.png"),
        cam_loc=(2.85, -1.15, -1.52),
        target=(2.85, -1.10, 2.66),
        lens=21.0,
        res=(1920, 1350)
    )
    ldata_w_beam.energy = 280.0
    ldata_w_sun.energy = 95.0
    bpy.context.scene.collection.objects.unlink(lobj_up)
    bpy.data.objects.remove(lobj_up)
    bpy.data.lights.remove(ldata_up)
    for obj in hidden_for_up_ceil:
        obj.hide_render = False

    if _area_fill_obj:
        _area_fill_obj.data.energy = _orig_fill_energy
    if _world_bg:
        _world_bg.inputs[1].default_value = _orig_bg_strength
    bpy.context.scene.collection.objects.unlink(lobj_tv)
    bpy.data.objects.remove(lobj_tv)
    bpy.data.lights.remove(ldata_tv)
    bpy.context.scene.collection.objects.unlink(lobj_tv2)
    bpy.data.objects.remove(lobj_tv2)
    bpy.data.lights.remove(ldata_tv2)
    bpy.context.scene.collection.objects.unlink(lobj_w_sun)
    bpy.data.objects.remove(lobj_w_sun)
    bpy.data.lights.remove(ldata_w_sun)
    bpy.context.scene.collection.objects.unlink(lobj_w_beam)
    bpy.data.objects.remove(lobj_w_beam)
    bpy.data.lights.remove(ldata_w_beam)
    for o in hidden_troughs:
        o.hide_render = False
    for obj in hidden_for_tv_render:
        obj.hide_render = False

    # 2g. 1F Kaspar Foyer Partition Screen & Living Room Front Render (matching media_1793051800333_90002acd.jpg)
    hidden_kaspar = [o for o in cols["1F_Plan"].objects if "CAD_Overlay" in o.name]
    for o in hidden_kaspar:
        o.hide_render = True
    ldata_kaspar = bpy.data.lights.new("KasparSunFill", type='AREA')
    ldata_kaspar.energy = 650.0
    ldata_kaspar.size = 3.2
    ldata_kaspar.color = (1.0, 0.97, 0.91)
    lobj_kaspar = bpy.data.objects.new("KasparSunFill", ldata_kaspar)
    bpy.context.scene.collection.objects.link(lobj_kaspar)
    lobj_kaspar.location = (6.40, -0.60, 1.85)
    look_at(lobj_kaspar, (4.20, -2.10, 0.90))
    render_view(
        os.path.join(OUT_DIR, "preview_1F_卡斯帕玄关_正面效果图.png"),
        cam_loc=(4.78, 0.85, 1.28),
        target=(4.58, -2.25, 1.28),
        lens=23.0,
        res=(1920, 1440)
    )
    bpy.context.scene.collection.objects.unlink(lobj_kaspar)
    bpy.data.objects.remove(lobj_kaspar)
    bpy.data.lights.remove(ldata_kaspar)
    for o in hidden_kaspar:
        o.hide_render = False

    # 2h. 1F Toilet Frosted Silk-Brushed Glass Door Front Render (SL-3553)
    _sun_1f = bpy.data.objects.get("Sun_Key")
    _orig_sun_1f = _sun_1f.data.energy if _sun_1f else 1.65
    _af_1f = bpy.data.objects.get("Area_Fill")
    _orig_af_1f = _af_1f.data.energy if _af_1f else 850.0
    _wbg_1f = bpy.context.scene.world.node_tree.nodes.get("Background") if (bpy.context.scene.world and bpy.context.scene.world.use_nodes) else None
    _orig_wbg_1f = _wbg_1f.inputs[1].default_value if _wbg_1f else 0.72
    if _sun_1f:
        _sun_1f.data.energy = 0.0
    if _af_1f:
        _af_1f.data.energy = 18.0
    if _wbg_1f:
        _wbg_1f.inputs[1].default_value = 0.14
    _z_1f_int = PLANS["1F_Plan"]["z0"]
    _temp_ceil_1f_wc = add_box_mm("Temp_1F_ToiletCorridorCeil", -1750.0, 950.0, -5760.0, -1450.0, _z_1f_int + 3.152, _z_1f_int + 3.240, MATS["Pure_White_Ceiling"], bpy.context.scene.collection)
    ldata_1fwc_fill = bpy.data.lights.new("1FToiletFrontFill", type='AREA')
    ldata_1fwc_fill.shape = 'RECTANGLE'
    ldata_1fwc_fill.size = 1.6
    ldata_1fwc_fill.size_y = 1.6
    ldata_1fwc_fill.energy = 46.0
    ldata_1fwc_fill.color = (1.0, 0.97, 0.93)
    lobj_1fwc_fill = bpy.data.objects.new("1FToiletFrontFill", ldata_1fwc_fill)
    bpy.context.scene.collection.objects.link(lobj_1fwc_fill)
    lobj_1fwc_fill.location = (-0.30, -2.55, 2.75)
    look_at(lobj_1fwc_fill, (-0.30, -4.25, 1.20))

    ldata_1fwc_back = bpy.data.lights.new("1FToiletBackGlow", type='AREA')
    ldata_1fwc_back.shape = 'RECTANGLE'
    ldata_1fwc_back.size = 1.3
    ldata_1fwc_back.size_y = 0.9
    ldata_1fwc_back.energy = 48.0
    ldata_1fwc_back.color = (1.0, 0.90, 0.74)
    lobj_1fwc_back = bpy.data.objects.new("1FToiletBackGlow", ldata_1fwc_back)
    bpy.context.scene.collection.objects.link(lobj_1fwc_back)
    lobj_1fwc_back.location = (-0.30, -4.95, 2.55)
    look_at(lobj_1fwc_back, (-0.30, -4.35, 1.05))

    render_view(
        os.path.join(OUT_DIR, "preview_1F_卫生间门.png"),
        cam_loc=(-0.30, -2.02, 1.30),
        target=(-0.30, -4.28, 1.24),
        lens=22.0,
        res=(1920, 1440),
        level_horiz=True
    )
    for _lo, _ld in [(lobj_1fwc_back, ldata_1fwc_back), (lobj_1fwc_fill, ldata_1fwc_fill)]:
        bpy.context.scene.collection.objects.unlink(_lo)
        bpy.data.objects.remove(_lo)
        bpy.data.lights.remove(_ld)
    if _temp_ceil_1f_wc is not None:
        _tc1_mesh = _temp_ceil_1f_wc.data
        bpy.context.scene.collection.objects.unlink(_temp_ceil_1f_wc)
        bpy.data.objects.remove(_temp_ceil_1f_wc)
        bpy.data.meshes.remove(_tc1_mesh)
    if _sun_1f:
        _sun_1f.data.energy = _orig_sun_1f
    if _af_1f:
        _af_1f.data.energy = _orig_af_1f
    if _wbg_1f:
        _wbg_1f.inputs[1].default_value = _orig_wbg_1f

    # 2i. 1F Living Room South Feature Wall with Sculptural Inverted-T Linear Fireplace
    hidden_fp_cad = [o for o in cols["1F_Plan"].objects if "CAD_Overlay" in o.name or "CAD_Lines" in o.name]
    for o in hidden_fp_cad:
        o.hide_render = True
    _sun_fp = bpy.data.objects.get("Sun_Key")
    _orig_sun_fp = _sun_fp.data.energy if _sun_fp else 1.65
    _af_fp = bpy.data.objects.get("Area_Fill")
    _orig_af_fp = _af_fp.data.energy if _af_fp else 850.0
    _wbg_fp = bpy.context.scene.world.node_tree.nodes.get("Background") if (bpy.context.scene.world and bpy.context.scene.world.use_nodes) else None
    _orig_wbg_fp = _wbg_fp.inputs[1].default_value if _wbg_fp else 0.72
    if _sun_fp:
        _sun_fp.data.energy = 0.0
    if _af_fp:
        _af_fp.data.energy = 22.0
    if _wbg_fp:
        _wbg_fp.inputs[1].default_value = 0.14

    _z_1f_fp = PLANS["1F_Plan"]["z0"]
    _temp_ceil_1f_fp = add_box_mm("Temp_1F_FPCeilingCap", -1500.0, 4800.0, -1760.0, 1400.0, _z_1f_fp + 2.860, _z_1f_fp + 2.940, MATS["Pure_White_Ceiling"], bpy.context.scene.collection)
    _fp_lights = []
    for _lname, _loc, _tgt, _sz, _szy, _eng, _col in [
        ("1FFPOverhead", (2.7235, -2.50, _z_1f_fp + 2.45), (2.7235, -4.60, _z_1f_fp + 0.85), 3.4, 2.4, 62.0, (1.0, 0.97, 0.92)),
        ("1FFPEastWin",  (5.40, -3.20, _z_1f_fp + 1.65),   (2.50, -4.40, _z_1f_fp + 1.25),   1.8, 1.8, 56.0, (0.98, 0.99, 1.0)),
        ("1FFPChandelierGlow", (2.7235, -2.75, _z_1f_fp + 1.88), (2.7235, -2.75, _z_1f_fp + 0.40), 0.70, 0.70, 26.0, (1.0, 0.90, 0.70)),
        ("1FFPFireGlow", (2.7235, -5.29, _z_1f_fp + 0.65), (2.7235, -5.51, _z_1f_fp + 0.90), 1.05, 0.14, 38.0, (1.0, 0.60, 0.18)),
    ]:
        _ld = bpy.data.lights.new(_lname, type='AREA')
        _ld.shape = 'RECTANGLE'
        _ld.size = _sz
        _ld.size_y = _szy
        _ld.energy = _eng
        _ld.color = _col
        _lo = bpy.data.objects.new(_lname, _ld)
        bpy.context.scene.collection.objects.link(_lo)
        _lo.location = _loc
        if _lname in ("1FFPFireGlow", "1FFPChandelierGlow"):
            _lo.visible_glossy = False
        look_at(_lo, _tgt)
        _fp_lights.append((_lo, _ld))

    render_view(
        os.path.join(OUT_DIR, "preview_1F_客厅_壁炉背景墙.png"),
        cam_loc=(2.7235, -0.15, _z_1f_fp + 1.34),
        target=(2.7235, -5.51, _z_1f_fp + 1.32),
        lens=16.5,
        res=(1920, 1440),
        level_horiz=True
    )
    for _lo, _ld in _fp_lights:
        bpy.context.scene.collection.objects.unlink(_lo)
        bpy.data.objects.remove(_lo)
        bpy.data.lights.remove(_ld)
    _tfc_mesh = _temp_ceil_1f_fp.data
    bpy.context.scene.collection.objects.unlink(_temp_ceil_1f_fp)
    bpy.data.objects.remove(_temp_ceil_1f_fp)
    bpy.data.meshes.remove(_tfc_mesh)
    for o in hidden_fp_cad:
        o.hide_render = False
    if _sun_fp:
        _sun_fp.data.energy = _orig_sun_fp
    if _af_fp:
        _af_fp.data.energy = _orig_af_fp
    if _wbg_fp:
        _wbg_fp.inputs[1].default_value = _orig_wbg_fp

    for co in ceil_objs_1f:
        co.hide_render = True

    # 3. 2F Second Floor Bird's-Eye Render (hide ceiling cove so 30cm cabinet footprint is unobstructed)
    set_only_collections_visible(cols, ["2F_Plan"])
    _hide_2f_cove = [o for o in cols["2F_Plan"].objects if o.name in ("2F_NorthBed_OppCab_CeilingCove", "2F_NorthBed_OppCab_CeilingLED", "2F_NorthBed_HeadCove_Outer", "2F_NorthBed_HeadCove_LED")]
    for o in _hide_2f_cove:
        o.hide_render = True
    render_view(
        os.path.join(OUT_DIR, "preview_2F_二层.png"),
        cam_loc=(-1.0, -10.8, 21.5),
        target=(-1.0, -1.9, 4.0),
        lens=38.0,
        res=(2200, 1500)
    )
    for o in _hide_2f_cove:
        o.hide_render = False

    # 3b. 2F North Bedroom Headboard Interior Perspective (matching media_1794846588713_812293f2.jpg + scalloped wave grille)
    _sun_2f = bpy.data.objects.get("Sun_Key")
    _orig_sun_2f = _sun_2f.data.energy if _sun_2f else 1.65
    _af_2f = bpy.data.objects.get("Area_Fill")
    _orig_af_2f = _af_2f.data.energy if _af_2f else 850.0
    _wbg_2f = bpy.context.scene.world.node_tree.nodes.get("Background") if (bpy.context.scene.world and bpy.context.scene.world.use_nodes) else None
    _orig_wbg_2f = _wbg_2f.inputs[1].default_value if _wbg_2f else 0.72
    if _sun_2f:
        _sun_2f.data.energy = 0.0
    if _af_2f:
        _af_2f.data.energy = 0.0
    if _wbg_2f:
        _wbg_2f.inputs[1].default_value = 0.10

    _z_2f_int = PLANS["2F_Plan"]["z0"]
    _temp_ceil_2f = add_box_mm("Temp_2F_InteriorCeiling", -600.0, 6850.0, -5400.0, 1550.0, _z_2f_int + 2.83, _z_2f_int + 2.93, MATS["Pure_White_Ceiling"], bpy.context.scene.collection)

    ldata_2fnb_h = bpy.data.lights.new("NorthBedHeadFill", type='AREA')
    ldata_2fnb_h.energy = 28.0
    ldata_2fnb_h.size = 3.2
    ldata_2fnb_h.color = (1.0, 0.98, 0.94)
    lobj_2fnb_h = bpy.data.objects.new("NorthBedHeadFill", ldata_2fnb_h)
    bpy.context.scene.collection.objects.link(lobj_2fnb_h)
    lobj_2fnb_h.location = (4.80, -0.85, 5.15)
    look_at(lobj_2fnb_h, (5.05, 1.25, 4.35))

    ldata_2fnb_rake = bpy.data.lights.new("NorthBedEastRake", type='AREA')
    ldata_2fnb_rake.shape = 'RECTANGLE'
    ldata_2fnb_rake.size = 0.35
    ldata_2fnb_rake.size_y = 1.85
    ldata_2fnb_rake.energy = 58.0
    ldata_2fnb_rake.color = (0.96, 0.98, 1.0)
    lobj_2fnb_rake = bpy.data.objects.new("NorthBedEastRake", ldata_2fnb_rake)
    bpy.context.scene.collection.objects.link(lobj_2fnb_rake)
    lobj_2fnb_rake.location = (6.56, 0.85, 4.75)
    look_at(lobj_2fnb_rake, (3.85, 1.35, 4.85))

    _nb_sc_lights = []
    for _si, _sx in enumerate([4.16, 6.12]):
        _sd = bpy.data.lights.new(f"NorthBedSconcePt_{_si+1}", type='POINT')
        _sd.energy = 2.8
        _sd.shadow_soft_size = 0.08
        _sd.color = (1.0, 0.86, 0.64)
        _so = bpy.data.objects.new(f"NorthBedSconcePt_{_si+1}", _sd)
        bpy.context.scene.collection.objects.link(_so)
        _so.location = (_sx, 1.26, 4.88)
        _nb_sc_lights.append((_so, _sd))

    render_view(
        os.path.join(OUT_DIR, "preview_2F_北卧_榻榻米与主床.png"),
        cam_loc=(5.05, -1.32, 4.45),
        target=(5.05, 1.35, 4.45),
        lens=19.0,
        res=(1920, 1080),
        level_horiz=True
    )
    for _so, _sd in _nb_sc_lights:
        bpy.context.scene.collection.objects.unlink(_so)
        bpy.data.objects.remove(_so)
        bpy.data.lights.remove(_sd)
    bpy.context.scene.collection.objects.unlink(lobj_2fnb_rake)
    bpy.data.objects.remove(lobj_2fnb_rake)
    bpy.data.lights.remove(ldata_2fnb_rake)
    bpy.context.scene.collection.objects.unlink(lobj_2fnb_h)
    bpy.data.objects.remove(lobj_2fnb_h)
    bpy.data.lights.remove(ldata_2fnb_h)

    # 3c. 2F North Bedroom Opposite-Bed Cabinet Front Render (matching Image 1 & CAD Image 2)
    hidden_nb_bath_wall = [o for o in cols["2F_Plan"].objects if o.name.startswith(("2F_NorthBed_Wardrobe_", "2F_NorthBed_Bath_", "2F_NorthBath_", "2F_CurvedWall_Parent", "2F_Door_ParentBath_"))]
    for o in hidden_nb_bath_wall:
        o.hide_render = True
    ldata_2fnb = bpy.data.lights.new("NorthBedOppCabFill", type='AREA')
    ldata_2fnb.shape = 'RECTANGLE'
    ldata_2fnb.energy = 42.0
    ldata_2fnb.size = 4.6
    ldata_2fnb.size_y = 1.2
    ldata_2fnb.color = (1.0, 0.98, 0.94)
    lobj_2fnb = bpy.data.objects.new("NorthBedOppCabFill", ldata_2fnb)
    bpy.context.scene.collection.objects.link(lobj_2fnb)
    lobj_2fnb.location = (4.22, 0.25, 5.40)
    look_at(lobj_2fnb, (4.22, -1.50, 4.40))

    ldata_2fnb_e = bpy.data.lights.new("NorthBedOppCabEast", type='AREA')
    ldata_2fnb_e.shape = 'RECTANGLE'
    ldata_2fnb_e.energy = 48.0
    ldata_2fnb_e.size = 0.55
    ldata_2fnb_e.size_y = 1.90
    ldata_2fnb_e.color = (0.97, 0.99, 1.0)
    lobj_2fnb_e = bpy.data.objects.new("NorthBedOppCabEast", ldata_2fnb_e)
    bpy.context.scene.collection.objects.link(lobj_2fnb_e)
    lobj_2fnb_e.location = (6.55, -0.85, 4.65)
    look_at(lobj_2fnb_e, (3.80, -1.48, 4.50))

    ldata_2fnb_alc = bpy.data.lights.new("NorthBedAlcoveSpot", type='AREA')
    ldata_2fnb_alc.shape = 'RECTANGLE'
    ldata_2fnb_alc.energy = 9.0
    ldata_2fnb_alc.size = 0.90
    ldata_2fnb_alc.size_y = 0.14
    ldata_2fnb_alc.color = (1.0, 0.88, 0.70)
    lobj_2fnb_alc = bpy.data.objects.new("NorthBedAlcoveSpot", ldata_2fnb_alc)
    bpy.context.scene.collection.objects.link(lobj_2fnb_alc)
    lobj_2fnb_alc.location = (5.80, -1.58, 5.55)
    look_at(lobj_2fnb_alc, (5.80, -1.62, 4.20))

    ldata_2fnb_gl = bpy.data.lights.new("NorthBedGlassGlow", type='AREA')
    ldata_2fnb_gl.shape = 'RECTANGLE'
    ldata_2fnb_gl.energy = 7.5
    ldata_2fnb_gl.size = 0.48
    ldata_2fnb_gl.size_y = 2.05
    ldata_2fnb_gl.color = (1.0, 0.87, 0.66)
    lobj_2fnb_gl = bpy.data.objects.new("NorthBedGlassGlow", ldata_2fnb_gl)
    bpy.context.scene.collection.objects.link(lobj_2fnb_gl)
    lobj_2fnb_gl.location = (3.32, -1.64, 4.48)
    look_at(lobj_2fnb_gl, (3.32, -1.30, 4.48))

    render_view(
        os.path.join(OUT_DIR, "preview_2F_北卧_床对面柜子.png"),
        cam_loc=(4.22, 1.22, 4.46),
        target=(4.22, -1.42, 4.46),
        lens=16.0,
        res=(1920, 1080),
        level_horiz=True,
        clip_start=1.95
    )
    for o in hidden_nb_bath_wall:
        o.hide_render = False
    for _lo, _ld in [(lobj_2fnb_gl, ldata_2fnb_gl), (lobj_2fnb_alc, ldata_2fnb_alc), (lobj_2fnb_e, ldata_2fnb_e), (lobj_2fnb, ldata_2fnb)]:
        bpy.context.scene.collection.objects.unlink(_lo)
        bpy.data.objects.remove(_lo)
        bpy.data.lights.remove(_ld)

    # 3d. 2F Master Bedroom Vanity Close-Up Render (Optical Wood Shadow / 光学木影系列 cabinet doors)
    ldata_van_rake = bpy.data.lights.new("MBRVanityEastRake", type='AREA')
    ldata_van_rake.shape = 'RECTANGLE'
    ldata_van_rake.size = 0.45
    ldata_van_rake.size_y = 1.90
    ldata_van_rake.energy = 46.0
    ldata_van_rake.color = (0.98, 0.98, 0.96)
    lobj_van_rake = bpy.data.objects.new("MBRVanityEastRake", ldata_van_rake)
    bpy.context.scene.collection.objects.link(lobj_van_rake)
    lobj_van_rake.location = (6.64, -4.15, 4.60)
    look_at(lobj_van_rake, (5.50, -4.85, 4.10))

    ldata_van_fill = bpy.data.lights.new("MBRVanityFill", type='AREA')
    ldata_van_fill.size = 2.8
    ldata_van_fill.energy = 26.0
    ldata_van_fill.color = (1.0, 0.97, 0.93)
    lobj_van_fill = bpy.data.objects.new("MBRVanityFill", ldata_van_fill)
    bpy.context.scene.collection.objects.link(lobj_van_fill)
    lobj_van_fill.location = (5.30, -2.90, 5.10)
    look_at(lobj_van_fill, (5.95, -4.95, 4.25))

    render_view(
        os.path.join(OUT_DIR, "preview_2F_主卧_梳妆台.png"),
        cam_loc=(5.90, -2.60, 4.42),
        target=(5.96, -5.05, 4.42),
        lens=26.0,
        res=(1920, 1440),
        level_horiz=True
    )

    # 3e. 2F Master Bedroom Opposite-Bed North Wardrobe Front Render (Sculpted Curved White Shadow Wood + Golden Silk Nanmu Alcove)
    hidden_mbr_bed = [o for o in cols["2F_Plan"].objects if o.name.startswith(("2F_MBR_Bed_", "2F_MBR_Night_"))]
    for o in hidden_mbr_bed:
        o.hide_render = True
    ldata_mw_rake = bpy.data.lights.new("MBRWardEastRake", type='AREA')
    ldata_mw_rake.shape = 'RECTANGLE'
    ldata_mw_rake.size = 0.55
    ldata_mw_rake.size_y = 1.95
    ldata_mw_rake.energy = 44.0
    ldata_mw_rake.color = (0.98, 0.99, 1.0)
    lobj_mw_rake = bpy.data.objects.new("MBRWardEastRake", ldata_mw_rake)
    bpy.context.scene.collection.objects.link(lobj_mw_rake)
    lobj_mw_rake.location = (6.62, -3.05, 4.70)
    look_at(lobj_mw_rake, (4.10, -2.35, 4.55))

    ldata_mw_fill = bpy.data.lights.new("MBRWardFill", type='AREA')
    ldata_mw_fill.size = 4.2
    ldata_mw_fill.energy = 28.0
    ldata_mw_fill.color = (1.0, 0.98, 0.94)
    lobj_mw_fill = bpy.data.objects.new("MBRWardFill", ldata_mw_fill)
    bpy.context.scene.collection.objects.link(lobj_mw_fill)
    lobj_mw_fill.location = (4.65, -4.15, 5.45)
    look_at(lobj_mw_fill, (4.805, -2.35, 4.45))

    _mw_wash_lights = []
    for wi, (wz, wen) in enumerate([(5.18, 3.8), (4.855, 3.8), (4.53, 3.8), (3.51, 4.8)], 1):
        _wd = bpy.data.lights.new(f"MBRWardWash_{wi}", type='AREA')
        _wd.shape = 'RECTANGLE'
        _wd.size = 1.22
        _wd.size_y = 0.06
        _wd.energy = wen
        _wd.color = (1.0, 0.87, 0.66)
        _wo = bpy.data.objects.new(f"MBRWardWash_{wi}", _wd)
        bpy.context.scene.collection.objects.link(_wo)
        _wo.location = (4.68, -1.94, wz)
        look_at(_wo, (4.68, -1.86, wz - 0.55))
        _mw_wash_lights.append((_wo, _wd))

    render_view(
        os.path.join(OUT_DIR, "preview_2F_主卧_床尾柜.png"),
        cam_loc=(4.805, -4.75, 4.48),
        target=(4.805, -2.35, 4.48),
        lens=19.0,
        res=(1920, 1080),
        level_horiz=True
    )
    for o in hidden_mbr_bed:
        o.hide_render = False
    for _lo, _ld in _mw_wash_lights + [(lobj_mw_fill, ldata_mw_fill), (lobj_mw_rake, ldata_mw_rake)]:
        bpy.context.scene.collection.objects.unlink(_lo)
        bpy.data.objects.remove(_lo)
        bpy.data.lights.remove(_ld)

    # 3f. 2F Master Walk-In Closet Perspective Render (Swapped South 3-Door Mirror-Glass Wardrobe)
    ldata_wic_fill = bpy.data.lights.new("WICCorridorFill", type='AREA')
    ldata_wic_fill.shape = 'RECTANGLE'
    ldata_wic_fill.size = 1.8
    ldata_wic_fill.size_y = 0.6
    ldata_wic_fill.energy = 18.0
    ldata_wic_fill.color = (1.0, 0.97, 0.92)
    lobj_wic_fill = bpy.data.objects.new("WICCorridorFill", ldata_wic_fill)
    bpy.context.scene.collection.objects.link(lobj_wic_fill)
    lobj_wic_fill.location = (0.45, -4.05, 5.90)
    lobj_wic_fill.visible_glossy = False
    look_at(lobj_wic_fill, (0.40, -4.25, 4.30))

    ldata_wic_gl = bpy.data.lights.new("WICGlassInnerGlow", type='AREA')
    ldata_wic_gl.shape = 'RECTANGLE'
    ldata_wic_gl.size = 1.45
    ldata_wic_gl.size_y = 1.8
    ldata_wic_gl.energy = 48.0
    ldata_wic_gl.color = (1.0, 0.88, 0.66)
    lobj_wic_gl = bpy.data.objects.new("WICGlassInnerGlow", ldata_wic_gl)
    bpy.context.scene.collection.objects.link(lobj_wic_gl)
    lobj_wic_gl.location = (0.38, -4.72, 4.75)
    lobj_wic_gl.visible_glossy = False
    look_at(lobj_wic_gl, (0.38, -5.22, 4.55))

    ldata_mb_back = bpy.data.lights.new("MasterBathBackGlow", type='AREA')
    ldata_mb_back.shape = 'RECTANGLE'
    ldata_mb_back.size = 1.4
    ldata_mb_back.size_y = 1.4
    ldata_mb_back.energy = 42.0
    ldata_mb_back.color = (1.0, 0.90, 0.75)
    lobj_mb_back = bpy.data.objects.new("MasterBathBackGlow", ldata_mb_back)
    bpy.context.scene.collection.objects.link(lobj_mb_back)
    lobj_mb_back.location = (-1.60, -4.00, 5.45)
    look_at(lobj_mb_back, (-0.55, -4.00, 4.45))

    render_view(
        os.path.join(OUT_DIR, "preview_2F_主卧_衣帽间镜面柜.png"),
        cam_loc=(1.65, -3.58, 4.48),
        target=(0.36, -4.68, 4.42),
        lens=17.5,
        res=(1920, 1440),
        level_horiz=True
    )

    # 3f-north. 2F Master Walk-In Closet North Run Render (Optical Wood Shadow 4-door wardrobe + 见光板)
    ldata_wics_rake = bpy.data.lights.new("WICSouthEastRake", type='AREA')
    ldata_wics_rake.shape = 'RECTANGLE'
    ldata_wics_rake.size = 0.65
    ldata_wics_rake.size_y = 1.90
    ldata_wics_rake.energy = 36.0
    ldata_wics_rake.color = (0.99, 0.98, 0.96)
    lobj_wics_rake = bpy.data.objects.new("WICSouthEastRake", ldata_wics_rake)
    bpy.context.scene.collection.objects.link(lobj_wics_rake)
    lobj_wics_rake.location = (1.60, -3.95, 4.70)
    look_at(lobj_wics_rake, (0.20, -3.42, 4.45))

    render_view(
        os.path.join(OUT_DIR, "preview_2F_主卧_衣帽间南柜.png"),
        cam_loc=(1.70, -4.18, 4.55),
        target=(0.15, -3.35, 4.55),
        lens=19.0,
        res=(1920, 1440),
        level_horiz=True
    )
    for _lo, _ld in [(lobj_wics_rake, ldata_wics_rake), (lobj_mb_back, ldata_mb_back), (lobj_wic_gl, ldata_wic_gl), (lobj_wic_fill, ldata_wic_fill)]:
        bpy.context.scene.collection.objects.unlink(_lo)
        bpy.data.objects.remove(_lo)
        bpy.data.lights.remove(_ld)

    # 3g. 2F Secondary Bedroom En-Suite Bathroom Frosted Silk-Brushed Glass Door Render (SL-3553)
    ldata_pb_fill = bpy.data.lights.new("ParentBathDoorFill", type='AREA')
    ldata_pb_fill.shape = 'RECTANGLE'
    ldata_pb_fill.size = 1.5
    ldata_pb_fill.size_y = 0.8
    ldata_pb_fill.energy = 28.0
    ldata_pb_fill.color = (1.0, 0.97, 0.93)
    lobj_pb_fill = bpy.data.objects.new("ParentBathDoorFill", ldata_pb_fill)
    bpy.context.scene.collection.objects.link(lobj_pb_fill)
    lobj_pb_fill.location = (3.10, -1.05, 5.55)
    look_at(lobj_pb_fill, (2.05, -0.45, 4.45))

    ldata_pb_back = bpy.data.lights.new("ParentBathBackGlow", type='AREA')
    ldata_pb_back.shape = 'RECTANGLE'
    ldata_pb_back.size = 1.3
    ldata_pb_back.size_y = 1.0
    ldata_pb_back.energy = 40.0
    ldata_pb_back.color = (1.0, 0.90, 0.75)
    lobj_pb_back = bpy.data.objects.new("ParentBathBackGlow", ldata_pb_back)
    bpy.context.scene.collection.objects.link(lobj_pb_back)
    lobj_pb_back.location = (2.05, 0.70, 5.45)
    look_at(lobj_pb_back, (2.05, -0.40, 4.45))

    render_view(
        os.path.join(OUT_DIR, "preview_2F_次卧卫浴门.png"),
        cam_loc=(3.45, -1.24, 4.42),
        target=(2.05, -0.42, 4.42),
        lens=18.0,
        res=(1920, 1440),
        level_horiz=True
    )
    for _lo, _ld in [(lobj_pb_back, ldata_pb_back), (lobj_pb_fill, ldata_pb_fill)]:
        bpy.context.scene.collection.objects.unlink(_lo)
        bpy.data.objects.remove(_lo)
        bpy.data.lights.remove(_ld)

    if _temp_ceil_2f is not None:
        _tc_mesh = _temp_ceil_2f.data
        bpy.context.scene.collection.objects.unlink(_temp_ceil_2f)
        bpy.data.objects.remove(_temp_ceil_2f)
        bpy.data.meshes.remove(_tc_mesh)
    if _sun_2f:
        _sun_2f.data.energy = _orig_sun_2f
    if _af_2f:
        _af_2f.data.energy = _orig_af_2f
    if _wbg_2f:
        _wbg_2f.inputs[1].default_value = _orig_wbg_2f
    bpy.context.scene.collection.objects.unlink(lobj_van_fill)
    bpy.data.objects.remove(lobj_van_fill)
    bpy.data.lights.remove(ldata_van_fill)
    bpy.context.scene.collection.objects.unlink(lobj_van_rake)
    bpy.data.objects.remove(lobj_van_rake)
    bpy.data.lights.remove(ldata_van_rake)

    # 4. B1 + B2 Double-Height Basement Bird's-Eye Render (showing B1 Mezzanine + Void looking down into B2 Lounge!)
    set_only_collections_visible(cols, ["B2_Base", "B1_Mezz"])
    render_view(
        os.path.join(OUT_DIR, "preview_B1_B2_地下室.png"),
        cam_loc=(2.6, -9.2, 9.8),
        target=(2.6, -2.1, -3.0),
        lens=38.0,
        res=(2200, 1600)
    )

    # 4b. B2 + B1 Double-Height Basement Interior Perspective Render (matching media_1793051728146_c18c89c6.jpg)
    for co in ceil_objs_b1:
        co.hide_render = False
    hidden_b2_cad = [o for o in list(cols["B2_Base"].objects) + list(cols["B1_Mezz"].objects) if "CAD_Overlay" in o.name]
    for o in hidden_b2_cad:
        o.hide_render = True
    bsm_lights = []
    for l_idx, (lx, ly, lz, tx, ty, tz, l_eng, l_sz) in enumerate([
        (1.80, -3.80, -0.45,  1.60, -1.50, -3.20, 260.0, 3.6),
        (2.40, -0.20, -1.80,  2.40,  0.50, -2.28, 120.0, 2.4),
        (2.60, -0.60, -2.65,  2.80,  0.50, -3.80, 140.0, 2.2),
    ]):
        ld = bpy.data.lights.new(f"BsmFill_{l_idx}", type='AREA')
        ld.energy = l_eng
        ld.size = l_sz
        ld.color = (1.0, 0.95, 0.88)
        lo = bpy.data.objects.new(f"BsmFill_{l_idx}", ld)
        bpy.context.scene.collection.objects.link(lo)
        lo.location = (lx, ly, lz)
        look_at(lo, (tx, ty, tz))
        bsm_lights.append((lo, ld))

    # 4b. Basement Front Full View (architectural 2-point perspective, zero keystoning distortion)
    render_view(
        os.path.join(OUT_DIR, "preview_B2_B1_地下室_正面效果图.png"),
        cam_loc=(2.15, -5.32, -3.20),
        target=(2.15, 0.20, -3.20),
        lens=19.5,
        res=(2048, 1152),
        shift_y=0.22,
        level_horiz=True
    )

    # 4b2. Overhead View of B2 Lounge & Stair matching reference photos & user feedback
    # Temporarily hide B1 ceiling plate so top-down view looks cleanly onto B1 Mezzanine S-curve, Grand Staircase & B2 Lounge!
    for co in ceil_objs_b1:
        co.hide_render = True
    render_view(
        os.path.join(OUT_DIR, "preview_B2_旋转楼梯_俯瞰透视图.png"),
        cam_loc=(2.35, -2.55, 1.15),
        target=(2.35, -2.55, -4.55),
        lens=21.0,
        res=(1700, 1800)
    )
    for co in ceil_objs_b1:
        co.hide_render = False

    # 4c. Perspective View strictly matching the site construction skeleton photo (IMG_7189.HEIC)
    # Framed in 4:3 ratio with architectural 2-point perspective: vertical lines 100% plumb,
    # 13-step curved stair with ink-wash marble treads on West side,
    # S-curved mezzanine wrapping outside the round column with 312mm clearance,
    # oval ceiling cove, and white grid bookcase!
    render_view(
        os.path.join(OUT_DIR, "preview_B2_夹层与楼梯_骨架透视图.png"),
        cam_loc=(1.40, -5.45, -3.35),
        target=(2.40, 0.10, -2.35),
        lens=17.0,
        res=(2048, 1536),
        shift_y=0.34,
        level_horiz=True
    )

    # 4d. B2 Entry Door Right Shoe Cabinet & Figurine Close-Up
    render_view(
        os.path.join(OUT_DIR, "preview_B2_玄关鞋柜_特写.png"),
        cam_loc=(-0.25, 0.45, -3.20),
        target=(-1.20, 0.45, -3.25),
        lens=24.0,
        res=(1920, 1440)
    )
    for lo, ld in bsm_lights:
        bpy.context.scene.collection.objects.unlink(lo)
        bpy.data.objects.remove(lo)
        bpy.data.lights.remove(ld)
    for o in hidden_b2_cad:
        o.hide_render = False
    for co in ceil_objs_b1:
        co.hide_render = True

    # --- Pass 2: Side-by-Side 2x2 Architectural Showcase of All 4 Floors ---
    rf = os.environ.get("RENDER_FILTER", "")
    if rf and ("showcase" not in rf and "all" not in rf):
        print(f"[SKIP PASS 2] Skipping Pass 2 because RENDER_FILTER={rf}")
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    init_materials()
    setup_world_and_lights()
    showcase_offsets = {
        "1F_Plan": (-9.5,  5.2,  0.00),
        "2F_Plan": ( 9.5,  5.2, -3.30),
        "B1_Mezz": (-9.5, -5.2,  2.40),
        "B2_Base": ( 9.5, -5.2,  4.55),
    }
    cols_sh = build_house_floors(msp, floor_offsets_xy=showcase_offsets)
    for o in cols_sh["1F_Plan"].objects:
        if o.name.startswith("1F_Living_Ceiling_"):
            o.hide_render = True
    for o in cols_sh["B1_Mezz"].objects:
        if o.name.startswith("B1_Ceiling_"):
            o.hide_render = True
    glb_showcase = os.path.join(OUT_DIR, "4层家装_11.2_展开展示.glb")
    bpy.ops.export_scene.gltf(filepath=glb_showcase, export_format='GLB')

    render_view(
        os.path.join(OUT_DIR, "preview_all_4floors_showcase.png"),
        cam_loc=(0.0, -17.0, 29.0),
        target=(0.0, -0.5, 0.5),
        ortho_scale=35.5,
        res=(2600, 1850)
    )
    print("ALL MANIFOLD 4-FLOOR 3D MODELS AND RENDERS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    main()

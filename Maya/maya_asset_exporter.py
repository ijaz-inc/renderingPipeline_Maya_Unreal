"""
Universal Maya Asset Cleanup & JSON Export Tool
Works with any imported FBX — captures ALL materials per mesh (multi-material support).

Usage:
    1. Import your FBX into Maya (File -> Import)
    2. Select the root transform node in the Outliner
    3. Run in Script Editor (Python tab):
        exec(open(r"C:/Users/ijz1cob/Desktop/Maya/maya_asset_exporter.py").read())
        run()
"""

import maya.cmds as cmds
import json
import os
import re


# ============================================================
# NAME CLEANUP
# ============================================================

FBXASC_PATTERN = re.compile(r'FBXASC\d{3}')
ILLEGAL_CHARS_PATTERN = re.compile(r'[^a-zA-Z0-9_]')
MULTI_UNDERSCORE_PATTERN = re.compile(r'_{2,}')


def clean_name(raw_name):
    name = raw_name
    if ':' in name:
        name = name.split(':')[-1]
    if '|' in name:
        name = name.split('|')[-1]
    name = FBXASC_PATTERN.sub('_', name)
    name = ILLEGAL_CHARS_PATTERN.sub('_', name)
    name = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    name = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
    name = name.lower()
    name = MULTI_UNDERSCORE_PATTERN.sub('_', name)
    name = name.strip('_')
    if not name:
        name = "unnamed"
    return name


def ensure_unique(name, used_names):
    if name not in used_names:
        used_names.add(name)
        return name
    counter = 1
    while f"{name}_{counter:02d}" in used_names:
        counter += 1
    unique = f"{name}_{counter:02d}"
    used_names.add(unique)
    return unique


# ============================================================
# MATERIAL EXTRACTION - CAPTURES ALL MATERIALS ON A MESH
# ============================================================

def get_all_materials_on_shape(shape_node):
    """
    Returns an ordered list of ALL materials assigned to a shape node,
    matching the material slot order. Uses listSets and listHistory
    to catch every shading group, including per-face assignments.
    """
    materials_ordered = []
    seen_sgs = set()

    # Method 1: listHistory to find all shading engines connected to this shape
    history_sgs = cmds.ls(cmds.listHistory(shape_node, future=True), type='shadingEngine') or []

    # Method 2: listSets for rendering sets
    set_sgs = cmds.listSets(type=1, object=shape_node) or []

    # Method 3: direct connections
    conn_sgs = cmds.listConnections(shape_node, type='shadingEngine') or []

    # Combine all found shading groups, preserving order
    all_sgs = []
    for sg in history_sgs + set_sgs + conn_sgs:
        if sg not in seen_sgs and sg != 'initialShadingGroup':
            seen_sgs.add(sg)
            all_sgs.append(sg)

    # If nothing found, check initialShadingGroup too
    if not all_sgs:
        for sg in history_sgs + set_sgs + conn_sgs:
            if sg not in seen_sgs:
                seen_sgs.add(sg)
                all_sgs.append(sg)

    for sg in all_sgs:
        mat_connections = cmds.listConnections(sg + '.surfaceShader', source=True, destination=False)
        if mat_connections:
            mat_name = mat_connections[0]
            materials_ordered.append(mat_name)

    return materials_ordered


def extract_material_data(mat_name):
    """Extracts PBR parameters from any Maya material type."""
    mat_data = {
        "base_color": [0.5, 0.5, 0.5],
        "metallic": 0.0,
        "roughness": 0.5,
        "specular": 0.5,
        "opacity": 1.0,
        "emissive_color": [0.0, 0.0, 0.0],
        "texture_maps": {}
    }

    if not cmds.objExists(mat_name):
        return mat_data

    node_type = cmds.nodeType(mat_name)

    try:
        if node_type == 'aiStandardSurface':
            bc = cmds.getAttr(f"{mat_name}.baseColor")[0]
            mat_data["base_color"] = [round(v, 4) for v in bc]
            mat_data["metallic"] = round(cmds.getAttr(f"{mat_name}.metalness"), 4)
            mat_data["roughness"] = round(cmds.getAttr(f"{mat_name}.specularRoughness"), 4)
            mat_data["specular"] = round(cmds.getAttr(f"{mat_name}.specular"), 4)
            mat_data["opacity"] = round(cmds.getAttr(f"{mat_name}.opacity")[0][0], 4)
            ec = cmds.getAttr(f"{mat_name}.emissionColor")[0]
            mat_data["emissive_color"] = [round(v, 4) for v in ec]
            _extract_textures_arnold(mat_name, mat_data)

        elif node_type == 'standardSurface':
            bc = cmds.getAttr(f"{mat_name}.baseColor")[0]
            mat_data["base_color"] = [round(v, 4) for v in bc]
            mat_data["metallic"] = round(cmds.getAttr(f"{mat_name}.metalness"), 4)
            mat_data["roughness"] = round(cmds.getAttr(f"{mat_name}.specularRoughness"), 4)
            mat_data["specular"] = round(cmds.getAttr(f"{mat_name}.specular"), 4)

        elif node_type == 'blinn':
            bc = cmds.getAttr(f"{mat_name}.color")[0]
            mat_data["base_color"] = [round(v, 4) for v in bc]
            mat_data["roughness"] = round(cmds.getAttr(f"{mat_name}.eccentricity"), 4)
            mat_data["specular"] = round(cmds.getAttr(f"{mat_name}.specularRollOff"), 4)
            _extract_textures_legacy(mat_name, mat_data)

        elif node_type in ('phong', 'phongE'):
            bc = cmds.getAttr(f"{mat_name}.color")[0]
            mat_data["base_color"] = [round(v, 4) for v in bc]
            cos_power = cmds.getAttr(f"{mat_name}.cosinePower")
            mat_data["roughness"] = round(1.0 - min(cos_power / 100.0, 1.0), 4)
            _extract_textures_legacy(mat_name, mat_data)

        elif node_type == 'lambert':
            bc = cmds.getAttr(f"{mat_name}.color")[0]
            mat_data["base_color"] = [round(v, 4) for v in bc]
            mat_data["roughness"] = 1.0
            mat_data["metallic"] = 0.0
            _extract_textures_legacy(mat_name, mat_data)

        else:
            if cmds.attributeQuery('color', node=mat_name, exists=True):
                bc = cmds.getAttr(f"{mat_name}.color")[0]
                mat_data["base_color"] = [round(v, 4) for v in bc]

    except Exception as e:
        cmds.warning(f"Error reading material '{mat_name}': {e}")

    return mat_data


def _extract_textures_arnold(mat_name, mat_data):
    attr_map = {
        'baseColor': 'base_color_map', 'normalCamera': 'normal_map',
        'metalness': 'metallic_map', 'specularRoughness': 'roughness_map',
        'opacity': 'opacity_map', 'emissionColor': 'emissive_map'
    }
    for attr, key in attr_map.items():
        _find_file_texture(mat_name, attr, key, mat_data)


def _extract_textures_legacy(mat_name, mat_data):
    attr_map = {
        'color': 'base_color_map', 'normalCamera': 'normal_map',
        'specularColor': 'specular_map'
    }
    for attr, key in attr_map.items():
        _find_file_texture(mat_name, attr, key, mat_data)


def _find_file_texture(mat_name, attr, map_key, mat_data):
    full_attr = f"{mat_name}.{attr}"
    if not cmds.attributeQuery(attr, node=mat_name, exists=True):
        return
    connections = cmds.listConnections(full_attr, source=True, destination=False) or []
    for conn in connections:
        conn_type = cmds.nodeType(conn)
        if conn_type == 'file':
            tex_path = cmds.getAttr(f"{conn}.fileTextureName")
            if tex_path:
                mat_data["texture_maps"][map_key] = os.path.basename(tex_path)
            return
        elif conn_type == 'aiImage':
            tex_path = cmds.getAttr(f"{conn}.filename")
            if tex_path:
                mat_data["texture_maps"][map_key] = os.path.basename(tex_path)
            return
        elif conn_type in ('bump2d', 'aiBump2d'):
            bump_input = cmds.listConnections(f"{conn}.bumpValue", source=True) or []
            for bi in bump_input:
                if cmds.nodeType(bi) == 'file':
                    tex_path = cmds.getAttr(f"{bi}.fileTextureName")
                    if tex_path:
                        mat_data["texture_maps"][map_key] = os.path.basename(tex_path)
                    return


# ============================================================
# HIERARCHY TRAVERSAL
# ============================================================

def build_hierarchy(root_node, used_names, rename_nodes=True):
    children = cmds.listRelatives(root_node, children=True, fullPath=False, type='transform') or []
    hierarchy = {}

    for child in children:
        original_name = child
        cleaned = clean_name(child)
        cleaned = ensure_unique(cleaned, used_names)

        if rename_nodes and cleaned != child:
            try:
                cmds.rename(child, cleaned)
            except Exception as e:
                cmds.warning(f"Could not rename '{child}' to '{cleaned}': {e}")
                cleaned = child
                used_names.add(cleaned)

        node_entry = {
            "original_name": original_name,
            "mesh": None,
            "material_slots": [],
            "transform": {},
            "children": {}
        }

        # Transform
        try:
            pos = cmds.xform(cleaned, query=True, worldSpace=True, translation=True)
            rot = cmds.xform(cleaned, query=True, worldSpace=True, rotation=True)
            scl = cmds.xform(cleaned, query=True, worldSpace=True, scale=True)
            node_entry["transform"] = {
                "translation": [round(v, 6) for v in pos],
                "rotation": [round(v, 6) for v in rot],
                "scale": [round(v, 6) for v in scl]
            }
        except:
            pass

        # Mesh shapes — get ALL materials
        shapes = cmds.listRelatives(cleaned, shapes=True, type='mesh', noIntermediate=True) or []
        if shapes:
            node_entry["mesh"] = cleaned
            all_mats = get_all_materials_on_shape(shapes[0])
            node_entry["material_slots"] = all_mats
            print(f"  Mesh '{cleaned}' has {len(all_mats)} material(s): {all_mats}")

        # Recurse
        node_entry["children"] = build_hierarchy(cleaned, used_names, rename_nodes)
        hierarchy[cleaned] = node_entry

    return hierarchy


# ============================================================
# MAIN EXPORT
# ============================================================

def collect_all_materials(hierarchy, material_set=None):
    if material_set is None:
        material_set = set()
    for node_name, node_data in hierarchy.items():
        for mat in node_data.get("material_slots", []):
            material_set.add(mat)
        collect_all_materials(node_data["children"], material_set)
    return material_set


def export_json(export_path=None, rename_nodes=True):
    selection = cmds.ls(selection=True, long=False)
    if not selection:
        cmds.warning("Nothing selected. Select a root transform node.")
        return None

    root = selection[0]
    if cmds.nodeType(root) != 'transform':
        cmds.warning(f"'{root}' is not a transform node.")
        return None

    if not export_path:
        result = cmds.fileDialog2(
            fileFilter="JSON Files (*.json)",
            dialogStyle=2, fileMode=0,
            caption="Export Asset Data as JSON"
        )
        if not result:
            return None
        export_path = result[0]

    print("=" * 60)
    print("MAYA ASSET EXPORTER")
    print("=" * 60)

    used_names = set()
    original_root = root
    cleaned_root = clean_name(root)
    cleaned_root = ensure_unique(cleaned_root, used_names)

    if rename_nodes and cleaned_root != root:
        try:
            cmds.rename(root, cleaned_root)
            print(f"  Root: '{original_root}' -> '{cleaned_root}'")
        except:
            cleaned_root = root
            used_names.add(cleaned_root)

    # Build hierarchy (captures ALL materials per mesh)
    hierarchy = build_hierarchy(cleaned_root, used_names, rename_nodes)

    # Also check root for materials
    root_shapes = cmds.listRelatives(cleaned_root, shapes=True, type='mesh', noIntermediate=True) or []
    root_material_slots = []
    if root_shapes:
        root_material_slots = get_all_materials_on_shape(root_shapes[0])

    # Collect every unique material name
    all_material_names = collect_all_materials(hierarchy)
    for mat in root_material_slots:
        all_material_names.add(mat)

    # Clean material names and build rename map
    mat_rename_map = {}
    cleaned_mat_names = set()
    for mat_name in sorted(all_material_names):
        cleaned_mat = clean_name(mat_name)
        cleaned_mat = ensure_unique(cleaned_mat, cleaned_mat_names)
        mat_rename_map[mat_name] = cleaned_mat

    # Extract material data with cleaned names
    materials_data = {}
    for original_mat, cleaned_mat in mat_rename_map.items():
        if original_mat == 'lambert1':
            materials_data[cleaned_mat] = {
                "base_color": [0.5, 0.5, 0.5], "metallic": 0.0,
                "roughness": 0.5, "specular": 0.5, "opacity": 1.0,
                "emissive_color": [0.0, 0.0, 0.0], "texture_maps": {},
                "is_default": True
            }
        else:
            mat_info = extract_material_data(original_mat)
            mat_info["is_default"] = False
            materials_data[cleaned_mat] = mat_info

    # Update hierarchy to use cleaned material names
    def update_mat_refs(h):
        for node_name, node_data in h.items():
            node_data["material_slots"] = [
                mat_rename_map.get(m, m) for m in node_data.get("material_slots", [])
            ]
            update_mat_refs(node_data["children"])

    update_mat_refs(hierarchy)

    root_material_slots = [mat_rename_map.get(m, m) for m in root_material_slots]

    # Build mesh -> [slot0_mat, slot1_mat, ...] map
    mesh_material_assignments = {}
    def build_assignments(h):
        for node_name, node_data in h.items():
            if node_data["mesh"] and node_data["material_slots"]:
                mesh_material_assignments[node_data["mesh"]] = node_data["material_slots"]
            build_assignments(node_data["children"])
    build_assignments(hierarchy)

    if root_shapes and root_material_slots:
        mesh_material_assignments[cleaned_root] = root_material_slots

    # All mesh names
    all_mesh_names = list(mesh_material_assignments.keys())

    # Assemble output
    output = {
        "version": "2.0",
        "source_file": cmds.file(query=True, sceneName=True) or "untitled",
        "scene_name": cleaned_root,
        "mesh_count": len(all_mesh_names),
        "material_count": len(materials_data),
        "meshes": all_mesh_names,
        "hierarchy": {
            cleaned_root: {
                "original_name": original_root,
                "mesh": cleaned_root if root_shapes else None,
                "material_slots": root_material_slots,
                "transform": {
                    "translation": [0.0, 0.0, 0.0],
                    "rotation": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0]
                },
                "children": hierarchy
            }
        },
        "materials": materials_data,
        "mesh_material_assignments": mesh_material_assignments
    }

    with open(export_path, 'w') as f:
        json.dump(output, f, indent=2)

    print("-" * 60)
    print(f"  Output : {export_path}")
    print(f"  Meshes : {all_mesh_names}")
    print(f"  Materials: {list(materials_data.keys())}")
    for mesh, slots in mesh_material_assignments.items():
        print(f"  {mesh} -> slots: {slots}")
    print("=" * 60)

    return output


def run(path=None):
    """Select root node, then call run()"""
    return export_json(export_path=path)


if __name__ == '__main__':
    run()

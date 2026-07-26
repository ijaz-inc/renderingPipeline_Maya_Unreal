"""
Unreal Engine - JSON Scene Importer & Material Builder
Parses JSON from Maya, spawns meshes, rebuilds hierarchy, assigns materials per slot.

Prerequisites:
    - Enable "Python Editor Script Plugin" in Edit -> Plugins
    - Enable "Editor Scripting Utilities" in Edit -> Plugins
    - FBX already imported into Unreal Content Browser

Usage:
    Edit -> Execute Python Script -> select this file
    Or in Output Log (Python):
        exec(open(r"C:/Users/ijz1cob/Desktop/Maya/unreal_scene_builder.py").read())
"""

import unreal
import json
import os


# ============================================================
# CONFIGURATION - UPDATE THESE FOR YOUR PROJECT
# ============================================================

# Path to the JSON exported from Maya
JSON_PATH = os.path.join(unreal.Paths.project_content_dir(), "JsonData", "basket_ball_json_data.json")

# Content Browser path where you imported your FBX
# The script searches this folder recursively for StaticMesh assets
MESH_SEARCH_PATH = "/Game/Meshes/"

# Where new materials will be created (if not already imported with FBX)
MATERIAL_OUTPUT_PATH = "/Game/Materials/Generated/"

# Where textures live (if any)
TEXTURE_SEARCH_PATH = "/Game/Textures/"

# ============================================================
# SPAWN TRANSFORM SETTINGS
# ============================================================

# Set to True to IGNORE transform data from JSON (spawn at your chosen location/scale)
# Set to False to use the original Maya transforms from the JSON
OVERRIDE_TRANSFORM = True

# Target spawn location (only used if OVERRIDE_TRANSFORM = True)
SPAWN_LOCATION = unreal.Vector(0.0, 0.0, 0.0)

# Target spawn rotation (only used if OVERRIDE_TRANSFORM = True)
SPAWN_ROTATION = unreal.Rotator(0.0, 0.0, 0.0)

# Target scale (only used if OVERRIDE_TRANSFORM = True)
# Set to (1,1,1) for default Unreal scale
SPAWN_SCALE = unreal.Vector(1.0, 1.0, 1.0)


# ============================================================
# ASSET DISCOVERY - ROBUST VERSION
# ============================================================

def discover_static_meshes(search_path):
    """
    Scans Content Browser for StaticMesh assets.
    Uses load_asset to check type — works across all UE versions.
    Returns {lowercase_name: full_asset_path}
    """
    mesh_map = {}

    all_assets = unreal.EditorAssetLibrary.list_assets(
        search_path, recursive=True, include_folder=False
    )

    unreal.log(f"  Scanning {search_path} ... found {len(all_assets)} asset(s) total")

    for asset_path in all_assets:
        # Try loading to check type
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if asset is None:
            continue

        if isinstance(asset, unreal.StaticMesh):
            # Get just the asset name from the full path
            asset_name = asset_path.rsplit('/', 1)[-1].split('.')[0]
            mesh_map[asset_name.lower()] = asset_path
            unreal.log(f"    [StaticMesh] '{asset_name}' at {asset_path}")

    if not mesh_map:
        unreal.log_warning(f"  No StaticMesh assets found in {search_path}")
        # Try searching /Game/ as fallback
        unreal.log(f"  Trying fallback search in /Game/ ...")
        all_game_assets = unreal.EditorAssetLibrary.list_assets(
            "/Game/", recursive=True, include_folder=False
        )
        for asset_path in all_game_assets:
            asset = unreal.EditorAssetLibrary.load_asset(asset_path)
            if asset and isinstance(asset, unreal.StaticMesh):
                asset_name = asset_path.rsplit('/', 1)[-1].split('.')[0]
                mesh_map[asset_name.lower()] = asset_path
                unreal.log(f"    [StaticMesh] '{asset_name}' at {asset_path}")

    unreal.log(f"  Total StaticMesh assets discovered: {len(mesh_map)}")
    return mesh_map


def discover_existing_materials(search_paths):
    """
    Scans multiple Content Browser paths for Material/MaterialInstance assets.
    Returns {lowercase_name: full_asset_path}
    """
    mat_map = {}

    for search_path in search_paths:
        try:
            all_assets = unreal.EditorAssetLibrary.list_assets(
                search_path, recursive=True, include_folder=False
            )
        except:
            continue

        for asset_path in all_assets:
            asset = unreal.EditorAssetLibrary.load_asset(asset_path)
            if asset is None:
                continue
            if isinstance(asset, (unreal.MaterialInterface, unreal.Material, unreal.MaterialInstance, unreal.MaterialInstanceConstant)):
                asset_name = asset_path.rsplit('/', 1)[-1].split('.')[0]
                mat_map[asset_name.lower()] = asset_path
                unreal.log(f"    [Material] '{asset_name}' at {asset_path}")

    unreal.log(f"  Total materials discovered: {len(mat_map)}")
    return mat_map


def find_mesh_asset(mesh_name, mesh_registry):
    """
    Finds a static mesh by trying multiple name matching strategies.
    """
    name_lower = mesh_name.lower()

    # 1. Exact match
    if name_lower in mesh_registry:
        return unreal.EditorAssetLibrary.load_asset(mesh_registry[name_lower])

    # 2. Partial match — mesh name contained in registry name or vice versa
    for reg_name, reg_path in mesh_registry.items():
        if name_lower in reg_name or reg_name in name_lower:
            unreal.log(f"    Fuzzy matched: '{mesh_name}' -> '{reg_name}'")
            return unreal.EditorAssetLibrary.load_asset(reg_path)

    # 3. Strip prefixes (SM_, Mesh_)
    for prefix in ['sm_', 'mesh_', 'staticmesh_']:
        stripped = name_lower.replace(prefix, '')
        for reg_name, reg_path in mesh_registry.items():
            reg_stripped = reg_name.replace(prefix, '')
            if stripped == reg_stripped or stripped in reg_stripped or reg_stripped in stripped:
                unreal.log(f"    Prefix-stripped match: '{mesh_name}' -> '{reg_name}'")
                return unreal.EditorAssetLibrary.load_asset(reg_path)

    # 4. Single mesh fallback — if there's only one mesh, it must be the one
    if len(mesh_registry) == 1:
        only_name = list(mesh_registry.keys())[0]
        only_path = list(mesh_registry.values())[0]
        unreal.log(f"    Single-mesh fallback: '{mesh_name}' -> '{only_name}'")
        return unreal.EditorAssetLibrary.load_asset(only_path)

    unreal.log_warning(f"    Mesh not found: '{mesh_name}'")
    return None


def find_material_asset(mat_name, existing_materials):
    """
    Finds existing material by name with fuzzy matching.
    """
    name_lower = mat_name.lower()

    # Exact
    if name_lower in existing_materials:
        return unreal.EditorAssetLibrary.load_asset(existing_materials[name_lower])

    # Remove underscores/dots for comparison
    clean_target = name_lower.replace('_', '').replace('.', '')
    for reg_name, reg_path in existing_materials.items():
        clean_reg = reg_name.replace('_', '').replace('.', '')
        if clean_target == clean_reg:
            unreal.log(f"    Material fuzzy match: '{mat_name}' -> '{reg_name}'")
            return unreal.EditorAssetLibrary.load_asset(reg_path)

    # Partial
    for reg_name, reg_path in existing_materials.items():
        if name_lower in reg_name or reg_name in name_lower:
            unreal.log(f"    Material partial match: '{mat_name}' -> '{reg_name}'")
            return unreal.EditorAssetLibrary.load_asset(reg_path)

    return None


# ============================================================
# MATERIAL CREATION
# ============================================================

def get_or_create_material(mat_name, mat_data, existing_materials):
    """
    Resolves a material: reuse existing from FBX import, or create new.
    """
    if mat_data.get("is_default", False):
        return None

    # Check existing imported materials
    existing = find_material_asset(mat_name, existing_materials)
    if existing:
        unreal.log(f"  Reusing imported material: {mat_name}")
        return existing

    # Check if already generated
    gen_path = MATERIAL_OUTPUT_PATH + mat_name
    if unreal.EditorAssetLibrary.does_asset_exist(gen_path):
        unreal.log(f"  Reusing generated material: {mat_name}")
        return unreal.EditorAssetLibrary.load_asset(gen_path)

    # Create new material
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialFactoryNew()
    material = asset_tools.create_asset(
        asset_name=mat_name,
        package_path=MATERIAL_OUTPUT_PATH,
        asset_class=unreal.Material,
        factory=factory
    )

    if not material:
        unreal.log_error(f"  Failed to create: {mat_name}")
        return None

    mel = unreal.MaterialEditingLibrary
    base_color = mat_data.get("base_color", [0.5, 0.5, 0.5])
    metallic = mat_data.get("metallic", 0.0)
    roughness = mat_data.get("roughness", 0.5)
    specular = mat_data.get("specular", 0.5)
    texture_maps = mat_data.get("texture_maps", {})

    x, y = -400, 0

    # Base Color
    _make_color_node(mel, material, base_color, x, y, unreal.MaterialProperty.MP_BASE_COLOR)
    y += 200

    # Metallic
    _make_scalar_node(mel, material, metallic, x, y, unreal.MaterialProperty.MP_METALLIC)
    y += 200

    # Roughness
    _make_scalar_node(mel, material, roughness, x, y, unreal.MaterialProperty.MP_ROUGHNESS)
    y += 200

    # Specular
    _make_scalar_node(mel, material, specular, x, y, unreal.MaterialProperty.MP_SPECULAR)
    y += 200

    # Opacity
    opacity = mat_data.get("opacity", 1.0)
    if opacity < 1.0:
        material.blend_mode = unreal.BlendMode.BLEND_TRANSLUCENT
        _make_scalar_node(mel, material, opacity, x, y, unreal.MaterialProperty.MP_OPACITY)
        y += 200

    # Emissive
    emissive = mat_data.get("emissive_color", [0.0, 0.0, 0.0])
    if any(v > 0 for v in emissive):
        _make_color_node(mel, material, emissive, x, y, unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    mel.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(gen_path)
    unreal.log(f"  Created material: {mat_name}")
    return material


def _make_color_node(mel, material, color, x, y, prop):
    node = mel.create_material_expression(material, unreal.MaterialExpressionConstant3Vector, x, y)
    node.constant = unreal.LinearColor(r=color[0], g=color[1], b=color[2], a=1.0)
    mel.connect_material_property(node, "", prop)


def _make_scalar_node(mel, material, value, x, y, prop):
    node = mel.create_material_expression(material, unreal.MaterialExpressionConstant, x, y)
    node.r = value
    mel.connect_material_property(node, "", prop)


# ============================================================
# TRANSFORM RESOLUTION
# ============================================================

def _resolve_transform(transform, is_root=False):
    """
    If OVERRIDE_TRANSFORM is True: root gets user-defined location/scale,
    children get identity (hierarchy positioning via folders).
    If False: converts Maya Y-up to Unreal Z-up.
    """
    if OVERRIDE_TRANSFORM:
        if is_root:
            return SPAWN_LOCATION, SPAWN_ROTATION, SPAWN_SCALE
        else:
            return unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0), unreal.Vector(1, 1, 1)
    else:
        location = unreal.Vector(0, 0, 0)
        rotation = unreal.Rotator(0, 0, 0)
        scale = unreal.Vector(1, 1, 1)
        if transform:
            t = transform.get("translation", [0, 0, 0])
            r = transform.get("rotation", [0, 0, 0])
            s = transform.get("scale", [1, 1, 1])
            location = unreal.Vector(t[0], -t[2], t[1])
            rotation = unreal.Rotator(r[0], r[2], r[1])
            scale = unreal.Vector(s[0], s[2], s[1])
        return location, rotation, scale


# ============================================================
# HIERARCHY SPAWNING — FOLDERS FOR GROUPS, ACTORS FOR MESHES
# ============================================================

def spawn_hierarchy(hierarchy_dict, mesh_registry, material_cache, folder_path="", depth=0):
    """
    Recursively spawns actors matching Maya hierarchy.
    - Group nodes (no mesh) -> World Outliner FOLDER (not an actor)
    - Mesh nodes -> StaticMeshActor placed inside the folder

    Result in World Outliner:
        📁 group
          └── basket_ball (StaticMeshActor)

    This matches Maya's Outliner structure exactly.
    """
    spawned = {}
    indent = "  " * (depth + 1)

    for node_name, node_data in hierarchy_dict.items():
        mesh_name = node_data.get("mesh")
        material_slots = node_data.get("material_slots", [])
        if not material_slots and node_data.get("material"):
            material_slots = [node_data["material"]]
        children = node_data.get("children", {})
        transform = node_data.get("transform", {})

        if mesh_name:
            # --- MESH NODE: spawn a real StaticMeshActor ---
            mesh_asset = find_mesh_asset(mesh_name, mesh_registry)

            if mesh_asset:
                location, rotation, scale = _resolve_transform(transform, depth == 0)

                actor = unreal.EditorLevelLibrary.spawn_actor_from_object(
                    mesh_asset, location, rotation
                )

                if actor:
                    actor.set_actor_label(node_name)
                    actor.set_actor_scale3d(scale)

                    # Place inside folder to match Maya hierarchy
                    if folder_path:
                        actor.set_folder_path(folder_path)

                    # === MULTI-MATERIAL SLOT ASSIGNMENT ===
                    mesh_comp = actor.static_mesh_component
                    if mesh_comp and material_slots:
                        num_slots = mesh_comp.get_num_materials()
                        unreal.log(f"{indent}[MESH] {node_name} | "
                                   f"{num_slots} slot(s), "
                                   f"{len(material_slots)} material(s) from JSON")

                        for slot_idx, mat_name in enumerate(material_slots):
                            if slot_idx >= num_slots:
                                unreal.log_warning(
                                    f"{indent}  Slot {slot_idx} exceeds mesh slots, skipping")
                                break
                            mat_asset = material_cache.get(mat_name)
                            if mat_asset:
                                mesh_comp.set_material(slot_idx, mat_asset)
                                unreal.log(f"{indent}  Slot {slot_idx} -> {mat_name}")
                            else:
                                unreal.log_warning(
                                    f"{indent}  Slot {slot_idx}: '{mat_name}' not resolved")
                    else:
                        unreal.log(f"{indent}[MESH] {node_name} (no materials)")

                    spawned[node_name] = actor
                else:
                    unreal.log_warning(f"{indent}[FAIL] Could not spawn: {node_name}")
            else:
                unreal.log_warning(f"{indent}[SKIP] Mesh not found: {node_name}")

            # If this mesh node also has children, recurse with a sub-folder
            if children:
                child_folder = f"{folder_path}/{node_name}" if folder_path else node_name
                child_spawned = spawn_hierarchy(
                    children, mesh_registry, material_cache,
                    folder_path=child_folder, depth=depth + 1
                )
                spawned.update(child_spawned)

        else:
            # --- GROUP NODE: create a folder, not an actor ---
            child_folder = f"{folder_path}/{node_name}" if folder_path else node_name
            unreal.log(f"{indent}[FOLDER] {child_folder}")

            # Recurse into children with the folder path
            if children:
                child_spawned = spawn_hierarchy(
                    children, mesh_registry, material_cache,
                    folder_path=child_folder, depth=depth + 1
                )
                spawned.update(child_spawned)

    return spawned


# ============================================================
# MAIN PIPELINE
# ============================================================

def run(json_path=None):
    if json_path is None:
        json_path = JSON_PATH

    unreal.log("=" * 60)
    unreal.log("UNREAL SCENE BUILDER v2")
    unreal.log("=" * 60)

    # Load JSON
    if not os.path.exists(json_path):
        unreal.log_error(f"JSON not found: {json_path}")
        return
    with open(json_path, 'r') as f:
        data = json.load(f)

    scene_name = data.get("scene_name", "unknown")
    unreal.log(f"  Scene: {scene_name}")
    unreal.log(f"  JSON version: {data.get('version', '1.0')}")
    unreal.log(f"  Meshes in JSON: {data.get('mesh_count', '?')}")
    unreal.log(f"  Materials in JSON: {data.get('material_count', '?')}")

    # Phase 1: Discover assets already in Content Browser
    unreal.log("--- Phase 1: Asset Discovery ---")
    mesh_registry = discover_static_meshes(MESH_SEARCH_PATH)

    if not mesh_registry:
        unreal.log_error("No StaticMesh assets found anywhere in /Game/!")
        unreal.log_error("Import your FBX into Unreal first, then re-run this script.")
        return

    # Search for materials in both the mesh folder and /Game/ root
    existing_materials = discover_existing_materials([MESH_SEARCH_PATH, "/Game/"])

    # Phase 2: Resolve materials
    unreal.log("--- Phase 2: Materials ---")
    materials_data = data.get("materials", {})
    material_cache = {}

    # Also build cache from mesh_material_assignments for v1 JSON compat
    assignments = data.get("mesh_material_assignments", {})

    with unreal.ScopedSlowTask(len(materials_data), "Processing Materials...") as task:
        task.make_dialog(True)
        for mat_name, mat_params in materials_data.items():
            if task.should_cancel():
                return
            task.enter_progress_frame(1, f"Material: {mat_name}")
            material_cache[mat_name] = get_or_create_material(
                mat_name, mat_params, existing_materials
            )

    # Phase 3: Spawn hierarchy
    unreal.log("--- Phase 3: Spawning Hierarchy ---")
    hierarchy = data.get("hierarchy", {})

    with unreal.ScopedSlowTask(1, "Building Scene...") as task:
        task.make_dialog(True)
        task.enter_progress_frame(1)
        spawned = spawn_hierarchy(hierarchy, mesh_registry, material_cache)

    # Summary
    unreal.log("=" * 60)
    unreal.log("PIPELINE COMPLETE")
    unreal.log(f"  Actors spawned: {len(spawned)}")
    resolved = sum(1 for v in material_cache.values() if v is not None)
    unreal.log(f"  Materials resolved: {resolved}/{len(material_cache)}")
    for mat_name, mat_asset in material_cache.items():
        status = "OK" if mat_asset else "MISSING"
        unreal.log(f"    [{status}] {mat_name}")
    unreal.log("=" * 60)


if __name__ == '__main__':
    run()

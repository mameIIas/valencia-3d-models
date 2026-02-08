import bpy
import sys
import os

# ------------------ Scene helpers ------------------
def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

def import_model(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in [".glb", ".gltf"]:
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".stl":
        bpy.ops.import_mesh.stl(filepath=path)
    elif ext == ".ply":
        bpy.ops.import_mesh.ply(filepath=path)
    else:
        raise ValueError(f"Formato no soportado: {ext}")

def join_all_meshes():
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("No se encontraron objetos MESH para simplificar.")

    if len(meshes) == 1:
        return meshes[0]

    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active

def triangulated_face_count(obj) -> int:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    mesh.calc_loop_triangles()
    n = len(mesh.loop_triangles)
    eval_obj.to_mesh_clear()
    return n

def bake_evaluated_to_real_mesh(obj):
    """
    Convierte el resultado FINAL evaluado (incluyendo Geometry Nodes/instancias)
    en un mesh real, y elimina modificadores para que no se regenere geometría.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)

    # En Blender 5.x: método robusto para crear un mesh "bakeado"
    baked_mesh = bpy.data.meshes.new_from_object(
        eval_obj,
        depsgraph=depsgraph,
        preserve_all_data_layers=True
    )

    # Asigna el mesh bakeado al objeto
    obj.data = baked_mesh

    # Quita TODOS los modificadores (Geometry Nodes incluido)
    obj.modifiers.clear()

    bpy.context.view_layer.update()

def add_triangulate_modifier(obj):
    tri = obj.modifiers.new(name="Triangulate", type="TRIANGULATE")
    tri.keep_custom_normals = True

def add_decimate_modifier(obj, ratio: float):
    dec = obj.modifiers.new(name="Decimate", type="DECIMATE")
    dec.decimate_type = "COLLAPSE"
    dec.use_collapse_triangulate = True
    dec.ratio = max(min(ratio, 1.0), 0.0001)
    return dec

def apply_modifier(obj, mod_name: str):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod_name)

def decimate_to_target_tris(obj, target_tris: int, max_iters: int = 20):
    """
    Ajusta ratio del Decimate hasta conseguir <= target_tris.
    Aplica Decimate y Triangulate al final (mesh real).
    """
    add_triangulate_modifier(obj)
    bpy.context.view_layer.update()

    before = triangulated_face_count(obj)
    if before <= target_tris:
        apply_modifier(obj, "Triangulate")
        return before, before

    # ratio inicial aproximado
    ratio0 = target_tris / before
    add_decimate_modifier(obj, ratio0)
    bpy.context.view_layer.update()

    # búsqueda binaria del ratio
    low, high = 0.0001, 1.0
    current = triangulated_face_count(obj)

    # Ajusta rango inicial según resultado
    if current > target_tris:
        high = obj.modifiers["Decimate"].ratio
    else:
        low = obj.modifiers["Decimate"].ratio

    for _ in range(max_iters):
        mid = (low + high) / 2.0
        obj.modifiers["Decimate"].ratio = mid
        bpy.context.view_layer.update()
        current = triangulated_face_count(obj)

        if current > target_tris:
            high = mid
        else:
            low = mid

        if current <= target_tris:
            break

    # Empujón final por si se queda un pelín por encima
    if current > target_tris:
        r = obj.modifiers["Decimate"].ratio
        obj.modifiers["Decimate"].ratio = max(r * (target_tris / current) * 0.95, 0.0001)
        bpy.context.view_layer.update()
        current = triangulated_face_count(obj)

    # Aplicar modificadores para “hornear” el resultado
    apply_modifier(obj, "Decimate")
    apply_modifier(obj, "Triangulate")

    final = triangulated_face_count(obj)
    return before, final

def delete_other_meshes(keep_obj):
    for other in [o for o in bpy.context.scene.objects if o.type == "MESH" and o.name != keep_obj.name]:
        bpy.data.objects.remove(other, do_unlink=True)

def export_model(path: str, obj_to_export):
    ext = os.path.splitext(path)[1].lower()

    bpy.ops.object.select_all(action="DESELECT")
    obj_to_export.select_set(True)
    bpy.context.view_layer.objects.active = obj_to_export

    if ext in [".glb", ".gltf"]:
        bpy.ops.export_scene.gltf(filepath=path, use_selection=True)
    elif ext == ".fbx":
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True)
    elif ext == ".obj":
        bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True)
    elif ext == ".stl":
        bpy.ops.export_mesh.stl(filepath=path, use_selection=True)
    elif ext == ".ply":
        bpy.ops.export_mesh.ply(filepath=path, use_selection=True)
    else:
        raise ValueError(f"Formato de salida no soportado: {ext}")

# ------------------ CLI parsing ------------------
def parse_args():
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("Uso: blender -b -P simplify_to_tris.py -- in.glb out.glb 50000")
    idx = argv.index("--")
    args = argv[idx + 1:]
    if len(args) < 3:
        raise SystemExit("Uso: blender -b -P simplify_to_tris.py -- in.glb out.glb 50000")
    return args[0], args[1], int(args[2])

def main():
    in_path, out_path, target = parse_args()

    clear_scene()
    import_model(in_path)

    obj = join_all_meshes()

    # Conteo antes (tal cual importado)
    tris_before = triangulated_face_count(obj)

    # Bake del resultado evaluado (Geometry Nodes/instancias) a mesh real
    bake_evaluated_to_real_mesh(obj)
    tris_baked = triangulated_face_count(obj)

    # Decimate hasta <= target
    before_dec, final = decimate_to_target_tris(obj, target_tris=target)

    # Limpieza y export (solo el objeto final)
    delete_other_meshes(obj)

    print(f"[INFO] Tris import: {tris_before} | Tris baked: {tris_baked}")
    print(f"[OK]   Tris decimate: {before_dec} -> {final} | objetivo <= {target}")

    export_model(out_path, obj)

if __name__ == "__main__":
    main()

import bpy
import sys
import os

# -------- utils --------
def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
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

def export_model(path: str):
    ext = os.path.splitext(path)[1].lower()

    # Selecciona todo lo exportable
    bpy.ops.object.select_all(action='DESELECT')
    for obj in bpy.context.scene.objects:
        if obj.type in {"MESH", "EMPTY", "ARMATURE"}:
            obj.select_set(True)

    # Pon un activo por si el operador lo requiere
    sel = [o for o in bpy.context.selected_objects]
    if sel:
        bpy.context.view_layer.objects.active = sel[0]

    if ext == ".obj":
        bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True)

    elif ext == ".fbx":
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True)

    elif ext in [".glb", ".gltf"]:
        # Blender 5.x: export_selected ya no existe; usa use_selection
        bpy.ops.export_scene.gltf(filepath=path, use_selection=True)

    elif ext == ".stl":
        bpy.ops.export_mesh.stl(filepath=path, use_selection=True)

    elif ext == ".ply":
        bpy.ops.export_mesh.ply(filepath=path, use_selection=True)

    else:
        raise ValueError(f"Formato de salida no soportado: {ext}")


def triangulated_face_count(obj) -> int:
    # Cuenta triángulos reales: usamos mesh calc_loop_triangles
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    mesh.calc_loop_triangles()
    n = len(mesh.loop_triangles)
    eval_obj.to_mesh_clear()
    return n

def join_all_meshes():
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("No se encontraron objetos MESH para simplificar.")

    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active

def ensure_triangulated(obj):
    # Triangula (así el conteo de triángulos es coherente y lo que exportas cumple)
    tri = obj.modifiers.new(name="Triangulate", type="TRIANGULATE")
    tri.keep_custom_normals = True

def decimate_to_target_tris(obj, target_tris: int, max_iters: int = 12):
    # Decimate usa ratio (0..1) sobre caras. Vamos ajustando por aproximación.
    dec = obj.modifiers.new(name="Decimate", type="DECIMATE")
    dec.decimate_type = 'COLLAPSE'
    dec.use_collapse_triangulate = True

    # Estimación inicial
    current = triangulated_face_count(obj)
    if current <= target_tris:
        return current

    ratio = max(min(target_tris / current, 1.0), 0.0001)
    dec.ratio = ratio
    bpy.context.view_layer.update()
    current = triangulated_face_count(obj)

    # Refinamiento (búsqueda binaria suave)
    low, high = 0.0001, 1.0
    for _ in range(max_iters):
        if current > target_tris:
            high = dec.ratio
        else:
            low = dec.ratio

        mid = (low + high) / 2.0
        dec.ratio = mid
        bpy.context.view_layer.update()
        current = triangulated_face_count(obj)

        # Si ya estamos cerca (±2%), paramos
        if abs(current - target_tris) / target_tris < 0.02:
            break

    return current

# -------- main --------
def parse_args():
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("Uso: blender -b -P simplify_to_tris.py -- in.obj out.glb 50000")
    idx = argv.index("--")
    args = argv[idx + 1:]
    if len(args) < 3:
        raise SystemExit("Uso: blender -b -P simplify_to_tris.py -- in.obj out.glb 50000")
    in_path = args[0]
    out_path = args[1]
    target = int(args[2])
    return in_path, out_path, target

def main():
    in_path, out_path, target = parse_args()
    clear_scene()
    import_model(in_path)

    obj = join_all_meshes()
    ensure_triangulated(obj)

    before = triangulated_face_count(obj)
    after = decimate_to_target_tris(obj, target_tris=target)

    # Aplica modificadores para “hornear” el resultado
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target='MESH')

    # Vuelve a contar tras aplicar
    final = triangulated_face_count(obj)

    print(f"[OK] Triángulos: {before} -> {final} (objetivo {target})")
    export_model(out_path)

if __name__ == "__main__":
    main()

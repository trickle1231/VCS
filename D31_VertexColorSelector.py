bl_info = {
    "name": "Vertex Color Selector",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "View3D > Sidebar > Vertex Color",
    "description": "Select faces by vertex color",
    "category": "Mesh",
}

import bpy
import bmesh

# Blender 버전 호환성 처리
try:
    from bpy_extras import view3d_utils
except ImportError:
    import bpy_extras
    view3d_utils = bpy_extras.view3d_utils

VC_SELECTOR_THRESHOLD = 0.01

def linear_to_srgb_channel(c):
    if c <= 0.0031308:
        return 12.92 * c
    else:
        return 1.055 * (c ** (1.0 / 2.4)) - 0.055

def linear_to_srgb(rgb):
    return tuple(linear_to_srgb_channel(c) for c in rgb)

def color_close(c1, c2, threshold=0.01):
    dist = sum((float(a) - float(b)) ** 2 for a, b in zip(c1[:3], c2[:3])) ** 0.5
    return dist < threshold

def get_color_attribute_names(obj):
    if not obj or obj.type != 'MESH':
        return []
    return [attr.name for attr in obj.data.color_attributes if attr.domain == 'CORNER']

def clear_color_lists(scene):
    # EnumProperty를 빈 items로 재정의
    bpy.types.Scene.vc_selector_face_colors = bpy.props.EnumProperty(
        name="Face Colors",
        items=[]
    )
    scene.vc_selector.color_previews.clear()

# --- Find Colors 오퍼레이터 ---
class VERTEXCOLOR_OT_find_face_colors(bpy.types.Operator):
    bl_idname = "mesh.find_face_colors"
    bl_label = "Find Face Colors"
    bl_description = "Find and list all vertex colors used in the mesh"

    def execute(self, context):
        scene = context.scene
        obj = context.active_object

        # Edit 모드가 아니면 에러 메시지
        if context.mode != 'EDIT_MESH':
            self.report({'ERROR'}, "Find Colors is only available in Edit Mode!")
            return {'CANCELLED'}

        current_mesh_id = obj.data.name if obj and obj.data else ""
        last_mesh_id = getattr(scene, "vc_selector_last_mesh_id", "")
        if current_mesh_id != last_mesh_id:
            clear_color_lists(scene)
            scene.vc_selector.last_mesh_id = current_mesh_id

        bm = bmesh.from_edit_mesh(obj.data)
        color_layer = bm.loops.layers.color.get(scene.vc_selector.color_attribute)
        if not color_layer:
            self.report({'ERROR'}, "No vertex color layer found")
            return {'CANCELLED'}

        seen_colors = set()
        items = []
        color_list = []
        idx = 1
        for face in bm.faces:
            colors = [tuple(loop[color_layer][:3]) for loop in face.loops]
            avg_linear = tuple(round(sum(c[i] for c in colors)/len(colors), 4) for i in range(3))
            if avg_linear in seen_colors:
                continue
            seen_colors.add(avg_linear)
            label = f"Col_{idx}"
            name = label
            items.append((str(avg_linear), label, ""))
            color_list.append((name, avg_linear))
            idx += 1

        bpy.types.Scene.vc_selector_face_colors = bpy.props.EnumProperty(
            name="Face Colors",
            items=items
        )
        self.report({'INFO'}, f"{len(items)} face colors found")

        # 컬러 미리보기 업데이트
        scene.vc_selector.color_previews.clear()
        for name, avg_linear in color_list:
            item = scene.vc_selector.color_previews.add()
            item.name = name
            item.color = avg_linear

        return {'FINISHED'}

class VERTEXCOLOR_OT_select_faces_by_face_color(bpy.types.Operator):
    bl_idname = "mesh.select_faces_by_face_color"
    bl_label = "Select Faces By Face Color"

    def execute(self, context):
        scene = context.scene
        obj = context.active_object
        mode = obj.mode

        target_color = eval(scene.vc_selector.face_colors)
        threshold = 0.01  # VC_SELECTOR_THRESHOLD로 대체

        if mode == 'EDIT':
            bm = bmesh.from_edit_mesh(obj.data)
            color_layer = bm.loops.layers.color.get(scene.vc_selector.color_attribute)
            if not color_layer:
                self.report({'ERROR'}, "No vertex color layer found")
                return {'CANCELLED'}
            for face in bm.faces:
                colors = [tuple(loop[color_layer][:3]) for loop in face.loops]
                avg_linear = tuple(round(sum(c[i] for c in colors)/len(colors), 4) for i in range(3))
                face.select_set(color_close(avg_linear, target_color, threshold))
            bmesh.update_edit_mesh(obj.data)
        elif mode in {'VERTEX_PAINT', 'WEIGHT_PAINT', 'TEXTURE_PAINT'}:
            color_layer = obj.data.vertex_colors.get(scene.vc_selector.color_attribute)
            if not color_layer:
                self.report({'ERROR'}, "No vertex color layer found")
                return {'CANCELLED'}
            for poly in obj.data.polygons:
                colors = [color_layer.data[li].color[:3] for li in poly.loop_indices]
                avg_linear = tuple(round(sum(c[i] for c in colors)/len(colors), 4) for i in range(3))
                poly.select = color_close(avg_linear, target_color, threshold)
        else:
            self.report({'ERROR'}, "Unsupported mode (Only Edit/Vertex/Weight/Texture Paint supported)")
            return {'CANCELLED'}

        return {'FINISHED'}

# 1. 컬러 미리보기 아래에 "Select This Color" 버튼 추가
class VCSelectorColorPreview(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    color: bpy.props.FloatVectorProperty(subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0)

# 2. 컬러별 선택 오퍼레이터 추가
class VERTEXCOLOR_OT_select_this_color(bpy.types.Operator):
    bl_idname = "mesh.select_this_color"
    bl_label = "Select This Color"
    color: bpy.props.FloatVectorProperty(size=3)

    def invoke(self, context, event):
        self.shift = event.shift
        self.ctrl = event.ctrl
        return self.execute(context)

    def execute(self, context):
        scene = context.scene
        obj = context.active_object
        mode = obj.mode
        threshold = 0.01  # VC_SELECTOR_THRESHOLD로 대체
        target_color = tuple(self.color)
        shift = getattr(self, "shift", False)
        ctrl = getattr(self, "ctrl", False)

        if mode == 'EDIT':
            bm = bmesh.from_edit_mesh(obj.data)
            color_layer = bm.loops.layers.color.get(scene.vc_selector.color_attribute)
            if not color_layer:
                self.report({'ERROR'}, "No vertex color layer found")
                return {'CANCELLED'}
            for face in bm.faces:
                colors = [tuple(loop[color_layer][:3]) for loop in face.loops]
                avg_linear = tuple(round(sum(c[i] for c in colors)/len(colors), 4) for i in range(3))
                if color_close(avg_linear, target_color, threshold):
                    if ctrl:
                        face.select_set(False)
                    else:
                        face.select_set(True)
                elif not shift and not ctrl:
                    face.select_set(False)
            bmesh.update_edit_mesh(obj.data)
        elif mode in {'VERTEX_PAINT', 'WEIGHT_PAINT', 'TEXTURE_PAINT'}:
            color_layer = obj.data.vertex_colors.get(scene.vc_selector.color_attribute)
            if not color_layer:
                self.report({'ERROR'}, "No vertex color layer found")
                return {'CANCELLED'}
            for poly in obj.data.polygons:
                colors = [color_layer.data[li].color[:3] for li in poly.loop_indices]
                avg_linear = tuple(round(sum(c[i] for c in colors)/len(colors), 4) for i in range(3))
                if color_close(avg_linear, target_color, threshold):
                    if ctrl:
                        poly.select = False
                    else:
                        poly.select = True
                elif not shift and not ctrl:
                    poly.select = False
        else:
            self.report({'ERROR'}, "Unsupported mode (Only Edit/Vertex Paint supported)")
            return {'CANCELLED'}

        return {'FINISHED'}

# --- 컬러 리스트 수동 초기화 오퍼레이터 추가 ---
class VERTEXCOLOR_OT_clear_color_lists(bpy.types.Operator):
    bl_idname = "mesh.clear_color_lists"
    bl_label = "Clear Color List"
    bl_description = "Clear the color list and color previews"

    def execute(self, context):
        scene = context.scene
        clear_color_lists(scene)
        self.report({'INFO'}, "Color list has been initialized.")
        return {'FINISHED'}

# --- 패널에 컬러 리스트 초기화 버튼 추가 ---
class VERTEXCOLOR_PT_select_panel(bpy.types.Panel):
    bl_label = "Select Faces by Vertex Color"
    bl_idname = "VERTEXCOLOR_PT_select_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'VCS'  # 네비게이션 탭 이름을 'VCS'로 변경

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        # Edit, Vertex Paint, Weight Paint, Texture Paint 모드에서만 표시
        return obj and obj.type == 'MESH' and context.mode in {
            'EDIT_MESH', 'PAINT_VERTEX', 'PAINT_WEIGHT', 'PAINT_TEXTURE'
        }

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.active_object

        # 컬러 속성 목록
        attr_names = [attr.name for attr in obj.data.color_attributes if attr.domain == 'CORNER'] if obj and obj.type == 'MESH' else []
        if not attr_names:
            box = layout.box()
            box.label(text="No Color Attribute", icon='ERROR')
            return

        # Color Attribute 선택 (한 번만!)
        layout.prop(scene.vc_selector, "color_attribute", text="Color")

        is_edit_mode = (context.mode == 'EDIT_MESH')

        # Color list manual reset button
        layout.operator("mesh.clear_color_lists", text="Clear Color List")

        # Find Colors UI
        find_row = layout.row()
        find_row.enabled = is_edit_mode
        find_row.operator("mesh.find_face_colors", text="Find Colors")
        if not is_edit_mode:
            box = layout.box()
            box.label(
                text="Edit Mode Only",
                icon='ERROR'
            )

        layout.label(text="Find Vertex Colors")

        # 컬러 리스트 표시
        face_colors = getattr(scene.vc_selector, "face_colors", None)
        color_previews = getattr(scene.vc_selector, "color_previews", None)
        if face_colors is None or color_previews is None or len(color_previews) == 0:
            return

        # 안내 박스
        box = layout.box()
        box.label(text="Shift: Add   Ctrl: Remove", icon='INFO')

        # Pick Vertex Color operator
        layout.operator("mesh.pick_vertex_color", text="Pick Vertex Color")

        # 컬러 리스트 라벨
        color_count = len(color_previews)
        layout.label(text=f"Color List ({color_count} color{'s' if color_count != 1 else ''} found)")

        # 팔레트 폴드 UI
        row = layout.row()
        icon = "TRIA_DOWN" if scene.vc_selector.show_color_list else "TRIA_RIGHT"
        row.prop(scene.vc_selector, "show_color_list", text="", icon=icon, emboss=False)
        row.label(text=f"Color List ({len(scene.vc_selector.color_previews)} colors found)")

        if not scene.vc_selector.show_color_list:
            return

        layout.label(text="Color Previews:")
        for item in color_previews:
            row = layout.row()
            row.prop(item, "color", text=item.name.split(" :")[0])
            op = row.operator("mesh.select_this_color", text="Select This Color")
            op.color = item.color

# --- Pick Vertex Color 오퍼레이터 추가 ---
class VCS_OT_pick_vertex_color(bpy.types.Operator):
    bl_idname = "mesh.pick_vertex_color"
    bl_label = "Pick Vertex Color"
    bl_description = "Pick vertex color from mesh under mouse cursor"
    bl_options = {'REGISTER', 'UNDO'}

    color: bpy.props.FloatVectorProperty(
        name="Picked Color",
        subtype='COLOR',
        size=3,
        min=0.0, max=1.0
    )

    def invoke(self, context, event):
        # shift 상태를 인스턴스 변수로 저장
        self._shift = event.shift
        self._ctrl = event.ctrl  # ← 이 줄 추가!
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set("Click on a mesh face to pick its vertex color (ESC to cancel)")
        context.window.cursor_set('EYEDROPPER')
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            context.area.header_text_set(None)
            context.window.cursor_set('DEFAULT')
            self.report({'INFO'}, "Pick cancelled")
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            obj = context.active_object

            context.area.header_text_set(None)
            context.window.cursor_set('DEFAULT')

            if not obj or obj.type != 'MESH':
                self.report({'ERROR'}, "No mesh object selected")
                return {'CANCELLED'}

            origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            depsgraph = context.evaluated_depsgraph_get()

            hit, location, normal, face_index, obj_ray, matrix = context.scene.ray_cast(
                depsgraph,
                origin,
                direction
            )
            if not hit or face_index < 0:
                self.report({'ERROR'}, "No face under cursor or face index out of range")
                return {'CANCELLED'}

            color_attr_name = context.scene.vc_selector.color_attribute

            if obj.mode == 'EDIT':
                bm = bmesh.from_edit_mesh(obj.data)
                bm.faces.ensure_lookup_table()
                if face_index >= len(bm.faces):
                    self.report({'ERROR'}, "Face index out of range in bmesh")
                    return {'CANCELLED'}
                face = bm.faces[face_index]
                color_layer = bm.loops.layers.color.get(color_attr_name)
                if not color_layer:
                    self.report({'ERROR'}, "No vertex color layer found in bmesh")
                    return {'CANCELLED'}
                colors = [loop[color_layer][:3] for loop in face.loops]
            else:
                # 항상 obj.data 사용 (페인트 모드 포함)
                mesh = obj.data
                if face_index >= len(mesh.polygons):
                    self.report({'ERROR'}, "Face index out of range in mesh")
                    return {'CANCELLED'}
                poly = mesh.polygons[face_index]
                color_layer = mesh.vertex_colors.get(color_attr_name) or mesh.color_attributes.get(color_attr_name)
                if not color_layer or len(color_layer.data) == 0:
                    self.report({'ERROR'}, "No vertex color layer found or layer has no data")
                    return {'CANCELLED'}
                if hasattr(color_layer, "domain") and color_layer.domain != 'CORNER':
                    self.report({'ERROR'}, "Color attribute domain must be CORNER")
                    return {'CANCELLED'}
                if color_layer.data and not hasattr(color_layer.data[0], "color"):
                    self.report({'ERROR'}, "Color attribute is not a color type")
                    return {'CANCELLED'}
                if any(li >= len(color_layer.data) for li in poly.loop_indices):
                    self.report({'ERROR'}, "Vertex color data index out of range (loop_indices)")
                    return {'CANCELLED'}
                colors = [color_layer.data[li].color[:3] for li in poly.loop_indices]

            if not colors:
                self.report({'ERROR'}, "No color data found for this face")
                return {'CANCELLED'}

            avg_color = tuple(sum(c[i] for c in colors) / len(colors) for i in range(3))
            self.color = avg_color

            threshold = VC_SELECTOR_THRESHOLD  # 내부 상수로 대체

            # --- modifier 우선순위 처리 ---
            shift = event.shift if (event.shift or event.ctrl) else getattr(self, "_shift", False)
            ctrl  = event.ctrl  if (event.shift or event.ctrl) else getattr(self, "_ctrl", False)

            if obj.mode == 'EDIT':
                bm = bmesh.from_edit_mesh(obj.data)
                color_layer = bm.loops.layers.color.get(color_attr_name)
                if not color_layer:
                    self.report({'ERROR'}, "No vertex color layer found")
                    return {'CANCELLED'}
                for face in bm.faces:
                    face_colors = [tuple(loop[color_layer][:3]) for loop in face.loops]
                    face_avg = tuple(round(sum(c[i] for c in face_colors)/len(face_colors), 4) for i in range(3))
                    if color_close(face_avg, avg_color, threshold):
                        if ctrl:
                            face.select_set(False)
                        else:
                            face.select_set(True)
                    elif not shift and not ctrl:
                        face.select_set(False)
                bmesh.update_edit_mesh(obj.data)
            else:
                # 페인트 모드(및 오브젝트 모드)도 여기서 처리
                mesh = obj.data
                color_layer = mesh.vertex_colors.get(color_attr_name) or mesh.color_attributes.get(color_attr_name)
                if not color_layer:
                    self.report({'ERROR'}, "No vertex color layer found")
                    return {'CANCELLED'}
                for poly in mesh.polygons:
                    poly_colors = [color_layer.data[li].color[:3] for li in poly.loop_indices]
                    poly_avg = tuple(round(sum(c[i] for c in poly_colors)/len(poly_colors), 4) for i in range(3))
                    if color_close(poly_avg, avg_color, threshold):
                        if ctrl:
                            poly.select = False
                        else:
                            poly.select = True
                    elif not shift and not ctrl:
                        poly.select = False

            self.report({'INFO'}, f"Picked and selected faces with color: {self.color}")
            return {'FINISHED'}

        return {'RUNNING_MODAL'}

# --- PropertyGroup 정의 ---
class VCSelectorColorPreview(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    color: bpy.props.FloatVectorProperty(subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0)

class VCSelectorProperties(bpy.types.PropertyGroup):
    face_colors: bpy.props.EnumProperty(
        name="Face Colors",
        items=[]
    )
    color_previews: bpy.props.CollectionProperty(type=VCSelectorColorPreview)
    last_mesh_id: bpy.props.StringProperty(
        name="Last Mesh ID",
        default=""
    )
    show_color_list: bpy.props.BoolProperty(
        name="Show Color List",
        default=True
    )
    def color_attr_items(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            return []
        return [(attr.name, attr.name, "") for attr in obj.data.color_attributes if attr.domain == 'CORNER']
    color_attribute: bpy.props.EnumProperty(
        name="Color Attribute",
        items=color_attr_items
    )

# --- 등록/해제 함수 수정 ---
def register():
    bpy.utils.register_class(VCSelectorColorPreview)
    bpy.utils.register_class(VCSelectorProperties)
    bpy.utils.register_class(VERTEXCOLOR_OT_find_face_colors)
    bpy.utils.register_class(VERTEXCOLOR_OT_select_faces_by_face_color)
    bpy.utils.register_class(VERTEXCOLOR_OT_select_this_color)
    bpy.utils.register_class(VERTEXCOLOR_OT_clear_color_lists)
    bpy.utils.register_class(VERTEXCOLOR_PT_select_panel)
    bpy.utils.register_class(VCS_OT_pick_vertex_color)
    bpy.types.Scene.vc_selector = bpy.props.PointerProperty(type=VCSelectorProperties)

def unregister():
    del bpy.types.Scene.vc_selector
    bpy.utils.unregister_class(VCSelectorColorPreview)
    bpy.utils.unregister_class(VCSelectorProperties)
    bpy.utils.unregister_class(VERTEXCOLOR_OT_find_face_colors)
    bpy.utils.unregister_class(VERTEXCOLOR_OT_select_faces_by_face_color)
    bpy.utils.unregister_class(VERTEXCOLOR_OT_select_this_color)
    bpy.utils.unregister_class(VERTEXCOLOR_OT_clear_color_lists)
    bpy.utils.unregister_class(VERTEXCOLOR_PT_select_panel)
    bpy.utils.unregister_class(VCS_OT_pick_vertex_color)

if __name__ == "__main__":
    register()
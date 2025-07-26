bl_info = {
    "name": "Vertex Color Selector",
    "author": "Your Name",
    "version": (1, 0, 6),
    "blender": (2, 80, 0),
    "location": "View3D > Sidebar > Vertex Color",
    "description": "Select faces by vertex color",
    "category": "Mesh",
}

import bpy
import bmesh
from bpy.app.handlers import persistent

# Blender 버전 호환성 처리
try:
    from bpy_extras import view3d_utils
except ImportError:
    import bpy_extras
    view3d_utils = bpy_extras.view3d_utils

def get_color_attr_items(scene, context):
    """전역 함수로 color attribute items를 반환"""
    obj = context.active_object if context else None
    items = []
    
    if obj and obj.type == 'MESH':
        for attr in obj.data.color_attributes:
            if attr.domain == 'CORNER':
                items.append((attr.name, attr.name, f"Color attribute: {attr.name}"))
    
    if not items:
        items.append(("NONE", "No Color Attributes", "No CORNER domain color attributes found"))
    
    return items

def ensure_valid_color_attribute(context):
    """유효한 컬러 어트리뷰트가 선택되도록 보장"""
    if not context or not hasattr(context, 'scene'):
        return
    
    scene = context.scene
    if not hasattr(scene, 'vc_selector'):
        return
    
    obj = context.active_object
    if not obj or obj.type != 'MESH':
        return
    
    # 현재 선택된 어트리뷰트 확인 - 안전한 접근
    try:
        current_attr = getattr(scene.vc_selector, "color_attribute", None)
    except (AttributeError, TypeError):
        current_attr = None
    
    # 사용 가능한 CORNER 어트리뷰트 목록
    available_attrs = [attr.name for attr in obj.data.color_attributes if attr.domain == 'CORNER']
    
    # 현재 선택된 어트리뷰트가 유효하지 않으면 첫 번째 사용 가능한 것으로 설정
    if not current_attr or current_attr == "NONE" or current_attr not in available_attrs:
        if available_attrs:
            try:
                scene.vc_selector.color_attribute = available_attrs[0]
            except (AttributeError, TypeError):
                pass  # PropertyGroup이 아직 초기화되지 않은 경우
        else:
            try:
                scene.vc_selector.color_attribute = "NONE"
            except (AttributeError, TypeError):
                pass  # PropertyGroup이 아직 초기화되지 않은 경우

@persistent
def scene_update_handler(scene):
    """씬이 업데이트될 때 color attribute 목록을 갱신하고 유효성 검증"""
    context = bpy.context
    ensure_valid_color_attribute(context)

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
        
        # 컬러 어트리뷰트 검증 - 안전한 접근 방법
        try:
            color_attr_name = getattr(scene.vc_selector, "color_attribute", None)
            if not color_attr_name or color_attr_name == "NONE":
                self.report({'ERROR'}, "No color attribute selected!")
                return {'CANCELLED'}
        except (AttributeError, TypeError):
            self.report({'ERROR'}, "Color attribute property not initialized!")
            return {'CANCELLED'}
        
        # 선택된 어트리뷰트가 실제로 존재하는지 확인
        color_attr = obj.data.color_attributes.get(color_attr_name)
        if not color_attr:
            self.report({'ERROR'}, f"Color attribute '{color_attr_name}' not found!")
            return {'CANCELLED'}
        
        if color_attr.domain != 'CORNER':
            self.report({'ERROR'}, f"Color attribute '{color_attr_name}' must be CORNER domain!")
            return {'CANCELLED'}

        current_mesh_id = obj.data.name if obj and obj.data else ""
        last_mesh_id = getattr(scene, "vc_selector_last_mesh_id", "")
        if current_mesh_id != last_mesh_id:
            clear_color_lists(scene)
            scene.vc_selector.last_mesh_id = current_mesh_id

        bm = bmesh.from_edit_mesh(obj.data)
        color_layer = bm.loops.layers.color.get(color_attr_name)
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

        # 컬러 어트리뷰트 검증
        if not scene.vc_selector.color_attribute or scene.vc_selector.color_attribute == "NONE":
            self.report({'ERROR'}, "No color attribute selected!")
            return {'CANCELLED'}

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

# 2. 컬러별 선택 오퍼레이터 추가
class VERTEXCOLOR_OT_select_this_color(bpy.types.Operator):
    bl_idname = "mesh.select_this_color"
    bl_label = "Select This Color"
    color = bpy.props.FloatVectorProperty(size=3)

    def invoke(self, context, event):
        self.shift = event.shift
        self.ctrl = event.ctrl
        return self.execute(context)

    def execute(self, context):
        scene = context.scene
        obj = context.active_object
        mode = obj.mode
        
        # 컬러 어트리뷰트 검증
        if not scene.vc_selector.color_attribute or scene.vc_selector.color_attribute == "NONE":
            self.report({'ERROR'}, "No color attribute selected!")
            return {'CANCELLED'}
        
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

# --- Attribute Refresh 오퍼레이터 ---
class VERTEXCOLOR_OT_refresh_color_attributes(bpy.types.Operator):
    bl_idname = "mesh.refresh_color_attributes"
    bl_label = "Attribute Refresh"
    bl_description = "Refresh and update the color attribute list"
    
    def execute(self, context):
        scene = context.scene
        obj = context.active_object
        
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "No mesh object selected!")
            return {'CANCELLED'}
        
        # PropertyGroup이 제대로 초기화되었는지 확인
        if not hasattr(scene, 'vc_selector'):
            self.report({'ERROR'}, "VCS PropertyGroup not initialized!")
            return {'CANCELLED'}
        
        # CORNER 도메인 어트리뷰트 찾기
        corner_attrs = [attr.name for attr in obj.data.color_attributes if attr.domain == 'CORNER']
        
        # 디버그 정보 출력 (Refresh 버튼을 눌렀을 때만)
        print(f"[VCS Debug] Attribute Refresh executed")
        print(f"[VCS Debug] Available: {len(corner_attrs)} CORNER attributes")
        for attr in obj.data.color_attributes:
            print(f"[VCS Debug]   • {attr.name} ({attr.domain})")
        
        if not corner_attrs:
            self.report({'WARNING'}, "No CORNER color attributes found!")
            # 빈 목록으로 EnumProperty 업데이트
            items = [("NONE", "No Color Attributes", "No CORNER domain color attributes found")]
        else:
            # 찾은 어트리뷰트로 EnumProperty items 생성
            items = [(attr, attr, f"Color attribute: {attr}") for attr in corner_attrs]
            # 현재 어트리뷰트가 유효하지 않으면 첫 번째로 설정 (매우 안전하게)
            try:
                if hasattr(scene.vc_selector, 'color_attribute'):
                    current_attr = getattr(scene.vc_selector, 'color_attribute', None)
                    if not current_attr or current_attr == "NONE" or current_attr not in corner_attrs:
                        scene.vc_selector.color_attribute = corner_attrs[0]
                        print(f"[VCS Debug] Set default attribute to: {corner_attrs[0]}")
            except Exception as e:
                print(f"[VCS Debug] Could not set default attribute: {e}")
        
        # EnumProperty 동적 업데이트를 위해 PropertyGroup 재정의
        try:
            # 먼저 기존 items 삭제
            if hasattr(bpy.types.Scene, 'vc_selector_color_attr_items'):
                delattr(bpy.types.Scene, 'vc_selector_color_attr_items')
            
            # 새로운 items 설정
            bpy.types.Scene.vc_selector_color_attr_items = items
            print(f"[VCS Debug] Updated items list with {len(items)} entries")
            
            # PropertyGroup을 강제로 다시 등록하여 EnumProperty 갱신
            # 이는 동적 items가 제대로 업데이트되도록 함
            prop_class = scene.vc_selector.__class__
            if hasattr(prop_class, 'color_attribute'):
                print(f"[VCS Debug] PropertyGroup has color_attribute property")
            
            # UI 강제 업데이트
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
                    
        except Exception as e:
            print(f"[VCS Debug] Error updating items: {e}")
        
        self.report({'INFO'}, f"Found {len(corner_attrs)} CORNER color attributes")
        return {'FINISHED'}

# --- 컬러 어트리뷰트 설정 오퍼레이터 ---
class VERTEXCOLOR_OT_set_color_attribute(bpy.types.Operator):
    bl_idname = "mesh.set_color_attribute"
    bl_label = "Set Color Attribute"
    bl_description = "Set the selected color attribute"
    
    attr_name = bpy.props.StringProperty()
    
    def execute(self, context):
        # 현재 어트리뷰트가 유효한지 확인
        obj = context.active_object
        if obj and obj.type == 'MESH':
            corner_attrs = [attr.name for attr in obj.data.color_attributes if attr.domain == 'CORNER']
            if self.attr_name in corner_attrs:
                context.scene.vc_selector.color_attribute = self.attr_name
                self.report({'INFO'}, f"Color attribute set to: {self.attr_name}")
            else:
                self.report({'ERROR'}, f"Color attribute '{self.attr_name}' not found or not CORNER domain!")
                return {'CANCELLED'}
        else:
            self.report({'ERROR'}, "No mesh object selected!")
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

        # 항상 리프레시 버튼을 맨 위에 표시
        layout.operator("mesh.refresh_color_attributes", text="Attribute Refresh", icon='FILE_REFRESH')

        # PropertyGroup 초기화 확인
        if not hasattr(scene, 'vc_selector') or scene.vc_selector is None:
            layout.label(text="VCS PropertyGroup not initialized", icon='ERROR')
            layout.label(text="Click Attribute Refresh to initialize", icon='INFO')
            return

        # 색상 어트리뷰트 속성이 실제로 존재하는지 확인
        if not hasattr(scene.vc_selector, 'color_attribute'):
            layout.label(text="color_attribute property not found", icon='ERROR')
            layout.label(text="Click Attribute Refresh to fix", icon='INFO')
            return
            
        # 컬러 어트리뷰트 드롭다운 - 최대한 안전한 표시
        dropdown_success = False
        current_attr = None
        
        # 먼저 현재 선택된 값을 안전하게 읽기
        try:
            current_attr = getattr(scene.vc_selector, "color_attribute", None)
        except (AttributeError, TypeError):
            current_attr = None
        
        # 드롭다운 시도
        try:
            # PropertyGroup 클래스에 속성이 정의되어 있는지 확인
            prop_class = scene.vc_selector.__class__
            if hasattr(prop_class, 'color_attribute') and hasattr(scene.vc_selector, 'color_attribute'):
                # 추가 검증: 실제로 접근 가능한지 테스트
                test_value = scene.vc_selector.color_attribute
                layout.prop(scene.vc_selector, "color_attribute", text="Color Attribute")
                dropdown_success = True
        except Exception as e:
            print(f"[VCS Debug] Dropdown error: {e}")
            dropdown_success = False
        
        if not dropdown_success:
            # 드롭다운이 실패하면 현재 값과 함께 대체 표시
            if current_attr and current_attr != "NONE":
                layout.label(text=f"Color Attribute: {current_attr}", icon='COLOR')
            else:
                layout.label(text="Color Attribute: Click Refresh button", icon='INFO')
        
        # 현재 선택값 확인 (이미 위에서 읽었음)
        # current_attr은 이미 안전하게 읽었으므로 추가 접근 불필요
        
        if not current_attr or current_attr == "NONE":
            box = layout.box()
            box.label(text="No color attribute selected", icon='INFO')
            if obj and obj.type == 'MESH':
                corner_attrs = [attr.name for attr in obj.data.color_attributes if attr.domain == 'CORNER']
                if not corner_attrs:
                    box.label(text="No CORNER color attributes found")
                    if obj.data.color_attributes:
                        box.label(text="Available attributes (wrong domain):")
                        for attr in obj.data.color_attributes:
                            box.label(text=f"  • {attr.name} ({attr.domain})")
            return

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
        try:
            face_colors = getattr(scene.vc_selector, "face_colors", None)
            color_previews = getattr(scene.vc_selector, "color_previews", None)
            
            # PropertyGroup의 CollectionProperty는 len() 대신 이렇게 체크
            if (face_colors is None or 
                color_previews is None or 
                not hasattr(color_previews, '__len__') or 
                len(list(color_previews)) == 0):
                return
        except (TypeError, AttributeError):
            # _PropertyDeferred 오류 방지
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

    color = bpy.props.FloatVectorProperty(
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
            
            # 컬러 어트리뷰트 검증
            if not color_attr_name or color_attr_name == "NONE":
                self.report({'ERROR'}, "No color attribute selected!")
                return {'CANCELLED'}

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
    name = bpy.props.StringProperty()
    color = bpy.props.FloatVectorProperty(subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0)

def get_refreshed_color_attr_items(self, context):
    """Refresh된 color attribute items를 반전"""
    try:
        # 안전하게 items 가져오기
        items = getattr(bpy.types.Scene, 'vc_selector_color_attr_items', None)
        if items and isinstance(items, list) and len(items) > 0:
            # 리스트가 올바른 형식인지 검증
            valid_items = []
            for item in items:
                if isinstance(item, tuple) and len(item) >= 2:
                    valid_items.append(item)
            if valid_items:
                return valid_items
        
        # 기본값 반환
        return [("NONE", "Click Attribute Refresh", "Click Attribute Refresh button to scan color attributes")]
    except Exception as e:
        # 오류 발생 시 기본값 반환
        print(f"[VCS Debug] Error in get_refreshed_color_attr_items: {e}")
        return [("NONE", "Error - Click Refresh", "Error occurred, click Attribute Refresh button")]

class VCSelectorProperties(bpy.types.PropertyGroup):
    face_colors = bpy.props.EnumProperty(
        name="Face Colors",
        items=[]
    )
    color_previews = bpy.props.CollectionProperty(type=VCSelectorColorPreview)
    last_mesh_id = bpy.props.StringProperty(
        name="Last Mesh ID",
        default=""
    )
    show_color_list = bpy.props.BoolProperty(
        name="Show Color List",
        default=True
    )
    
    def color_attr_update(self, context):
        # 컬러 어트리뷰트가 변경되면 기존 컬러 리스트 초기화
        if hasattr(context.scene, 'vc_selector'):
            clear_color_lists(context.scene)
        # 변경 후 유효성 다시 확인
        ensure_valid_color_attribute(context)
    
    # EnumProperty로 변경하여 드롭다운 제공
    color_attribute = bpy.props.EnumProperty(
        name="Color Attribute",
        items=get_refreshed_color_attr_items,
        update=color_attr_update,
        description="Select a color attribute to work with"
    )

# --- 등록/해제 함수 수정 ---
def register():
    # 순서가 중요합니다!
    bpy.utils.register_class(VCSelectorColorPreview)
    bpy.utils.register_class(VCSelectorProperties)
    
    # PropertyGroup을 Scene에 등록
    bpy.types.Scene.vc_selector = bpy.props.PointerProperty(type=VCSelectorProperties)
    
    # 나머지 클래스들 등록
    bpy.utils.register_class(VERTEXCOLOR_OT_find_face_colors)
    bpy.utils.register_class(VERTEXCOLOR_OT_select_faces_by_face_color)
    bpy.utils.register_class(VERTEXCOLOR_OT_select_this_color)
    bpy.utils.register_class(VERTEXCOLOR_OT_refresh_color_attributes)
    bpy.utils.register_class(VERTEXCOLOR_OT_set_color_attribute)
    bpy.utils.register_class(VERTEXCOLOR_OT_clear_color_lists)
    bpy.utils.register_class(VERTEXCOLOR_PT_select_panel)
    bpy.utils.register_class(VCS_OT_pick_vertex_color)
    
    # 핸들러 등록
    if scene_update_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(scene_update_handler)
    
    print("[VCS] Registration complete")
    
    # 등록 직후 기본값 설정
    try:
        ensure_valid_color_attribute(bpy.context)
    except:
        pass  # 컨텍스트가 없으면 무시

def unregister():
    # 핸들러 해제
    if scene_update_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(scene_update_handler)
    
    # PropertyGroup 해제 (다른 클래스들보다 먼저)
    if hasattr(bpy.types.Scene, 'vc_selector'):
        del bpy.types.Scene.vc_selector
    
    # 클래스들 해제 (역순으로)
    bpy.utils.unregister_class(VCS_OT_pick_vertex_color)
    bpy.utils.unregister_class(VERTEXCOLOR_PT_select_panel)
    bpy.utils.unregister_class(VERTEXCOLOR_OT_clear_color_lists)
    bpy.utils.unregister_class(VERTEXCOLOR_OT_set_color_attribute)
    bpy.utils.unregister_class(VERTEXCOLOR_OT_refresh_color_attributes)
    bpy.utils.unregister_class(VERTEXCOLOR_OT_select_this_color)
    bpy.utils.unregister_class(VERTEXCOLOR_OT_select_faces_by_face_color)
    bpy.utils.unregister_class(VERTEXCOLOR_OT_find_face_colors)
    bpy.utils.unregister_class(VCSelectorProperties)
    bpy.utils.unregister_class(VCSelectorColorPreview)
    
    print("[VCS] Unregistration complete")

if __name__ == "__main__":
    register()
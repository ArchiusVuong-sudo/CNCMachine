"""STEP file loading and assembly tree decomposition using PythonOCC XDE framework."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_ColorTool, XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

logger = logging.getLogger(__name__)


@dataclass
class ComponentData:
    """Represents a single component extracted from a STEP assembly."""

    name: str
    description: str
    label: TDF_Label
    shape: TopoDS_Shape
    location: TopLoc_Location
    assembly_path: str
    is_assembly: bool = False
    children: list[ComponentData] = field(default_factory=list)


def _get_label_name(label: TDF_Label) -> str:
    """Extract the name string from a TDF_Label via TDataStd_Name."""
    name_attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), name_attr):
        return name_attr.Get().ToExtString()
    return ""


def _traverse_assembly(
    shape_tool: XCAFDoc_ShapeTool,
    label: TDF_Label,
    parent_path: str,
) -> ComponentData:
    """Recursively traverse the assembly tree from a given label."""
    name = _get_label_name(label)
    if not name:
        name = f"Component_{label.Tag()}"

    current_path = f"{parent_path}/{name}"
    location = shape_tool.GetLocation_s(label)
    is_assembly = shape_tool.IsAssembly_s(label)

    # Get the shape — for references, resolve to the referred shape
    if shape_tool.IsReference_s(label):
        ref_label = TDF_Label()
        shape_tool.GetReferredShape_s(label, ref_label)
        shape = shape_tool.GetShape_s(ref_label)
        resolved_name = _get_label_name(ref_label)
        if resolved_name:
            name = resolved_name
            current_path = f"{parent_path}/{name}"
        is_assembly = shape_tool.IsAssembly_s(ref_label)
        working_label = ref_label
    else:
        shape = shape_tool.GetShape_s(label)
        working_label = label

    component = ComponentData(
        name=name,
        description="",
        label=label,
        shape=shape,
        location=location,
        assembly_path=current_path,
        is_assembly=is_assembly,
    )

    # Recurse into sub-components if this is an assembly
    if is_assembly:
        sub_labels = TDF_LabelSequence()
        shape_tool.GetComponents_s(working_label, sub_labels)
        for i in range(sub_labels.Length()):
            sub_label = sub_labels.Value(i + 1)  # 1-indexed
            child = _traverse_assembly(shape_tool, sub_label, current_path)
            component.children.append(child)

    return component


def _collect_leaf_components(component: ComponentData) -> list[ComponentData]:
    """Flatten the tree, returning only leaf parts (non-assembly solids)."""
    if not component.is_assembly and not component.children:
        return [component]
    leaves: list[ComponentData] = []
    for child in component.children:
        leaves.extend(_collect_leaf_components(child))
    return leaves


def _shape_diagnostics(shape: TopoDS_Shape) -> dict:
    """Quick stats so we can tell why a leaf produced bbox=0 (empty? shell-only?)."""
    if shape is None or shape.IsNull():
        return {"is_null": True, "solids": 0, "shells": 0}
    solids = 0
    shells = 0
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        solids += 1
        exp.Next()
    exp = TopExp_Explorer(shape, TopAbs_SHELL)
    while exp.More():
        shells += 1
        exp.Next()
    return {"is_null": False, "solids": solids, "shells": shells,
            "shape_type": int(shape.ShapeType())}


def load_step_assembly(file_path: str | Path) -> tuple[str, list[ComponentData], TDocStd_Document, TopoDS_Shape | None]:
    """
    Load a STEP file and decompose it into individual components.

    Returns:
        (assembly_name, list_of_leaf_components, xde_document, top_level_shape)
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"STEP file not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext not in (".stp", ".step"):
        raise ValueError(f"Unsupported file extension: {ext}. Use .stp or .step")

    logger.info("Loading STEP file: %s", file_path)

    # Create XDE document
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(doc)

    # Read STEP with XDE reader
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    reader.SetLayerMode(True)

    status = reader.ReadFile(str(file_path))
    if status != IFSelect_RetDone:
        raise RuntimeError(f"Failed to read STEP file: status={status}")

    if not reader.Transfer(doc):
        raise RuntimeError("Failed to transfer STEP data into XDE document")

    # Get shape and color tools
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    # Get top-level free shapes
    free_shapes = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_shapes)

    if free_shapes.Length() == 0:
        raise RuntimeError("No shapes found in STEP file")

    # Determine assembly name from the top-level label
    top_label = free_shapes.Value(1)
    assembly_name = _get_label_name(top_label)
    if not assembly_name:
        assembly_name = file_path.stem

    # Capture the top-level shape for fallback volume computation
    top_level_shape = shape_tool.GetShape_s(top_label)

    logger.info("Assembly: %s, top-level shapes: %d", assembly_name, free_shapes.Length())

    # Traverse all top-level shapes
    all_components: list[ComponentData] = []
    for i in range(free_shapes.Length()):
        label = free_shapes.Value(i + 1)
        tree = _traverse_assembly(shape_tool, label, "")
        leaves = _collect_leaf_components(tree)
        all_components.extend(leaves)

    # Deduplicate by name — instances of the same part share geometry
    # but may have different locations. Keep all instances.
    logger.info("Found %d leaf components", len(all_components))

    # Diagnostic: warn loudly when a leaf has no solid/shell content —
    # those produce bbox=0×0×0 downstream and let agents hallucinate.
    for c in all_components:
        diag = _shape_diagnostics(c.shape)
        if diag.get("is_null") or (diag.get("solids", 0) == 0 and diag.get("shells", 0) == 0):
            logger.warning(
                "step_parser: leaf %r has no solid/shell geometry: %s",
                c.name, diag,
            )

    # If no leaf components found, the file might contain only simple solids
    if not all_components:
        logger.warning("No leaf components via XDE; falling back to shape explorer")
        all_components = _fallback_extract_solids(shape_tool, free_shapes, file_path.stem)

    # Populate product descriptions from STEP entities
    _populate_descriptions(reader, all_components)

    return assembly_name, all_components, doc, top_level_shape


def _fallback_extract_solids(
    shape_tool: XCAFDoc_ShapeTool,
    free_shapes: TDF_LabelSequence,
    fallback_name: str,
) -> list[ComponentData]:
    """Fallback: extract solids directly when XDE assembly tree is flat."""
    components: list[ComponentData] = []
    for i in range(free_shapes.Length()):
        label = free_shapes.Value(i + 1)
        shape = shape_tool.GetShape_s(label)
        name = _get_label_name(label) or f"{fallback_name}_solid_{i}"

        if shape.ShapeType() == TopAbs_COMPOUND:
            explorer = TopExp_Explorer(shape, TopAbs_SOLID)
            solid_idx = 0
            while explorer.More():
                solid = TopoDS.Solid_s(explorer.Current())
                comp = ComponentData(
                    name=f"{name}_solid_{solid_idx}",
                    description="",
                    label=label,
                    shape=solid,
                    location=TopLoc_Location(),
                    assembly_path=f"/{name}/{name}_solid_{solid_idx}",
                )
                components.append(comp)
                solid_idx += 1
                explorer.Next()
        else:
            comp = ComponentData(
                name=name,
                description="",
                label=label,
                shape=shape,
                location=TopLoc_Location(),
                assembly_path=f"/{name}",
            )
            components.append(comp)

    return components


def _populate_descriptions(
    reader: STEPCAFControl_Reader,
    components: list[ComponentData],
) -> None:
    """Match STEP product descriptions to components by name/id."""
    try:
        from OCP.StepBasic import StepBasic_Product
    except ImportError:
        logger.debug("StepBasic_Product not available; skipping descriptions")
        return

    try:
        ws = reader.Reader().WS()
        model = ws.Model()
    except Exception as e:
        logger.debug("Cannot access STEP model for descriptions: %s", e)
        return

    # Build name/id -> description lookup from STEP PRODUCT entities
    desc_map: dict[str, str] = {}
    n = model.NbEntities()
    for i in range(1, n + 1):
        ent = model.Entity(i)
        if isinstance(ent, StepBasic_Product):
            name = ent.Name().ToCString().strip() if ent.Name() else ""
            pid = ent.Id().ToCString().strip() if ent.Id() else ""
            desc = ent.Description().ToCString().strip() if ent.Description() else ""
            if desc:
                if name:
                    desc_map[name] = desc
                if pid and pid != name:
                    desc_map[pid] = desc

    if not desc_map:
        logger.debug("No product descriptions found in STEP file")
        return

    logger.info("Found %d product descriptions in STEP file", len(desc_map))

    for comp in components:
        if comp.name in desc_map:
            comp.description = desc_map[comp.name]

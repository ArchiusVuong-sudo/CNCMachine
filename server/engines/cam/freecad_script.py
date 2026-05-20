"""The Python source that runs inside FreeCAD's interpreter.

Kept as a module-level string (``FREECAD_SCRIPT``) so :mod:`.freecad_runner`
can materialize it to a tempdir alongside the STEP + job spec before
spawning the FreeCAD subprocess. The pattern is identical to
:mod:`server.engines.extraction_3d.welding`.

The script reads:

  * ``argv[1]`` — STEP file path (one component per invocation; the parent
    keeps invocations 1-to-1 with components).
  * ``argv[2]`` — JSON job-spec path. See :func:`_job_spec_for_component`
    in :mod:`.engine` for the shape; the script trusts the parent's
    serialization.
  * ``argv[3]`` — output directory for ``.nc`` files.

It writes structured JSON to stdout (last line = result) and per-op
progress to stderr (the parent streams that into the trace logger).
Never raises — every failure mode resolves to ``{"ok": false, ...}``.
"""
from __future__ import annotations

import textwrap

FREECAD_SCRIPT = textwrap.dedent("""\
    #!/usr/bin/env python3
    '''CAM G-code generation via FreeCAD Path. Subprocess entry.'''
    import sys, os, json, traceback, re

    # Wire up FreeCAD's binary path so `import FreeCAD` resolves. Layout
    # differs by platform — see welding.py for the parallel implementation.
    if sys.platform == "win32":
        # Windows conda: <env>/python.exe + <env>/Library/bin/FreeCAD.pyd
        _libbin = os.path.join(os.path.dirname(sys.executable), "Library", "bin")
        if os.path.isdir(_libbin):
            sys.path.insert(0, _libbin)
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(_libbin)
    else:
        # Linux pod: hardcoded conda env path (matches install_freecad.sh).
        _FC_LIB = "/workspace/miniconda3/envs/freecad/lib"
        if os.path.isdir(_FC_LIB):
            sys.path.insert(0, _FC_LIB)
            os.environ["LD_LIBRARY_PATH"] = (
                _FC_LIB + ":/usr/local/cuda-12.9/compat:/usr/local/cuda-12.9/lib64:"
                + os.environ.get("LD_LIBRARY_PATH", "")
            )

    def _emit(payload):
        '''Last line of stdout = the parent's parsed result.'''
        print(json.dumps(payload))

    if len(sys.argv) < 4:
        _emit({"ok": False, "error": "argv: <step> <job_spec> <out_dir>"})
        sys.exit(1)

    step_file = sys.argv[1]
    spec_file = sys.argv[2]
    out_dir   = sys.argv[3]
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as exc:
        _emit({"ok": False, "error": f"mkdir failed: {exc}"})
        sys.exit(1)

    try:
        with open(spec_file, "r", encoding="utf-8") as f:
            spec = json.load(f)
    except Exception as exc:
        _emit({"ok": False, "error": f"job spec load failed: {exc}"})
        sys.exit(1)

    # ── FreeCAD import ────────────────────────────────────────────────────
    try:
        import FreeCAD, Part
        import Path
        # PathScripts has moved between versions; we touch it lazily inside
        # the op handlers so missing modules fail per-op rather than at boot.
    except ImportError as exc:
        _emit({
            "ok": False, "error": f"FreeCAD not available: {exc}",
            "traceback": traceback.format_exc(),
            "outputs": [],
        })
        sys.exit(0)

    # ── Helpers ───────────────────────────────────────────────────────────
    def _face_index_from_key(key_face_id):
        '''OCC encodes IDs as "Face{N}_{sha256_16}" — recover the 1-based N.'''
        if not key_face_id:
            return None
        m = re.match(r"^Face(\\d+)_", str(key_face_id))
        if not m:
            return None
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            return None

    def _resolve_faces(part_obj, key_face_ids):
        '''Map a list of key_face_ids → list of (obj, ("FaceN",)) tuples.

        Silently drops IDs whose index is out of range — the op will then
        cover whatever survived (Path Profile / Pocket both accept empty
        base-geometry and fall back to the whole-solid silhouette).
        '''
        out = []
        n_faces = len(part_obj.Shape.Faces) if getattr(part_obj, "Shape", None) else 0
        for kfid in key_face_ids or []:
            idx = _face_index_from_key(kfid)
            if idx is None or idx < 1 or idx > n_faces:
                sys.stderr.write(f"[cam] skipping {kfid}: index out of range (1..{n_faces})\\n")
                continue
            out.append((part_obj, (f"Face{idx}",)))
        return out

    def _make_tool(doc, tool_type, dims):
        '''Build a Path Tool with the dimensions from Phase C.

        FreeCAD's Path.Tool API is positional; we pass diameter / corner_radius
        explicitly and let the rest default. ``tool_type`` maps onto FreeCAD's
        TYPE strings — anything outside the table falls back to "EndMill".
        '''
        TYPE_MAP = {
            "End Mill":       "EndMill",
            "Ball Mill":      "BallEndMill",
            "Chamfer Mill":   "ChamferMill",
            "Face Mill":      "EndMill",  # FreeCAD treats face mill as wide end mill
            "Drill":          "Drill",
            "Thread Mill":    "ThreadMill",
            "Form Tool":      "EndMill",
            "Radius Mill":    "BallEndMill",
            "Slitting Saw":   "SlotCutter",
            "Dovetail":       "DovetailCutter",
        }
        fc_type = TYPE_MAP.get(tool_type or "", "EndMill")
        diameter = float((dims or {}).get("diameter_mm") or 6.0)
        length   = float((dims or {}).get("length_mm")   or max(20.0, diameter * 4))
        corner_r = float((dims or {}).get("corner_radius_mm") or 0.0)
        try:
            tool = Path.Tool(
                name=f"T_{fc_type}_{diameter:.2f}",
                tooltype=fc_type,
                diameter=diameter,
                lengthOffset=length,
                cornerRadius=corner_r,
            )
        except TypeError:
            # Older FreeCAD signatures: positional fallback.
            tool = Path.Tool(f"T_{fc_type}_{diameter:.2f}", fc_type, diameter, 0, 0)
        return tool

    def _make_tool_controller(doc, tool, spindle_rpm, feedrate):
        '''Wrap a Tool in a ToolController. Returns the TC object or None.'''
        try:
            from PathScripts import PathToolController as PTC
            tc = PTC.Create()
        except Exception:
            try:
                tc = Path.ToolController()
                doc.addObject("Path::FeaturePython", "TC").Proxy = tc
            except Exception as exc:
                sys.stderr.write(f"[cam] ToolController create failed: {exc}\\n")
                return None
        try:
            tc.Tool = tool
            if spindle_rpm and spindle_rpm > 0:
                tc.SpindleSpeed = float(spindle_rpm)
            if feedrate and feedrate > 0:
                tc.HorizFeed = float(feedrate)
                tc.VertFeed  = float(feedrate) / 2.0
        except Exception as exc:
            sys.stderr.write(f"[cam] TC wire failed: {exc}\\n")
        return tc

    def _create_path_op(doc, job, path_op_str, base_faces, params):
        '''Instantiate the FreeCAD Path op named by ``path_op_str``.

        ``path_op_str`` is one of "Path.Profile" / "Path.Pocket" / etc. from
        :mod:`op_mapping`. The lookup tries the modern Path.* namespace
        first and falls back to PathScripts.* for older FreeCAD.
        '''
        op_name = path_op_str.split(".")[-1]   # "Profile", "Pocket", …
        # 1. Try Path.<Op>.Create (FreeCAD 1.0+).
        op = None
        try:
            mod = getattr(Path, op_name, None)
            if mod is not None and hasattr(mod, "Create"):
                op = mod.Create(op_name)
        except Exception as exc:
            sys.stderr.write(f"[cam] Path.{op_name}.Create failed: {exc}\\n")

        # 2. Fallback: PathScripts.Path<Op>Gui.
        if op is None:
            try:
                modname = f"PathScripts.Path{op_name}"
                mod = __import__(modname, fromlist=["Create"])
                op = mod.Create(op_name)
            except Exception as exc:
                sys.stderr.write(f"[cam] PathScripts.Path{op_name} failed: {exc}\\n")
                return None

        # Attach base geometry. Faces are optional — some ops (Surface, Engrave)
        # don't need them.
        if base_faces:
            try:
                op.Base = base_faces
            except Exception as exc:
                sys.stderr.write(f"[cam] op.Base assign failed: {exc}\\n")

        # Wire S/F/SO/SD onto the op props that exist (different ops expose
        # different subsets — assign-if-present is the FreeCAD convention).
        for k, v in (params or {}).items():
            if v is None:
                continue
            if hasattr(op, k):
                try:
                    setattr(op, k, v)
                except Exception as exc:
                    sys.stderr.write(f"[cam] op.{k}={v} failed: {exc}\\n")

        # Attach to job.
        try:
            job.Proxy.addOperation(op)
        except Exception:
            try:
                job.Operations.Group = list(job.Operations.Group or []) + [op]
            except Exception as exc:
                sys.stderr.write(f"[cam] addOperation failed: {exc}\\n")
        return op

    def _make_job(doc, part_obj, post_processor):
        '''Create a Path Job that owns the operations.'''
        try:
            from PathScripts import PathJob, PathJobGui   # noqa: F401
            job = PathJob.Create("Job", [part_obj])
        except Exception:
            try:
                # Newer FreeCAD: Path.Job.
                job = Path.Job.Create("Job", [part_obj])
            except Exception as exc:
                sys.stderr.write(f"[cam] Job.Create failed: {exc}\\n")
                return None
        try:
            job.PostProcessor = post_processor or "linuxcnc"
        except Exception:
            pass
        return job

    def _post_process(job, out_path, ops_list):
        '''Post-process exactly ``ops_list`` (one or more Path ops).

        Each invocation produces a self-contained .nc — passing the per-op
        list keeps successive files from accumulating prior ops. FreeCAD's
        PostProcessor API is version-dependent, so we try the modern
        PathScripts.PathPost first then fall back to Path.Post.
        '''
        try:
            from PathScripts import PathPost
            processor = PathPost.PostProcessor.load(job.PostProcessor)
            gcode = processor.export(ops_list, out_path, "")
            return True, str(out_path), len(gcode) if gcode else 0
        except Exception as exc:
            # Older FreeCAD: try Path.Post.
            try:
                from Path import Post as _Post
                gcode = _Post.processObjects(ops_list, job.PostProcessor)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(gcode if isinstance(gcode, str) else "\\n".join(gcode))
                return True, str(out_path), os.path.getsize(out_path)
            except Exception as exc2:
                return False, f"post failed: {exc} / {exc2}", 0

    # ── Main pipeline ─────────────────────────────────────────────────────
    try:
        doc = FreeCAD.newDocument("cam")
        shape = Part.read(step_file)

        post = spec.get("post_processor") or "linuxcnc"
        analysis_id = spec.get("analysis_id") or "unknown"
        component_name = spec.get("component_name") or "comp0"
        component_solid_index = spec.get("component_solid_index")
        ops_spec = spec.get("operations") or []

        # Pick the right solid when the STEP is a multi-body assembly. The
        # parent passes ``component_solid_index`` so the per-component face
        # numbering aligns with what OCC saw. If it's missing or the index
        # is out of range we fall back to the full compound (acceptable for
        # single-component parts; lossy for assemblies but always non-fatal).
        solids = list(shape.Solids)
        if (component_solid_index is not None
                and 0 <= int(component_solid_index) < len(solids)):
            target_shape = solids[int(component_solid_index)]
            sys.stderr.write(
                f"[cam] using solid #{component_solid_index} of {len(solids)} for "
                f"component {component_name}\\n"
            )
        else:
            target_shape = shape
            sys.stderr.write(
                f"[cam] using full shape — {len(shape.Faces)} face(s), {len(solids)} solid(s)\\n"
            )
        part_obj = doc.addObject("Part::Feature", "Stock")
        part_obj.Shape = target_shape
        doc.recompute()

        if not ops_spec:
            _emit({
                "ok": True, "outputs": [],
                "note": f"no CAM ops in spec for {component_name}",
            })
            sys.exit(0)

        job = _make_job(doc, part_obj, post)
        if job is None:
            _emit({"ok": False, "error": "Job.Create failed — Path workbench missing?"})
            sys.exit(0)

        outputs = []
        per_op_errors = []
        for op_spec in ops_spec:
            sequence = op_spec.get("sequence") or 0
            op_code  = op_spec.get("op_code")  or "UNKNOWN"
            path_op  = op_spec.get("path_op")  or "Path.Profile"
            kind     = op_spec.get("kind")     or "mill"

            sys.stderr.write(
                f"[cam] op {sequence:02d} {op_code} → {path_op} ({kind})\\n"
            )

            base_faces = _resolve_faces(part_obj, op_spec.get("key_face_ids"))

            # Build tool + TC for this op (one TC per op keeps the
            # post-processor honest; FreeCAD allows TC reuse but cost is
            # negligible at this scale).
            tool = _make_tool(doc, op_spec.get("tool_type"), op_spec.get("tool_dimensions"))
            tc   = _make_tool_controller(
                doc, tool,
                op_spec.get("spindle_speed_rpm"),
                op_spec.get("feed_rate_mm_min"),
            )

            # Common Path op props. Different ops expose different attrs;
            # _create_path_op only sets the ones it finds.
            params = {
                "StepOver":   op_spec.get("stepover_mm"),
                "StepDown":   op_spec.get("stepdown_mm"),
                "ClearanceHeight": 10.0,
                "SafeHeight":      5.0,
            }
            if tc is not None:
                params["ToolController"] = tc

            op = _create_path_op(doc, job, path_op, base_faces, params)
            if op is None:
                per_op_errors.append({"sequence": sequence, "op_code": op_code,
                                      "error": "create failed"})
                continue

            # Recompute is what generates the actual G-code path internally.
            try:
                doc.recompute()
            except Exception as exc:
                sys.stderr.write(f"[cam] recompute failed: {exc}\\n")

            # Post-process to .nc. Per-op output: pass [op] so the file
            # contains just this operation's G-code (no accumulation).
            nc_name = f"seq_{sequence:02d}_{op_code}.nc"
            nc_path = os.path.join(out_dir, nc_name)
            ok, info, size = _post_process(job, nc_path, [op])
            if ok:
                outputs.append({
                    "sequence":  sequence,
                    "op_code":   op_code,
                    "path":      info,
                    "size":      size,
                })
                sys.stderr.write(f"[cam]   → {nc_name} ({size}B)\\n")
            else:
                per_op_errors.append({
                    "sequence": sequence, "op_code": op_code, "error": info,
                })

        payload = {
            "ok": True,
            "outputs": outputs,
            "component_name": component_name,
            "analysis_id":    analysis_id,
        }
        if per_op_errors:
            payload["per_op_errors"] = per_op_errors[:10]
            payload["per_op_error_count"] = len(per_op_errors)
        _emit(payload)
        sys.exit(0)

    except Exception as exc:
        _emit({
            "ok": False, "outputs": [],
            "error": str(exc), "traceback": traceback.format_exc(),
        })
        sys.exit(2)
""")


__all__ = ["FREECAD_SCRIPT"]

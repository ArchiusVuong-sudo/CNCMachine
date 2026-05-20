"""Smoke test for server/infra/persistence.py against live Supabase.

Inserts a synthetic analysis row + component + features + processes using
realistic values that the actual coordinator emits, then cleans up.

Run:
    cd E:\\data
    python -m server.infra.migrations.smoke_persistence
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path


def _load_env() -> None:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        print(f"smoke: no .env at {env_file}", file=sys.stderr)
        sys.exit(2)
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))


async def main() -> int:
    _load_env()
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

    from server.infra.supabase import get_supabase_client
    from server.infra.persistence import (
        persist_analysis_start,
        persist_analysis_complete,
    )

    client = get_supabase_client()
    if client is None:
        print("smoke: supabase client unavailable")
        return 2

    aid = str(uuid.uuid4())
    print(f"smoke: analysis_id={aid}")

    await persist_analysis_start(
        client,
        analysis_id=aid,
        file_name="smoke_test.step",
        step_url=None,
        drawing_url=None,
        user_id=None,
        batch_size=1,
    )
    print("smoke: persist_analysis_start ok")

    extraction_2d = {
        "part_number": "SMOKE-001",
        "revision": "A",
        "description": "smoke test part",
        "material": "Aluminum 6061-T6",
        "dimension_unit": "mm",
        "bom_items": [],
        "drawing_notes": [],
        "dimensions": [],
        "gdt_callouts": [],
        "threads": [],
    }

    assembly_data = {
        "assembly_name": "smoke_assembly",
        "total_volume_mm3": 12345.0,
        "pmi_available": False,
        "welding_contacts": [],
    }

    components = [
        {
            "component_index": 0,
            "name": "smoke_part",
            "description": "single test component",
            "instance_count": 1,
            "part_type": "cnc_milling",
            "volume_mm3": 12345.0,
            "surface_area_mm2": 6789.0,
            "bbox_length_mm": 50.0,
            "bbox_width_mm": 40.0,
            "bbox_height_mm": 25.0,
            "material": "Aluminum 6061-T6",
            "cycle_time_min": 8.5,
            "cost": {"total_usd": 42.50, "machine_usd": 30.0, "labor_usd": 12.5},
            "features": [
                {
                    "feature_type": "pocket",
                    "feature_id": "F0",
                    "key_face_ids": ["Face1_abc", "Face2_def"],
                    "count": 1,
                    "confidence": 0.9,
                    "source": "rule_based",
                    "dimensions": {"depth_mm": 5.0, "width_mm": 10.0},
                }
            ],
            "agentic": {
                "chosen_machine_id": None,
                "machine_class": "3-axis VMC",
                "top_machines": [],
            },
        }
    ]

    # Realistic process rows — these are exactly the categories+process_types
    # the coordinator emits via _OP_CODE_CATEGORY / _OP_CODE_PROCESS_TYPE.
    components_processes = [
        [
            {
                "sequence_order": 1,
                "process_type": "cnc_milling",
                "category": "machining",
                "feature_ids": ["F0"],
                "operation_count": 1,
                "notes": "rough mill the pocket",
                "cycle_time_min": 4.0,
                "agent_phase": "B",
            },
            {
                "sequence_order": 2,
                "process_type": "cnc_milling",
                "category": "machining",
                "feature_ids": ["F0"],
                "operation_count": 1,
                "notes": "finish mill the pocket",
                "cycle_time_min": 3.0,
                "agent_phase": "B",
            },
            {
                "sequence_order": 3,
                "process_type": "deburring",
                "category": "deburring",
                "feature_ids": [],
                "operation_count": 1,
                "cycle_time_min": 1.0,
                "agent_phase": "B",
            },
            {
                "sequence_order": 4,
                "process_type": "inspection",
                "category": "inspection",
                "feature_ids": [],
                "operation_count": 1,
                "cycle_time_min": 0.5,
                "agent_phase": "B",
            },
            # Stress-test the normalizer with free-text variants the agent
            # might emit if the canonical map drifts. These must NOT 500.
            {
                "sequence_order": 5,
                "process_type": "roughing",
                "category": "roughing",
                "feature_ids": ["F0"],
                "operation_count": 1,
                "notes": "agent free-text variant",
                "cycle_time_min": 0.0,
                "agent_phase": "B",
            },
            {
                "sequence_order": 6,
                "process_type": "drilling",
                "category": "drilling",
                "feature_ids": [],
                "operation_count": 1,
                "cycle_time_min": 0.0,
                "agent_phase": "B",
            },
        ]
    ]

    await persist_analysis_complete(
        client,
        analysis_id=aid,
        status="completed",
        extraction_2d=extraction_2d,
        assembly_data=assembly_data,
        components=components,
        components_processes=components_processes,
        cam_output=None,
        elapsed_seconds=12.34,
        trace={"phases": ["1", "2", "3"]},
    )
    print("smoke: persist_analysis_complete ok")

    # Verify rows landed
    a = client.table("a4_analyses").select("id,status,total_minutes,total_usd").eq("id", aid).execute()
    print(f"smoke: a4_analyses -> {a.data}")
    comps = client.table("a4_components").select("id,name,cycle_time_min").eq("analysis_id", aid).execute()
    print(f"smoke: a4_components -> {comps.data}")
    if comps.data:
        cid = comps.data[0]["id"]
        feats = client.table("a4_features").select("feature_id,feature_type,key_face_ids").eq("component_id", cid).execute()
        print(f"smoke: a4_features -> {feats.data}")
        procs = client.table("a4_processes").select("sequence_order,process_type,category").eq("component_id", cid).execute()
        print(f"smoke: a4_processes -> {procs.data}")

    # Cleanup
    client.table("a4_analyses").delete().eq("id", aid).execute()
    print("smoke: cleanup ok")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

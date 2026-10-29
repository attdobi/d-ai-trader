"""Screenshots are scoped to selected rows and frozen before either API sees them."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

import cycle_images as ci

RUN = "20261029T083047"
CFG = "image-scope"


def png(color="red"):
    stream = BytesIO()
    Image.new("RGB", (96, 48), color).save(stream, format="PNG")
    return stream.getvalue()


def row(tmp_path, *, agent="Agent_CNBC", config_dir=True, source_run=RUN, sid=1):
    directory = tmp_path / CFG / source_run if config_dir else tmp_path / source_run
    directory.mkdir(parents=True, exist_ok=True)
    files = [directory/f"{agent}_{i}.png" for i in (1,2)]
    for file in files:
        file.write_bytes(png())
    return {"id": sid, "agent": agent, "run_id": source_run, "config_hash": CFG,
            "data": json.dumps({"agent": agent,"run_id":source_run,"screenshot_paths":list(map(str,files))})}, files


def freeze(root, rows):
    return ci.freeze_summary_images(rows, screenshot_root=root, config_hash=CFG,
                                     decision_run_id="20261029T083100")


def test_two_images_per_selected_source_are_frozen_and_public_metadata_has_no_paths_or_pixels(tmp_path):
    source, files = row(tmp_path)
    bundle=freeze(tmp_path,[source])
    assert len(bundle.attachments)==2
    assert [i.image_id for i in bundle.attachments]==["I01","I02"]
    assert all((i.width,i.height)==(96,48) and i.detail=="high" for i in bundle.attachments)
    assert bundle.public_manifest()["image_count"]==2 and bundle.public_manifest()["omissions"]==[]
    public=json.dumps(bundle.public_manifest())
    assert str(tmp_path) not in public and "relative_path" not in public and "base64" not in public
    original=bundle.chat_parts()
    files[0].write_bytes(png("blue"))
    assert bundle.chat_parts()==original
    assert bundle.attachments[0].sha256!=__import__('hashlib').sha256(files[0].read_bytes()).hexdigest()
    assert "I01" in bundle.describe() and "Agent_CNBC" in bundle.describe()


def test_legacy_paths_and_modern_paths_restore_exact_same_local_manifest(tmp_path):
    one,_=row(tmp_path,config_dir=False)
    two,_=row(tmp_path,agent="Agent_Yahoo_Finance",sid=2)
    bundle=freeze(tmp_path,[one,two])
    restored=ci.load_manifest(bundle.manifest(),screenshot_root=tmp_path)
    assert restored==bundle
    assert restored.decisions_parts()[1]["type"]=="input_image"
    assert restored.chat_parts()[1]["type"]=="image_url"
    assert restored.public_manifest()["snapshot_hash"]==bundle.manifest()["snapshot_hash"]


@pytest.mark.parametrize("change,expected",[
    ("outside","path_outside_root"),
    ("other_run","source_scope_mismatch"),
    ("other_config","source_scope_mismatch"),
    ("other_agent","source_scope_mismatch"),
    ("symlink","unsafe_path"),
    ("duplicate","duplicate_image_reference"),
    ("missing","missing_image"),
    ("invalid","invalid_png"),
])
def test_unselected_unsafe_or_invalid_images_are_omitted_without_reading_other_sources(tmp_path,change,expected):
    source,files=row(tmp_path)
    data=json.loads(source["data"])
    if change=="outside":
        data["screenshot_paths"][0]=str(tmp_path.parent/"secret.png")
    elif change=="other_run":
        data["screenshot_paths"][0]=str(tmp_path/CFG/"20261028T083047"/files[0].name)
    elif change=="other_config":
        data["screenshot_paths"][0]=str(tmp_path/"another-config"/RUN/files[0].name)
    elif change=="other_agent":
        data["screenshot_paths"][0]=str(files[0].with_name("Agent_Fox_Business_1.png"))
    elif change=="symlink":
        target=files[0].with_name("real.png");target.write_bytes(png())
        files[0].unlink();files[0].symlink_to(target)
    elif change=="duplicate":
        data["screenshot_paths"].append(str(files[0]))
    elif change=="missing": files[0].unlink()
    elif change=="invalid": files[0].write_text("not a PNG")
    source["data"]=json.dumps(data)
    bundle=freeze(tmp_path,[source])
    assert expected in {item["reason"] for item in bundle.public_manifest()["omissions"]}
    assert all(i.source_agent==source["agent"] for i in bundle.attachments)


def test_scope_mismatch_uses_no_pixels_and_reports_unknown(tmp_path):
    source,_=row(tmp_path)
    source["run_id"]="20261028T083047"
    bundle=freeze(tmp_path,[source])
    assert not bundle.attachments
    assert bundle.public_manifest()["omissions"][0]["reason"]=="summary_scope_mismatch"
    assert "UNKNOWN" in bundle.describe()


def test_bounds_do_not_silently_expand_from_directory_contents(tmp_path,monkeypatch):
    sources=[row(tmp_path,agent=f"Agent_Source_{i}",sid=i)[0] for i in range(7)]
    bundle=freeze(tmp_path,sources)
    assert len(bundle.attachments)==12 and bundle.offered_count==14
    assert {o["reason"] for o in bundle.public_manifest()["omissions"]}=={"image_count_limit"}
    monkeypatch.setattr(ci,"MAX_IMAGE_BYTES",100)
    smaller=freeze(tmp_path,sources[:1])
    assert not smaller.attachments
    assert {o["reason"] for o in smaller.public_manifest()["omissions"]}=={"image_size_limit"}


def test_replay_refuses_changed_missing_reordered_or_cross_scoped_pixels(tmp_path):
    source,files=row(tmp_path)
    manifest=freeze(tmp_path,[source]).manifest()
    bad=deepcopy(manifest);bad["images"].reverse()
    with pytest.raises(ci.ImageEvidenceError,match="image_order_changed"):
        ci.load_manifest(bad,screenshot_root=tmp_path)
    files[0].write_bytes(png("blue"))
    with pytest.raises(ci.ImageEvidenceError,match="recorded_image_changed"):
        ci.load_manifest(manifest,screenshot_root=tmp_path)
    files[0].unlink()
    with pytest.raises(ci.ImageEvidenceError,match="missing_image"):
        ci.load_manifest(manifest,screenshot_root=tmp_path)


def test_empty_bundle_is_valid_and_no_foreign_config_is_loaded(tmp_path):
    assert not freeze(tmp_path,[]).attachments
    source,_=row(tmp_path);source["config_hash"]="foreign"
    assert not freeze(tmp_path,[source]).attachments
    manifest=freeze(tmp_path,[]).manifest()
    assert ci.load_manifest(manifest,screenshot_root=tmp_path).manifest()==manifest

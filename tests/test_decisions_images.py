"""Hosted images are one shared, bounded context; audit rows retain metadata only."""
from io import BytesIO
import json

from PIL import Image
import pytest
from sqlalchemy import create_engine, text

from cycle_images import FrozenImageBundle, freeze_summary_images
from policy_router import decisions as d
from policy_router.decisions_log import comparison_panel, record_shadow
from policy_router.features import CycleContext
from policy_router.nodes import RouterNode


def bundle(tmp_path, *, color="red", size=(600,400)):
    folder=tmp_path/"cfg"/"20261029T083047"
    folder.mkdir(parents=True,exist_ok=True)
    file=folder/"Agent_CNBC_1.png"
    # Uncompressed test PNG is >400K base64 but well below the per-image cap.
    Image.new("RGB",size,color).save(file,compress_level=0)
    rows=[{"id":1,"agent":"Agent_CNBC","run_id":"20261029T083047",
           "data":{"run_id":"20261029T083047","screenshot_paths":[str(file)]}}]
    return freeze_summary_images(rows,screenshot_root=tmp_path,config_hash="cfg")


def nodes():
    return [RouterNode("DA.ltm.1","ltm","A supplied note",20),
            RouterNode("DA.ltm.2","ltm","A second supplied note",30)]


def response():
    return {"model":"gpt-6-luna","answers":[{"type":"predicate","name":n.node_id,"probability":.8} for n in nodes()],
            "usage":{"input_tokens":5000,"input_tokens_details":{"cached_tokens":0,"cache_write_tokens":3000},"output_tokens":0}}


def test_images_are_shared_once_not_per_guideline_and_do_not_consume_source_text_limit(tmp_path):
    images=bundle(tmp_path)
    payload,_,_,_=d.build_request(CycleContext(),nodes(),image_bundle=images)
    parts=payload["input"][0]["content"]
    assert len(json.dumps(payload))>d.MAX_REQUEST_CHARS
    assert [p["type"] for p in parts]==["input_json","input_text","input_image"]
    assert sum(p.get("type")=="input_image" for p in parts)==1
    assert all("image_url" not in q for q in payload["questions"])
    assert parts[0]["data"]["images"]==images.public_manifest()
    assert parts[2]["detail"]=="high" and parts[2]["image_url"].startswith("data:image/png;base64,")
    assert str(tmp_path) not in json.dumps(payload)
    assert "a person's feelings" in payload["questions"][0]["instructions"]


def test_pixels_and_identity_change_request_hash_but_not_policy_identity(tmp_path):
    a,_,pa,qa=d.build_request(CycleContext(),nodes(),image_bundle=bundle(tmp_path))
    b,_,pb,qb=d.build_request(CycleContext(),nodes(),image_bundle=bundle(tmp_path,color="blue"))
    assert d._hash(a)!=d._hash(b) and pa==pb and qa==qb


def test_text_and_total_request_limits_remain_separate_and_fail_before_transport(tmp_path,monkeypatch):
    images=bundle(tmp_path)
    huge=[RouterNode("DA.ltm.1","ltm","x"*d.MAX_REQUEST_CHARS,1)]
    with pytest.raises(d.DecisionsResponseError,match="request_too_large"):
        d.build_request(CycleContext(),huge,image_bundle=images)
    monkeypatch.setattr(d,"MAX_REQUEST_BYTES",1000)
    result=d.route_shadow_cycle(d.DecisionsSettings(),CycleContext(),nodes(),image_bundle=images,
         api_key="never-send",transport=lambda *_:pytest.fail("oversized payload reached transport"))
    assert not result.request_attempted and result.note=="multimodal_request_too_large"


def test_a_frozen_bundle_cannot_be_attached_to_a_different_named_decision_run(tmp_path):
    images=bundle(tmp_path)
    bound=FrozenImageBundle(images.config_hash,"decision-one",images.attachments,
                            images.offered_count,images.omissions)
    with pytest.raises(d.DecisionsResponseError,match="image_decision_run_mismatch"):
        d.build_request(CycleContext(run_id="decision-two"),nodes(),image_bundle=bound)
    payload,*_=d.build_request(CycleContext(run_id="decision-one"),nodes(),image_bundle=bound)
    assert payload["input"][0]["content"][0]["data"]["images"]["decision_run_id"]=="decision-one"


def test_image_usage_is_billed_as_provider_input_and_audit_contains_no_pixels_or_paths(tmp_path):
    images=bundle(tmp_path)
    calls=[]
    def transport(*args):
        calls.append(args);return response()
    result=d.route_shadow_cycle(d.DecisionsSettings(),CycleContext(),nodes(),image_bundle=images,
                                api_key="private-sentinel",transport=transport)
    assert result.status=="ok" and not result.active and len(calls)==1
    assert result.usage["input_tokens"]==5000
    assert result.cost_usd==pytest.approx((2000*.1+3000*.125)/1e6)
    db=create_engine("sqlite://")
    record_shadow(db,"cfg",60,"run",result)
    public=comparison_panel(db,"cfg")["last_cycle"]
    assert public["image_manifest"]["images"][0]["sha256"]==images.attachments[0].sha256
    with db.connect() as c:
        raw=str(c.execute(text("SELECT * FROM policy_router_comparisons")).fetchall())
    assert "base64," not in raw and str(tmp_path) not in raw and "private-sentinel" not in raw

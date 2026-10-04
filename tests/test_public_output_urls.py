"""Local `/view?type=output` URLs are rewritten only on the MCP response.

comfy-cli keeps speaking to ComfyUI at ``COMFY_LOCAL_URL``. A remote client
receives ``COMFY_MCP_PUBLIC_BASE_URL`` for generated outputs and nothing else.
"""

from __future__ import annotations

import asyncio

import pytest
from conftest import envelope

from comfy_mcp import public_urls, server, upload_session
from comfy_mcp.errors import ComfyCliError

_LOCAL = "http://127.0.0.1:8189/view?filename=x.mp4&subfolder=video&type=output"
_PUBLIC = "https://example.ts.net/view?filename=x.mp4&subfolder=video&type=output"
_ENCODED = (
    "filename=moutons_R2V30_partie2_00001-audio.mp4"
    "&subfolder=video&type=output&note=a%20b"
)


@pytest.fixture
def public_base(monkeypatch):
    monkeypatch.setenv("COMFY_MCP_PUBLIC_BASE_URL", "https://example.ts.net")
    monkeypatch.setenv("COMFY_LOCAL_URL", "http://127.0.0.1:8189")


def test_standard_output_url_uses_the_public_base(public_base):
    assert public_urls._publicize_comfy_output_url(_LOCAL) == _PUBLIC


def test_query_encoding_and_extra_parameters_are_preserved(public_base):
    local = f"http://127.0.0.1:8189/view?{_ENCODED}"
    assert (
        public_urls._publicize_comfy_output_url(local)
        == f"https://example.ts.net/view?{_ENCODED}"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8189/view?filename=x.png&type=input",
        "http://127.0.0.1:8189/view?filename=x.png&type=temp",
        "http://other-host:8189/view?filename=x.mp4&type=output",
        "https://cloud.example/view?filename=x.mp4&type=output",
        "http://127.0.0.1:8189/api/view?filename=x.mp4&type=output",
        "not a url",
    ],
)
def test_non_output_and_foreign_urls_stay(public_base, url):
    assert public_urls._publicize_comfy_output_url(url) == url


def test_no_public_base_preserves_the_object(monkeypatch):
    monkeypatch.delenv("COMFY_MCP_PUBLIC_BASE_URL", raising=False)
    payload = {"outputs": [_LOCAL], "host": "127.0.0.1"}
    assert public_urls.publicize_client_result(payload) is payload


def test_nested_output_structures_are_rewritten_without_touching_metadata(public_base):
    payload = {
        "outputs": [_LOCAL],
        "outputs_by_node": {"123": [_LOCAL]},
        "outputs_by_item": [{"url": _LOCAL, "kind": "video"}],
        "host": "127.0.0.1",
        "port": 8189,
        "state_file": "/tmp/comfy/job.json",
    }
    shown = public_urls.publicize_client_result(payload)
    assert shown["outputs"] == [_PUBLIC]
    assert shown["outputs_by_node"] == {"123": [_PUBLIC]}
    assert shown["outputs_by_item"] == [{"url": _PUBLIC, "kind": "video"}]
    assert payload["outputs"] == [_LOCAL]
    assert shown["host"] == "127.0.0.1"
    assert shown["port"] == 8189
    assert shown["state_file"] == payload["state_file"]


def test_public_base_path_prefix_is_joined(monkeypatch):
    monkeypatch.setenv("COMFY_MCP_PUBLIC_BASE_URL", "https://example.com/comfy/")
    monkeypatch.setenv("COMFY_LOCAL_URL", "http://127.0.0.1:8189")
    assert (
        public_urls._publicize_comfy_output_url(_LOCAL)
        == "https://example.com/comfy/view?filename=x.mp4&subfolder=video&type=output"
    )


def test_run_comfy_keeps_the_local_url_and_the_tool_does_not(public_base, patched_run):
    calls = patched_run(
        stdout=envelope(
            data={
                "outputs": [_LOCAL],
                "host": "127.0.0.1",
                "port": 8189,
                "state_file": "/tmp/comfy/job.json",
            }
        )
    )
    raw = server._run_comfy("jobs", "status", "p1", timeout=60)
    shown = asyncio.run(server.job(action="status", prompt_id="p1"))
    assert raw["outputs"] == [_LOCAL]
    assert shown["outputs"] == [_PUBLIC]
    assert shown["host"] == "127.0.0.1"
    assert shown["state_file"] == "/tmp/comfy/job.json"
    assert calls
    assert all("example.ts.net" not in " ".join(call["cmd"]) for call in calls)


def test_fetch_outputs_publicizes_urls_only_on_the_client_result(
    public_base, patched_run, tmp_path
):
    patched_run(stdout=envelope(data={"urls": [_LOCAL], "outputs": [_LOCAL]}))
    shown = server.fetch_outputs("p1", str(tmp_path), url_only=True)
    assert shown["urls"] == [_PUBLIC]
    assert shown["outputs"] == [_PUBLIC]


def test_upload_explicit_origin_wins_over_the_generic_base(monkeypatch):
    monkeypatch.setenv("COMFY_MCP_UPLOAD_PUBLIC_BASE_URL", "https://uploads.example")
    monkeypatch.setenv("COMFY_MCP_PUBLIC_BASE_URL", "https://example.ts.net")
    assert upload_session.public_base_url() == "https://uploads.example"


def test_upload_falls_back_to_the_generic_public_base(monkeypatch):
    monkeypatch.delenv("COMFY_MCP_UPLOAD_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("COMFY_MCP_PUBLIC_BASE_URL", "https://example.ts.net/comfy")
    assert upload_session.public_base_url() == "https://example.ts.net/comfy"


def test_upload_still_requires_a_base_when_neither_variable_is_set(monkeypatch):
    monkeypatch.delenv("COMFY_MCP_UPLOAD_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("COMFY_MCP_PUBLIC_BASE_URL", raising=False)
    with pytest.raises(ComfyCliError, match="COMFY_MCP_UPLOAD_PUBLIC_BASE_URL"):
        upload_session.public_base_url()


def test_http_public_base_does_not_become_an_upload_origin(monkeypatch):
    monkeypatch.delenv("COMFY_MCP_UPLOAD_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("COMFY_MCP_PUBLIC_BASE_URL", "http://example.ts.net")
    with pytest.raises(ComfyCliError, match="COMFY_MCP_PUBLIC_BASE_URL"):
        upload_session.public_base_url()

from types import SimpleNamespace

import agent


def test_get_vad_instance_prefers_prewarmed_cache():
    cached_vad = object()
    ctx = SimpleNamespace(proc=SimpleNamespace(userdata={"vad": cached_vad}))

    assert agent.get_vad_instance(ctx) is cached_vad

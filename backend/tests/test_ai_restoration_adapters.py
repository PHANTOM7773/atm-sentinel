from app.cv.ai_restoration_adapters import all_ai_status


def test_ai_adapters_report_blocked_without_local_runtime():
    status = all_ai_status()
    assert status["any_ready"] is False
    names = {m["name"] for m in status["models"]}
    assert {"GFPGAN", "Real-ESRGAN", "CodeFormer"} == names
    for m in status["models"]:
        assert m["ready"] is False
        assert m["blockers"]
        assert m["install_requirements"]

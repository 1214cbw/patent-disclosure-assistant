from app.web.main import home


def test_local_web_home_is_available():
    response = home()
    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "Patent Agent" in body
    assert "人工 Checkpoint" in body

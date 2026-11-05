"""Account-owned learning requests, progress, and verified member access."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .support import make_app, make_bundle, make_jobs_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import seekers_store

    db = tmp_path / 'jobs.db'
    dist = tmp_path / 'dist'
    make_jobs_db(db)
    make_bundle(dist)
    monkeypatch.setenv('SEEKERS_DB_PATH', str(tmp_path / 'seekers.db'))
    seekers_store.reset_store()
    return TestClient(make_app(db, dist, tmp_path, cookie_secure=False))


def register(client, email='learner@example.com'):
    response = client.post('/api/auth/register', json={
        'email': email, 'password': 'correct-horse-battery', 'display_name': 'Learner',
    })
    assert response.status_code == 201
    return response.json()['id']


def test_learning_request_and_progress_belong_to_one_seeker(client):
    assert client.get('/api/me/learning').status_code == 401
    register(client)
    assert client.post('/api/me/learning/enrol', json={'course_id': 'unknown'}).status_code == 404
    requested = client.post('/api/me/learning/enrol', json={'course_id': '01'})
    assert requested.status_code == 200
    assert requested.json()['enrolments'][0]['completed_steps'] == 0
    assert client.get('/api/admin/learning/requests').status_code == 403
    invalid = client.put('/api/me/learning/01/progress', json={'completed_steps': 4})
    assert invalid.status_code == 422
    missing = client.put('/api/me/learning/02/progress', json={'completed_steps': 1})
    assert missing.status_code == 409
    saved = client.put('/api/me/learning/01/progress', json={'completed_steps': 2})
    assert saved.json()['enrolments'][0]['completed_steps'] == 2
    client.post('/api/auth/logout')
    client.cookies.clear()
    register(client, 'other@example.com')
    assert client.get('/api/me/learning').json()['enrolments'] == []


def test_member_workshop_requires_staff_verified_membership(client):
    seeker_id = register(client)
    blocked = client.post('/api/me/learning/enrol', json={'course_id': 'member-ai-roundtable'})
    assert blocked.status_code == 403
    assert client.get('/api/me/learning').json()['enrolments'] == []
    assert client.post(f'/api/admin/learning/members/{seeker_id}').status_code == 403
    import seekers_store
    seekers_store.get_store().set_admin(seeker_id)
    assert client.post(f'/api/admin/learning/members/{seeker_id}').status_code == 204
    approved = client.post('/api/me/learning/enrol', json={'course_id': 'member-ai-roundtable'})
    assert approved.status_code == 200
    assert approved.json()['member'] is True
    assert approved.json()['enrolments'][0]['course_id'] == 'member-ai-roundtable'
    queue = client.get('/api/admin/learning/requests')
    assert queue.status_code == 200
    assert queue.json()[0]['email'] == 'learner@example.com'


def test_capstone_submission_and_review_round_trip(client):
    assert client.get('/api/me/learning/quant/capstone').status_code == 401
    seeker_id = register(client)
    assert client.get('/api/me/learning/unknown/capstone').status_code == 404
    assert client.get('/api/me/learning/quant/capstone').json() == {'submission': None}
    links = {'notebook_url': 'https://colab.research.google.com/drive/abc',
             'memo_url': 'https://docs.example.com/memo'}
    rejected = client.put('/api/me/learning/quant/capstone', json={**links, 'memo_url': 'javascript:alert(1)'})
    assert rejected.status_code == 422
    submitted = client.put('/api/me/learning/quant/capstone', json={**links, 'note': '  Ready  '})
    assert submitted.status_code == 200
    assert submitted.json()['submission']['note'] == 'Ready'
    assert submitted.json()['submission']['feedback'] is None

    review = {'feedback': 'Clear thesis; the turnover constraint needs evidence.', 'score': 78}
    path = f'/api/admin/learning/capstones/{seeker_id}/quant/review'
    assert client.post(path, json=review).status_code == 403
    import seekers_store
    seekers_store.get_store().set_admin(seeker_id)
    queue = client.get('/api/admin/learning/capstones').json()
    assert [row['course_id'] for row in queue] == ['quant']
    assert client.post(path, json={**review, 'score': 101}).status_code == 422
    assert client.post(f'/api/admin/learning/capstones/{seeker_id}/missing/review', json=review).status_code == 404
    reviewed = client.post(path, json=review)
    assert reviewed.status_code == 200
    mine = client.get('/api/me/learning/quant/capstone').json()['submission']
    assert mine['score'] == 78 and mine['feedback'].startswith('Clear thesis')

    resubmitted = client.put('/api/me/learning/quant/capstone', json=links)
    assert resubmitted.json()['submission']['feedback'] is None
    assert resubmitted.json()['submission']['score'] is None

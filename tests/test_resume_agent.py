from agents.resume import extract_candidate_info
from agents.resume.agent import agent

def test_resume_agent_exports():
    assert callable(extract_candidate_info)
    assert agent is not None
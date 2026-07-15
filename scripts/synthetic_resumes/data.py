"""聚合全部合成测试简历数据。"""

from scripts.synthetic_resumes.data_java import RESUMES as JAVA
from scripts.synthetic_resumes.data_other import RESUMES as OTHER
from scripts.synthetic_resumes.data_python import RESUMES as PYTHON
from scripts.synthetic_resumes.data_rag import RESUMES as RAG
from scripts.synthetic_resumes.data_risk import RESUMES as RISK

RESUMES: list[dict] = [*RAG, *PYTHON, *JAVA, *RISK, *OTHER]

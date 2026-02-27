# pip install httpx
import json
import os
from typing import List

from settings import settings
import httpx
import asyncio
from loguru import logger

import base64
from langchain.messages import HumanMessage, SystemMessage
from asgiref.sync import sync_to_async
import io
import aiofiles
from core.pdf import PDF2ImageConverter
from langchain_openai import ChatOpenAI


qwen_ocr_llm = ChatOpenAI(
    api_key=settings.DASHSCOPE_API_KEY,
    # model="qwen-vl-ocr-2025-11-20",
    model="qwen-vl-ocr",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    temperature=0.1
)



class PaddleOcr:
    def __init__(self):
        self.job_url = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
        self.access_token = settings.PADDLE_OCR_ACCESS_TOKEN
        self.model_name = "PaddleOCR-VL-1.5"
        self.headers = {
            "Authorization": f"bearer {self.access_token}",
        }
        self.optional_payload = {
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
        }

    async def create_job(self, file: str) -> str:
        if file.startswith("http"):
            self.headers["Content-Type"] = "application/json"
            payload = {
                "fileUrl": file,
                "model": self.model_name,
                "optionalPayload": self.optional_payload
            }
            async with httpx.AsyncClient() as client:
                job_resp = await client.post(self.job_url, json=payload, headers=self.headers)
        else:
            if not os.path.exists(file):
                raise ValueError(f"错误：{file}不存在！")
            data = {
                "model": self.model_name,
                "optionalPayload": json.dumps(self.optional_payload)
            }

            with open(file, "rb") as fp:
                files = {"file": fp}
                async with httpx.AsyncClient() as client:
                    job_resp = await client.post(self.job_url, headers=self.headers, data=data, files=files)

        if job_resp.status_code != 200:
            logger.error(f"文件上传失败：{job_resp.text}, file: {file}")
            raise ValueError(f"文件上传失败：{job_resp.text}")

        job_id = job_resp.json()["data"]["jobId"]
        return job_id

    async def poll_for_state(self, job_id: str) -> str | None:
        while True:
            async with httpx.AsyncClient() as client:
                url = f"{self.job_url}/{job_id}"
                job_result_response = await client.get(url, headers=self.headers)
                if job_result_response.status_code != 200:
                    raise ValueError(f"获取任务：{job_id}状态错误！")
                state = job_result_response.json()["data"]["state"]
                if state == 'pending':
                    logger.info(f"{job_id}peding...")
                elif state == 'running':
                    try:
                        total_pages = job_result_response.json()['data']['extractProgress']['totalPages']
                        extracted_pages = job_result_response.json()['data']['extractProgress']['extractedPages']
                        logger.info(f"任务：{job_id}运行中，{extracted_pages}/{total_pages}")
                    except KeyError:
                        logger.info("The current status of the job is running...")
                elif state == 'done':
                    extracted_pages = job_result_response.json()['data']['extractProgress']['extractedPages']
                    start_time = job_result_response.json()['data']['extractProgress']['startTime']
                    end_time = job_result_response.json()['data']['extractProgress']['endTime']
                    logger.info(f"任务{job_id}执行完成，总共提取{extracted_pages}，开始时间：{start_time}，结束时间：{end_time}")
                    jsonl_url = job_result_response.json()['data']['resultUrl']['jsonUrl']
                    return jsonl_url
                elif state == "failed":
                    error_msg = job_result_response.json()['data']['errorMsg']
                    logger.error(f"任务：{job_id}失败，错误信息：{error_msg}")
                    raise ValueError(error_msg)
            await asyncio.sleep(2)

    async def fetch_parsed_contents(self, jsonl_url: str) -> List[str]:
        contents = []
        async with httpx.AsyncClient() as client:
            jsonl_response = await client.get(jsonl_url)
            if jsonl_response.status_code != 200:
                raise ValueError(f"获取内容失败：{jsonl_response.text}")
            lines = jsonl_response.text.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                result = json.loads(line)["result"]
                for res in result["layoutParsingResults"]:
                    contents.append(res["markdown"]["text"])
        return contents


EXTRACT_CANDIDATE_FROM_RESUME_SYSTEM_PROMPT = """
    你是一位经验丰富的人力资源（HR）专家，擅长从各种格式的简历（如 PDF、Word、图片等文档中提取的文本）中精准、高效地提取关键信息。
    你的任务是仔细分析提供的简历文本，并将其结构化为JSON格式。

    请遵循以下规则：

    1. **输出格式**: 必须以一个完整的JSON对象输出。
    2. **字段提取**: 提取以下字段。如果简历中没有明确提供某个字段，请使用 `null` 作为其值。
        - `name`: 姓名 (string)
        - `gender`: 性别 (string, e.g., "男", "女")
        - `birth_date`: 出生日期 (string, 尽量格式化为 YYYY-MM-DD)，如果只有年龄，则根据现在的时间和年龄计算出出生年份，月份和日期用01填充。
        - `phone_number`: 手机号 (string)
        - `email`: 邮箱 (string)
        - `highest_education`: 最高学历 (string, e.g., "本科", "硕士", "博士")
        - `education_experience`: 教育经历 (string，将所有教育经历都提取成一个字符串即可。)
        - `work_experience`: 工作经验 (string，将所有工作经历都提取成一个字符串即可。)
        - `project_experience`: 项目经验 (string，将所有项目经历都提取成一个字符串即可。)
        - `self_evaluation`: 自我评价 (string)
        - `skills`: 技能清单 (string，将所有技能都提取成一个字符串即可。)
        - `other_info`: 其他任何你认为有价值的补充信息 (string)

    3. **灵活性与准确性**: 简历的表述可能不尽相同，例如“工作经验”可能被称为“工作经历”。请理解上下文，准确提取信息。对于日期，尽力提取出年和月。
    4. **处理噪声**: 从文件转换的文本可能包含格式错误或无关字符，请忽略这些噪声，专注于提取有效信息。
"""

class QwenOcr:
    def __init__(self):
        pass

    async def convert_pdf_to_image(self, file_path: str) -> io.BytesIO:
        conveter = PDF2ImageConverter()
        buffer = await sync_to_async(conveter.pdf_to_single_compressed_image)(file_path)
        return buffer

    async def extract_info_from_resume(self, file_path: str) -> str:
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in [".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff"]:
            raise ValueError(f"Unsupported file extension: {file_ext}")

        if file_ext == ".pdf":
            buffer = await self.convert_pdf_to_image(file_path)
            image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        else:
            async with aiofiles.open(file_path, "rb") as fp:
                image_b64 = base64.b64encode(await fp.read()).decode("utf-8")
        # 1. 调用OCR大模型提取文字
        ocr_system_msg = SystemMessage(content=EXTRACT_CANDIDATE_FROM_RESUME_SYSTEM_PROMPT)
        ocr_msg = HumanMessage(content=[
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
            },
            {"type": "text", "text": f"请提取文件中的所有文字信息。"}
        ])
        ocr_response = await qwen_ocr_llm.ainvoke([ocr_system_msg, ocr_msg])
        extracted_text = ocr_response.content

        return extracted_text

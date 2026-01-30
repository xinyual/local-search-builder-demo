from constants import *
import requests
import time
import asyncio
from preparation import *
from manifest import *
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from scan_loop import *

def wait_opensearch():
    for _ in range(180):
        try:
            r = requests.get(OPENSEARCH_URL, timeout=1)
            if r.status_code < 500:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("OpenSearch not reachable")

async def wait_to_deploy_model_bg(task_id: str, type_str: str):
    model_id = ""
    try:
        # 1) wait register/download task
        while True:
            task_status = await asyncio.to_thread(get_task_status, get_os_client(), task_id)

            state = task_status.get("state")
            if state == "COMPLETED":
                model_id = task_status["model_id"]
                break
            elif state == "FAILED":
                GLOBAL_RESOURCE[type_str] = task_status.get("error", "unknown error")
                return

            await asyncio.sleep(20)

        # 2) deploy model
        deploy_model_task = await asyncio.to_thread(deploy_model, get_os_client(), model_id)
        GLOBAL_RESOURCE[type_str] = f"deploy model with task id: {deploy_model_task}"

        # 3) wait deploy task
        while True:
            task_status = await asyncio.to_thread(get_task_status, get_os_client(), deploy_model_task)

            state = task_status.get("state")
            if state == "COMPLETED":
                GLOBAL_RESOURCE[type_str] = model_id
                if type_str == DENSE_MODEL_ID:
                    GLOBAL_RESOURCE[DENSE_QUERY_MODEL_ID] = model_id
                return
            elif state == "FAILED":
                GLOBAL_RESOURCE[type_str] = task_status.get("error", "unknown error")
                return

            await asyncio.sleep(20)

    except asyncio.CancelledError:
        GLOBAL_RESOURCE[type_str] = "cancelled"
        raise
    except Exception as e:
        GLOBAL_RESOURCE[type_str] = f"exception: {repr(e)}"
        return

async def init_things_bg():
    put_config(get_os_client())
    sparse_model_task_id = await asyncio.to_thread(register_sparse_model, get_os_client())
    dense_model_task_id  = await asyncio.to_thread(register_dense_model,  get_os_client())

    GLOBAL_RESOURCE[SPARSE_MODEL_ID] = f"downloading with task id: {sparse_model_task_id}"
    GLOBAL_RESOURCE[DENSE_MODEL_ID] = f"downloading with task id: {dense_model_task_id}"
    GLOBAL_RESOURCE[DENSE_QUERY_MODEL_ID] = f"downloading with task id: {dense_model_task_id}"

    sparse_task = asyncio.create_task(
        wait_to_deploy_model_bg(sparse_model_task_id, SPARSE_MODEL_ID),
        name="wait_sparse_model"
    )
    dense_task = asyncio.create_task(
        wait_to_deploy_model_bg(dense_model_task_id, DENSE_MODEL_ID),
        name="wait_dense_model"
    )

    return [sparse_task, dense_task]

@asynccontextmanager
async def lifespan(app: FastAPI):
    pdf_opts = PdfPipelineOptions()
    pdf_opts.do_ocr = False
    pdf_opts.do_picture_description = False
    pdf_opts.do_table_structure = False
    print("forbid OCR")
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts),
        }
    )
    GLOBAL_RESOURCE["converter"] = converter

    GLOBAL_RESOURCE.setdefault("watch_map", {})
    await asyncio.to_thread(create_manifest_index, get_os_client())
    app.state.watch_task = asyncio.create_task(scan_loop())

    app.state.bg_tasks = []
    #bg_tasks = await init_things_bg()
    #app.state.bg_tasks.extend(bg_tasks)

    yield
    app.state.watch_task.cancel()
    for t in app.state.bg_tasks:
        t.cancel()
    await asyncio.gather(*app.state.bg_tasks, return_exceptions=True)


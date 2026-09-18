"""根据查询结果生成自然语言回答"""

import json

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.answer_grounding import answer_is_grounded, fallback_answer
from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.nodes.progress import progress_event
from app.agent.state import DataAgentState
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt

_RESULT_ROW_LIMIT = 20


async def generate_answer(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """把执行结果转成可直接展示的中文回答"""
    step = "生成回答"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        rows = state.get("execution_result") or []
        prompt = PromptTemplate(
            template=load_prompt("generate_answer"),
            input_variables=["query", "result"],
        )
        chain = prompt | llm | StrOutputParser()
        answer = (
            await chain.ainvoke(
                {
                    "query": state["query"],
                    "result": json.dumps(
                        rows[:_RESULT_ROW_LIMIT],
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            )
        ).strip()
        if not answer_is_grounded(answer, rows, state["query"]):
            logger.warning(f"回答数字无法对账，已替换兜底文案：{answer}")
            answer = fallback_answer(rows)
        logger.info(f"生成的回答：{answer}")
        writer(progress_event(step, "success"))
        writer({"type": "answer", "text": answer})
        return {"answer": answer, "error": None}
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise
